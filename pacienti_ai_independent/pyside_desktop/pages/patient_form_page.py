from __future__ import annotations

import re
from datetime import datetime, date
from typing import Dict, List

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
)
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import QEvent, QObject, QStringListModel, QTimer, Qt

from db.address_format import (
    ADDRESS_STREET_TYPES,
    canonical_street_type,
    compose_address_details_from_parts,
    compose_structured_address,
    parse_address_details_to_parts,
    parse_structured_address,
)
from db.cnp_utils import (
    CNP_INPUT_ACCEPTABLE,
    derive_cnp_data,
    enforce_max_valid_cnp_prefix,
    validate_cnp_partial,
)
from db.drg_estimate import estimate_drg_icm
from db.icd10_catalog import (
    icd10_catalog_is_configured,
    icd10_catalog_origin_label,
    icd10_merge_secondary_choice,
    icd10_secondary_field_last_segment_query,
    load_icd10_catalog,
    search_icd10_options,
)
from db.icd10_codec import (
    extract_icd10_code_from_text,
    normalize_icd10_code,
    parse_icd10_codes_csv,
    serialize_icd10_codes_csv,
)
from db.ro_localities_catalog import load_ro_localities_catalog
from db.street_catalog_sync import fetch_street_catalog_for_locality_from_osm
from db.time_utils import now_ts
from runtime_paths import EXPORTS_DIR

from pyside_desktop.pages.base_page import BasePage
from pyside_desktop.rbac import has_role
from pyside_desktop.services import clinical_qt
from pyside_desktop.services import page_draft_store
from pyside_desktop.services.export_qt import write_csv_rows
from pyside_desktop.services.patient_store import empty_patient_payload, row_to_payload
from pyside_desktop.widgets.cnp_line_edit import wire_strict_cnp_input
from pyside_desktop.widgets.field_markers import mark_critical_field
from pyside_desktop.shared_qss import (
    get_ui_theme,
    register_post_theme_apply_hook,
    unregister_post_theme_apply_hook,
)
from pyside_desktop.widgets.modern_cards import CollapsibleSectionCard, SectionCard
from pyside_desktop.widgets.table_utils import make_table


class _IcdCompleterPopupShowNotifier(QObject):
    """QCompleter.popup() este QListView — fără semnal aboutToShow (acela e pe QMenu)."""

    def __init__(self, on_show, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_show = on_show

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: ARG002
        if event.type() == QEvent.Type.Show:
            self._on_show()
        return False


class PatientFormPage(BasePage):
    """Fișă pacient – câmpuri principale + salvare locală SQLite."""

    _PF_ADDRESS_UI_KEY = "PF_ADDRESS_UI"
    _ICD_COMPLETER_DEBOUNCE_MS = 180
    _TEXT_KEYS = ("medical_history", "allergies", "chronic_conditions", "current_medication")
    _MED_DUP_KEY = "MEDICATION_ALLOW_SAME_DAY_DUPLICATE"
    _TL_FILTER_KEY = "PF_TIMELINE_FILTER"
    _TL_LIMIT_KEY = "PF_TIMELINE_LIMIT"
    _TL_SEARCH_KEY = "PF_TIMELINE_SEARCH"
    _PF_DRAFT_PREFIX = "PF_LONGTEXT_DRAFT"

    def _make_icon_button(
        self,
        text: str,
        icon: QStyle.StandardPixmap,
        *,
        clicked=None,
        object_name: str | None = None,
        tooltip: str | None = None,
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setIcon(self.style().standardIcon(icon))
        btn.setAutoDefault(False)
        if clicked is not None:
            btn.clicked.connect(clicked)
        if object_name:
            btn.setObjectName(object_name)
        if tooltip:
            btn.setToolTip(tooltip)
        return btn

    def __init__(self, db, session, parent=None) -> None:
        super().__init__(db, session, parent)
        self._row_version: int | None = None
        self._edits: Dict[str, QLineEdit] = {}
        self._texts: Dict[str, QTextEdit] = {}
        self._admission_rows: list[dict] = []
        self._medication_rows: list[dict] = []
        self._summary_label = QLabel("")
        self._summary_diag_label = QLabel("")
        self._summary_admission_label = QLabel("")
        self._risk_warning_label = QLabel("")
        self._timeline_rows: List[dict] = []
        self._timeline_filter: QComboBox | None = None
        self._timeline_search: QLineEdit | None = None
        self._timeline_limit: QComboBox | None = None
        self._content_layout: QVBoxLayout | None = None
        self._timeline_search_debounce = QTimer(self)
        self._timeline_search_debounce.setSingleShot(True)
        self._timeline_search_debounce.setInterval(350)
        self._timeline_search_debounce.timeout.connect(self._on_timeline_search_debounced)
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(900)
        self._draft_timer.timeout.connect(self._flush_longtext_draft)
        self._draft_restore_prompted = False
        self._draft_is_loading = False
        self._save_btn: QPushButton | None = None
        self._new_patient_snapshot: Dict[str, str] = {}
        self._new_btn: QPushButton | None = None
        self._reload_btn: QPushButton | None = None
        self._cnp_feedback_label: QLabel | None = None
        self._cnp_autofilled_birth_date = ""
        self._cnp_autofilled_gender = ""
        self._identity_auto_labels: Dict[str, QLabel] = {}
        self._icd_catalog_cache: Dict[str, str] | None = None
        self._icd_secondary_snapshot = ""
        self._icd_primary_model: QStringListModel | None = None
        self._icd_secondary_model: QStringListModel | None = None
        self._icd_primary_debounce = QTimer(self)
        self._icd_primary_debounce.setSingleShot(True)
        self._icd_primary_debounce.setInterval(self._ICD_COMPLETER_DEBOUNCE_MS)
        self._icd_primary_debounce.timeout.connect(self._on_icd_primary_debounce)
        self._icd_secondary_debounce = QTimer(self)
        self._icd_secondary_debounce.setSingleShot(True)
        self._icd_secondary_debounce.setInterval(self._ICD_COMPLETER_DEBOUNCE_MS)
        self._icd_secondary_debounce.timeout.connect(self._on_icd_secondary_debounce)
        self._icd_secondary_popup_show_notifier: QObject | None = None
        self._icd_primary_summary: QLabel | None = None
        self._icd_secondary_summary: QLabel | None = None
        self._icd_loading_label: QLabel | None = None
        self._icd_search_busy = 0
        self._icd_loading_show_timer = QTimer(self)
        self._icd_loading_show_timer.setSingleShot(True)
        self._icd_loading_show_timer.setInterval(140)
        self._icd_loading_show_timer.timeout.connect(self._on_icd_loading_show_timeout)
        self._icd_secondary_summary_debounce = QTimer(self)
        self._icd_secondary_summary_debounce.setSingleShot(True)
        self._icd_secondary_summary_debounce.setInterval(220)
        self._icd_secondary_summary_debounce.timeout.connect(self._refresh_icd_secondary_summary)
        self._new_patient_dirty_label: QLabel | None = None
        self._dirty_debounce = QTimer(self)
        self._dirty_debounce.setSingleShot(True)
        self._dirty_debounce.setInterval(80)
        self._dirty_debounce.timeout.connect(self._sync_new_patient_dirty_indicator)
        self._icd_catalog_banner: QLabel | None = None
        self._save_btn_default_text = "Salvează"
        self._addr_localities_catalog: Dict[str, List[str]] = load_ro_localities_catalog()
        self._addr_street_type_by_name: Dict[str, str] = {}
        self._address_ui_syncing = False
        self._addr_county: QComboBox | None = None
        self._addr_locality: QComboBox | None = None
        self._addr_zone: QLineEdit | None = None
        self._addr_street_type: QComboBox | None = None
        self._addr_street_name: QComboBox | None = None
        self._addr_number: QLineEdit | None = None
        self._addr_block: QLineEdit | None = None
        self._addr_stair: QLineEdit | None = None
        self._addr_floor: QLineEdit | None = None
        self._addr_apartment: QLineEdit | None = None
        self._addr_intercom: QLineEdit | None = None
        self._addr_extra: QLineEdit | None = None
        self._addr_catalog_status_label: QLabel | None = None
        self._addr_catalog_import_btn: QPushButton | None = None
        self._addr_structured_widgets = False
        self._address_host: QWidget | None = None
        self._patient_form_grid: QGridLayout | None = None
        self._address_embedded_in_grid = False

        root = self.create_scrollable_outer_layout()
        self._content_layout = root
        title = QLabel("Fișă pacient")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        summary_card = SectionCard("Rezumat pacient")
        summary_layout = QVBoxLayout()
        self._summary_label.setObjectName("PatientSummaryMain")
        self._summary_diag_label.setObjectName("PatientSummaryDiag")
        self._summary_admission_label.setObjectName("PatientSummaryAdmission")
        self._risk_warning_label.setObjectName("PatientRiskWarning")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addWidget(self._summary_diag_label)
        summary_layout.addWidget(self._summary_admission_label)
        summary_layout.addWidget(self._risk_warning_label)
        summary_card.add_layout(summary_layout)
        root.addWidget(summary_card)
        self._hint = QLabel("Selectați un pacient din listă sau creați unul nou.")
        self._hint.setObjectName("PageHint")
        hint_card = SectionCard("Context")
        hint_card.add_widget(self._hint)
        self._new_patient_dirty_label = QLabel("")
        self._new_patient_dirty_label.setObjectName("NewPatientDirtyLabel")
        self._new_patient_dirty_label.setWordWrap(True)
        hint_card.add_widget(self._new_patient_dirty_label)
        self._shortcut_hint = QLabel(
            "Scurtături: Ctrl+S — salvează (pacient nou) · Ctrl+E — pacient nou · Esc — reîncarcă/reset · "
            "Ctrl+N — medicație nouă (cu pacient) · Return — actualizează medicație selectată"
        )
        self._shortcut_hint.setObjectName("HintLabel")
        self._shortcut_hint.setWordWrap(True)
        hint_card.add_widget(self._shortcut_hint)
        export_row = QHBoxLayout()
        export_row.addStretch()
        export_row.addWidget(
            self._make_icon_button(
                "Export pacient…",
                QStyle.StandardPixmap.SP_DialogOpenButton,
                clicked=self._open_export_patient_dialog,
            ),
        )
        hint_card.add_layout(export_row)
        root.addWidget(hint_card)

        inner_layout = root
        form_card = SectionCard("Date pacient")
        self._icd_catalog_banner = QLabel("")
        self._icd_catalog_banner.setObjectName("HintLabel")
        self._icd_catalog_banner.setWordWrap(True)
        self._icd_catalog_banner.hide()
        form_card.add_widget(self._icd_catalog_banner)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self._patient_form_grid = grid

        simple_keys = [
            ("first_name", "Prenume"),
            ("last_name", "Nume"),
            ("cnp", "CNP"),
            ("phone", "Telefon"),
            ("email", "E-mail"),
            ("birth_date", "Data nașterii (YYYY-MM-DD)"),
            ("gender", "Sex"),
            ("address", "Adresă"),
            ("occupation", "Ocupație"),
            ("insurance_provider", "Asigurător"),
            ("insurance_id", "Nr. asigurare"),
            ("emergency_contact_name", "Contact urgent – nume"),
            ("emergency_contact_phone", "Contact urgent – telefon"),
            ("blood_type", "Grupă sanguină"),
            ("height_cm", "Înălțime (cm)"),
            ("weight_kg", "Greutate (kg)"),
        ]
        row = 0
        for key, label in simple_keys:
            if key == "address":
                if self._pf_address_ui_structured():
                    row = self._populate_structured_address_grid_rows(grid, row, label)
                else:
                    lab_addr = QLabel(label)
                    lab_addr.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    grid.addWidget(lab_addr, row, 0)
                    self._address_host = QWidget()
                    self._address_host.setSizePolicy(
                        QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Minimum,
                    )
                    grid.addWidget(self._address_host, row, 1)
                    self._build_address_into_host(False)
                    row += 1
                continue
            grid.addWidget(QLabel(label), row, 0)
            e = QLineEdit()
            self._edits[key] = e
            if key == "cnp":
                wire_strict_cnp_input(e)
                e.setToolTip(
                    "Cod numeric personal (RO): exact 13 cifre, fără spații. "
                    "Cifra 13 este cifră de control (algoritm cu pondere). "
                    "Prefixul este validat pe măsură ce tastați."
                )
                cnp_row = QHBoxLayout()
                self._cnp_feedback_label = QLabel("")
                self._cnp_feedback_label.setObjectName("CnpFeedbackLabel")
                self._cnp_feedback_label.setWordWrap(True)
                self._cnp_feedback_label.setMinimumWidth(0)
                cnp_row.addWidget(e, stretch=1)
                cnp_row.addWidget(self._cnp_feedback_label, stretch=0)
                grid.addLayout(cnp_row, row, 1)
                e.textChanged.connect(self._on_cnp_field_text_changed)
            else:
                if key in {"birth_date", "gender"}:
                    identity_row = QHBoxLayout()
                    identity_hint = QLabel("auto din CNP")
                    identity_hint.setObjectName("HintLabel")
                    identity_hint.hide()
                    identity_row.addWidget(e, stretch=1)
                    identity_row.addWidget(identity_hint, stretch=0)
                    self._identity_auto_labels[key] = identity_hint
                    grid.addLayout(identity_row, row, 1)
                    e.textChanged.connect(
                        lambda _t, field_key=key: self._on_identity_field_text_changed(field_key)
                    )
                else:
                    grid.addWidget(e, row, 1)
            row += 1
        for k in ("first_name", "last_name", "cnp"):
            mark_critical_field(self._edits[k])

        row = self._add_icd10_diagnosis_fields(grid, row)

        for key, label in (("free_diagnosis_text", "Diagnostic liber"),):
            grid.addWidget(QLabel(label), row, 0)
            e = QLineEdit()
            self._edits[key] = e
            grid.addWidget(e, row, 1)
            row += 1

        form_card.add_layout(grid)
        inner_layout.addWidget(form_card)

        hist_card = CollapsibleSectionCard("Istoric clinic și observații (texte)", start_collapsed=False)
        hist_grid = QGridLayout()
        hist_grid.setHorizontalSpacing(12)
        hist_grid.setVerticalSpacing(8)
        hist_grid.setColumnStretch(1, 1)
        hrow = 0
        _text_field_labels = {
            "medical_history": "Istoric medical",
            "allergies": "Alergii",
            "chronic_conditions": "Afecțiuni cronice",
            "current_medication": "Medicație curentă",
        }
        for key in self._TEXT_KEYS:
            hist_grid.addWidget(QLabel(_text_field_labels[key]), hrow, 0)
            t = QTextEdit()
            t.setMaximumHeight(80)
            self._texts[key] = t
            hist_grid.addWidget(t, hrow, 1)
            hrow += 1

        _extra_text_labels = {
            "surgeries": "Intervenții chirurgicale",
            "family_history": "Istoric familial",
            "lifestyle_notes": "Stil de viață / observații",
        }
        for key in ("surgeries", "family_history", "lifestyle_notes"):
            hist_grid.addWidget(QLabel(_extra_text_labels[key]), hrow, 0)
            t = QTextEdit()
            t.setMaximumHeight(60)
            self._texts[key] = t
            hist_grid.addWidget(t, hrow, 1)
            hrow += 1

        hist_card.add_layout(hist_grid)
        inner_layout.addWidget(hist_card)

        risk_card = SectionCard("Risc & avertizări")
        risk_layout = QVBoxLayout()
        self._risk_summary_label = QLabel("")
        risk_layout.addWidget(self._risk_summary_label)
        risk_card.add_layout(risk_layout)
        inner_layout.addWidget(risk_card)

        admissions_card = SectionCard("Internări pacient")
        self._admissions_hint = QLabel("Internările asociate pacientului selectat apar aici.")
        admissions_card.add_widget(self._admissions_hint)
        self._admissions_table = make_table(
            ["ID", "MRN", "Tip", "Triaj", "Secție", "Stare", "Admis la", "Externat la"]
        )
        self._admissions_table.setMinimumHeight(320)
        self._admissions_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._admissions_table.cellDoubleClicked.connect(self._open_selected_admission)
        admissions_card.add_widget(self._admissions_table, 1)
        adm_actions = QHBoxLayout()
        adm_actions.addWidget(
            self._make_icon_button(
                "Reîncarcă internări",
                QStyle.StandardPixmap.SP_BrowserReload,
                clicked=self._refresh_admissions_for_current_patient,
            )
        )
        adm_actions.addWidget(
            self._make_icon_button(
                "Deschide modul Internări",
                QStyle.StandardPixmap.SP_DialogOpenButton,
                clicked=lambda: self.session.navigate_requested.emit("Internări"),
            )
        )
        adm_actions.addWidget(QPushButton("Checklist caz", clicked=self._open_case_checklist))
        adm_actions.addStretch()
        admissions_card.add_layout(adm_actions)
        inner_layout.addWidget(admissions_card, 1)

        medication_card = SectionCard("Medicație zilnică")
        self._medication_hint = QLabel(
            "Înregistrează medicația administrată zilnic pentru pacientul selectat. "
            "Cheie setări: MEDICATION_ALLOW_SAME_DAY_DUPLICATE (0/1)."
        )
        medication_card.add_widget(self._medication_hint)
        self._medication_dup_status = QLabel("")
        medication_card.add_widget(self._medication_dup_status)
        mg = QGridLayout()
        self._med_day = QLineEdit(now_ts()[:10])
        self._med_text = QLineEdit()
        self._med_text.setPlaceholderText("Ex: Ceftriaxonă 1g x2/zi")
        self._med_notes = QLineEdit()
        self._med_notes.setPlaceholderText("Observații opționale")
        mg.addWidget(QLabel("Data (YYYY-MM-DD):"), 0, 0)
        mg.addWidget(self._med_day, 0, 1)
        mg.addWidget(QLabel("Medicație:"), 1, 0)
        mg.addWidget(self._med_text, 1, 1)
        mg.addWidget(QLabel("Observații:"), 2, 0)
        mg.addWidget(self._med_notes, 2, 1)
        medication_card.add_layout(mg)
        mh_top = QHBoxLayout()
        mh_top.addWidget(QPushButton("Adaugă medicația zilei", clicked=self._add_medication_entry))
        mh_top.addWidget(
            self._make_icon_button(
                "Reîncarcă istoric medicație",
                QStyle.StandardPixmap.SP_BrowserReload,
                clicked=self._refresh_medication_entries,
            )
        )
        mh_top.addStretch()
        medication_card.add_layout(mh_top)
        self._med_filter_from = QLineEdit()
        self._med_filter_from.setPlaceholderText("De la (YYYY-MM-DD)")
        self._med_filter_to = QLineEdit()
        self._med_filter_to.setPlaceholderText("Până la (YYYY-MM-DD)")
        self._med_filter_q = QLineEdit()
        self._med_filter_q.setPlaceholderText("Caută în medicație/observații")
        self._med_filter_apply_btn = QPushButton("Aplică filtru", clicked=self._refresh_medication_entries)
        self._med_export_btn = self._make_icon_button(
            "Export CSV",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            clicked=self._export_medication_csv,
        )
        self._med_today_btn = QPushButton("Astăzi", clicked=self._set_med_filter_today)
        self._med_reset_filters_btn = QPushButton("Reset filtre", clicked=self._reset_medication_filters)
        mh_filters = QHBoxLayout()
        mh_filters.addWidget(self._med_filter_from)
        mh_filters.addWidget(self._med_filter_to)
        mh_filters.addWidget(self._med_filter_q, 1)
        mh_filters.addWidget(self._med_today_btn)
        mh_filters.addWidget(self._med_reset_filters_btn)
        mh_filters.addWidget(self._med_filter_apply_btn)
        mh_filters.addWidget(self._med_export_btn)
        medication_card.add_layout(mh_filters)
        mh2 = QHBoxLayout()
        mh2.addWidget(QPushButton("Încarcă rândul selectat în formular", clicked=self._load_selected_medication_into_form))
        mh2.addWidget(QPushButton("Actualizează rândul selectat", clicked=self._update_selected_medication_entry))
        mh2.addWidget(
            self._make_icon_button(
                "Șterge rândul selectat",
                QStyle.StandardPixmap.SP_TrashIcon,
                clicked=self._delete_selected_medication_entry,
            )
        )
        mh2.addStretch()
        medication_card.add_layout(mh2)
        self._medication_table = make_table(["Data", "Medicație", "Observații", "Înregistrat la"])
        self._medication_table.setMinimumHeight(220)
        self._medication_table.cellDoubleClicked.connect(self._on_medication_dblclick)
        medication_card.add_widget(self._medication_table, 1)
        inner_layout.addWidget(medication_card, 1)
        self._med_update_shortcut = QShortcut(QKeySequence("Return"), self)
        self._med_update_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._med_update_shortcut.activated.connect(self._update_selected_medication_entry)
        self._med_add_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self._med_add_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._med_add_shortcut.activated.connect(self._add_medication_entry)

        actions_row1 = QHBoxLayout()
        new_btn = self._make_icon_button(
            "Pacient nou",
            QStyle.StandardPixmap.SP_FileDialogNewFolder,
            clicked=self._new_patient,
            tooltip="Inițializează formular pacient nou (Ctrl+E).",
        )
        self._new_btn = new_btn
        actions_row1.addWidget(new_btn)
        reload_btn = self._make_icon_button(
            "Reîncarcă din baza de date",
            QStyle.StandardPixmap.SP_BrowserReload,
            clicked=self.reload_from_session,
            tooltip="Reîncarcă pacientul curent sau resetează formularul (Esc).",
        )
        self._reload_btn = reload_btn
        actions_row1.addWidget(reload_btn)
        save_btn = self._make_icon_button(
            self._save_btn_default_text,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            clicked=self._save,
            object_name="primaryButton",
            tooltip="Salvează pacient nou (Ctrl+S).",
        )
        self._save_btn = save_btn
        actions_row1.addWidget(save_btn)
        actions_row1.addWidget(
            self._make_icon_button(
                "Șterge draft texte",
                QStyle.StandardPixmap.SP_TrashIcon,
                clicked=self._discard_longtext_draft,
            )
        )
        actions_row1.addWidget(QPushButton("Estimare DRG/ICM (local)", clicked=self._estimate_drg))
        actions_row1.addWidget(
            self._make_icon_button(
                "Șterge pacientul…",
                QStyle.StandardPixmap.SP_TrashIcon,
                clicked=self._delete_patient,
            )
        )
        actions_row1.addStretch()
        actions_row2 = QHBoxLayout()
        wiz_btn = self._make_icon_button(
            "Wizard pacient → internare",
            QStyle.StandardPixmap.SP_ArrowRight,
            clicked=self._open_new_patient_admission_wizard,
            tooltip="Creare ghidată: pacient nou și internare (schiță salvată în Setări până finalizați).",
        )
        actions_row2.addWidget(wiz_btn)
        actions_row2.addWidget(
            self._make_icon_button(
                "Creează internare",
                QStyle.StandardPixmap.SP_FileDialogNewFolder,
                clicked=self._open_create_admission,
            )
        )
        actions_row2.addWidget(
            self._make_icon_button(
                "Deschide Vizite",
                QStyle.StandardPixmap.SP_DialogOpenButton,
                clicked=self._open_visits_module,
            )
        )
        actions_row2.addWidget(
            self._make_icon_button(
                "Deschide Ordine",
                QStyle.StandardPixmap.SP_DialogOpenButton,
                clicked=self._open_orders_module,
            )
        )
        actions_row2.addWidget(
            self._make_icon_button(
                "Deschide Vitale",
                QStyle.StandardPixmap.SP_DialogOpenButton,
                clicked=self._open_vitals_module,
            )
        )
        actions_row2.addStretch()
        actions_card = SectionCard("Acțiuni")
        actions_card.add_layout(actions_row1)
        actions_card.add_layout(actions_row2)
        root.addWidget(actions_card)

        session.patient_selected.connect(lambda _pid: self.reload_from_session())
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self._on_shortcut_save)
        self._new_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        self._new_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._new_shortcut.activated.connect(self._on_shortcut_new)
        self._cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._cancel_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._cancel_shortcut.activated.connect(self._on_shortcut_cancel)
        self._timeline_reset_shortcut = QShortcut(QKeySequence("F5"), self)
        self._timeline_reset_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._timeline_reset_shortcut.activated.connect(self._reset_timeline_filters)
        for key in (
            "medical_history",
            "allergies",
            "chronic_conditions",
            "current_medication",
            "surgeries",
            "family_history",
            "lifestyle_notes",
        ):
            txt = self._texts.get(key)
            if txt is not None:
                txt.textChanged.connect(self._schedule_longtext_draft)

        self._wire_patient_form_tab_order()
        self._wire_new_patient_dirty_tracking()

        register_post_theme_apply_hook(self._on_theme_refresh_patient_form)
        self.destroyed.connect(self._unregister_theme_apply_hook)

    def _pf_address_ui_structured(self) -> bool:
        raw = (self.db.get_setting(self._PF_ADDRESS_UI_KEY, "structured") or "structured").strip().lower()
        return raw in ("structured", "struct", "dropdown", "1", "yes", "true", "on")

    @staticmethod
    def _clear_layout_of_widget(host: QWidget) -> None:
        lay = host.layout()
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        lay.deleteLater()
        host.setLayout(None)

    def _address_edit_set_text(self, text: str) -> None:
        w = self._edits.get("address")
        if w is None:
            return
        if isinstance(w, QTextEdit):
            w.setPlainText(text)
        else:
            w.setText(text)

    def _form_grid_label(self, text: str) -> QLabel:
        return QLabel(text)

    def _wire_addr_searchable_combo(self, cb: QComboBox, placeholder: str) -> None:
        cb.setObjectName("AddressStructCombo")
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cb.setMinimumWidth(168)
        cb.setMinimumHeight(32)
        cb.setToolTip(
            "Lista: click pe săgeata din dreapta (▼). Căutare: tastați în câmp."
        )
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(14)
        le = cb.lineEdit()
        if le is not None:
            le.setPlaceholderText(placeholder)

    def _wire_addr_choice_combo(self, cb: QComboBox) -> None:
        cb.setObjectName("AddressStructCombo")
        cb.setEditable(False)
        cb.setMinimumWidth(168)
        cb.setMinimumHeight(32)
        cb.setToolTip("Lista: click pe câmp, apoi pe săgeata din dreapta (▼).")

    def _attach_addr_combo_completer(self, cb: QComboBox | None) -> None:
        if cb is None:
            return
        m = cb.model()
        if m is None:
            return
        c = QCompleter(m, cb)
        c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        c.setFilterMode(Qt.MatchFlag.MatchContains)
        cb.setCompleter(c)

    def _create_structured_address_widgets(self) -> None:
        self._addr_county = QComboBox()
        self._addr_county.addItems(sorted(self._addr_localities_catalog.keys(), key=lambda x: x.lower()))
        self._wire_addr_searchable_combo(self._addr_county, "▼ Județ — listă sau căutare…")
        self._attach_addr_combo_completer(self._addr_county)

        self._addr_locality = QComboBox()
        self._wire_addr_searchable_combo(self._addr_locality, "▼ Localitate — listă sau căutare…")

        self._addr_zone = QLineEdit()
        self._addr_zone.setPlaceholderText("Opțional")

        self._addr_street_type = QComboBox()
        self._addr_street_type.addItems(list(ADDRESS_STREET_TYPES))
        self._wire_addr_choice_combo(self._addr_street_type)

        self._addr_street_name = QComboBox()
        self._addr_street_name.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._wire_addr_searchable_combo(self._addr_street_name, "▼ Stradă — nomenclator sau text…")

        self._addr_number = QLineEdit()
        self._addr_number.setPlaceholderText("Nr.")

        self._addr_block = QLineEdit()
        self._addr_stair = QLineEdit()
        self._addr_floor = QLineEdit()
        self._addr_apartment = QLineEdit()
        for w, ph in (
            (self._addr_block, "Bloc"),
            (self._addr_stair, "Sc."),
            (self._addr_floor, "Et."),
            (self._addr_apartment, "Ap."),
        ):
            w.setPlaceholderText(ph)

        self._addr_intercom = QLineEdit()
        self._addr_extra = QLineEdit()
        self._addr_intercom.setPlaceholderText("Interfon")
        self._addr_extra.setPlaceholderText("Alte detalii")
        self._addr_catalog_status_label = QLabel("")
        self._addr_catalog_status_label.setObjectName("HintLabel")
        self._addr_catalog_status_label.setWordWrap(True)
        self._addr_catalog_import_btn = QPushButton("Importă acum (OSM)")
        self._addr_catalog_import_btn.setToolTip("Importă străzi pentru județ/localitate curente.")
        self._addr_catalog_import_btn.clicked.connect(self._import_current_locality_streets_from_osm)

        addr_full = QTextEdit()
        addr_full.setReadOnly(True)
        addr_full.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        addr_full.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        addr_full.setMaximumHeight(100)
        addr_full.setMinimumHeight(56)
        addr_full.setPlaceholderText("Text compus automat pentru câmpul «adresă» (DB)…")
        addr_full.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edits["address"] = addr_full

    def _connect_structured_address_signals_and_refresh(self) -> None:
        self._addr_county.currentTextChanged.connect(self._on_addr_county_changed)
        self._addr_locality.currentTextChanged.connect(self._on_addr_locality_changed)
        self._addr_street_type.currentTextChanged.connect(self._compose_structured_address_ui)
        self._addr_street_name.currentTextChanged.connect(self._on_addr_street_name_changed)
        for w in (
            self._addr_zone,
            self._addr_number,
            self._addr_block,
            self._addr_stair,
            self._addr_floor,
            self._addr_apartment,
            self._addr_intercom,
            self._addr_extra,
        ):
            w.textChanged.connect(self._compose_structured_address_ui)
        self._sync_addr_import_btn_state()
        self._refresh_addr_locality_options()
        self._refresh_addr_street_options()

    def _populate_structured_address_grid_rows(self, grid: QGridLayout, row: int, section_title: str) -> int:
        """Adresă structurată în același grid ca Prenume/CNP (etichetă stânga, câmp dreapta)."""
        self._null_address_widget_refs()
        self._addr_structured_widgets = True
        self._address_host = None
        self._address_embedded_in_grid = True
        self._create_structured_address_widgets()

        grid.addWidget(self._form_grid_label(section_title), row, 0)
        grid.addWidget(self._addr_county, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Localitate"), row, 0)
        grid.addWidget(self._addr_locality, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Zonă / cartier"), row, 0)
        grid.addWidget(self._addr_zone, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Tip stradă"), row, 0)
        grid.addWidget(self._addr_street_type, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Stradă"), row, 0)
        grid.addWidget(self._addr_street_name, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Nomenclator"), row, 0)
        status_row = QWidget()
        status_row_l = QHBoxLayout(status_row)
        status_row_l.setContentsMargins(0, 0, 0, 0)
        status_row_l.setSpacing(8)
        status_row_l.addWidget(self._addr_catalog_status_label, 1)
        status_row_l.addWidget(self._addr_catalog_import_btn, 0)
        grid.addWidget(status_row, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Număr"), row, 0)
        grid.addWidget(self._addr_number, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Bloc"), row, 0)
        grid.addWidget(self._addr_block, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Scară"), row, 0)
        grid.addWidget(self._addr_stair, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Etaj"), row, 0)
        grid.addWidget(self._addr_floor, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Apartament"), row, 0)
        grid.addWidget(self._addr_apartment, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Interfon"), row, 0)
        grid.addWidget(self._addr_intercom, row, 1)
        row += 1
        grid.addWidget(self._form_grid_label("Alte detalii"), row, 0)
        grid.addWidget(self._addr_extra, row, 1)
        row += 1
        lab_prev = self._form_grid_label("Adresă completă (salvat)")
        lab_prev.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(lab_prev, row, 0)
        grid.addWidget(self._edits["address"], row, 1)
        row += 1

        self._connect_structured_address_signals_and_refresh()
        return row

    def _null_address_widget_refs(self) -> None:
        self._edits.pop("address", None)
        self._addr_county = None
        self._addr_locality = None
        self._addr_zone = None
        self._addr_street_type = None
        self._addr_street_name = None
        self._addr_number = None
        self._addr_block = None
        self._addr_stair = None
        self._addr_floor = None
        self._addr_apartment = None
        self._addr_intercom = None
        self._addr_extra = None
        self._addr_catalog_status_label = None
        self._addr_catalog_import_btn = None

    def _update_addr_catalog_status(self, street_count: int) -> None:
        lbl = self._addr_catalog_status_label
        if lbl is None or self._addr_county is None or self._addr_locality is None:
            return
        county = self._addr_county.currentText().strip() or "—"
        locality = self._addr_locality.currentText().strip() or "—"
        last_updated = ""
        try:
            last_updated = str(
                self.db.street_catalog_last_updated_at(county=county, locality=locality) or ""
            ).strip()
        except Exception:
            last_updated = ""
        pretty_updated = last_updated
        try:
            if last_updated:
                pretty_updated = datetime.strptime(last_updated[:19], "%Y-%m-%d %H:%M:%S").strftime(
                    "%d.%m.%Y %H:%M"
                )
        except Exception:
            pretty_updated = last_updated
        suffix = f" Ultima actualizare: {pretty_updated}." if pretty_updated else ""
        if street_count <= 0:
            lbl.setText(
                f"Nu există străzi în nomenclator pentru {locality}, {county}. "
                "Puteți completa din Setări -> Adresă / nomenclator stradal."
                + suffix
            )
            if get_ui_theme() == "dark":
                lbl.setStyleSheet("color: #fbbf24;")
            else:
                lbl.setStyleSheet("color: #b45309;")
            self._sync_addr_import_btn_state()
            return
        lbl.setText(
            f"Nomenclator disponibil: {int(street_count)} străzi pentru {locality}, {county}."
            + suffix
        )
        if get_ui_theme() == "dark":
            lbl.setStyleSheet("color: #86efac;")
        else:
            lbl.setStyleSheet("color: #166534;")
        self._sync_addr_import_btn_state()

    def _sync_addr_import_btn_state(self) -> None:
        btn = self._addr_catalog_import_btn
        if btn is None:
            return
        county = (self._addr_county.currentText().strip() if self._addr_county is not None else "")
        locality = (self._addr_locality.currentText().strip() if self._addr_locality is not None else "")
        allowed = has_role(self.session.user, "admin")
        btn.setEnabled(bool(allowed and county and locality))
        if county and locality:
            btn.setToolTip(f"Importă străzi din OSM pentru {locality}, {county}.")
        else:
            btn.setToolTip("Selectați mai întâi județ și localitate pentru import OSM.")

    def _import_current_locality_streets_from_osm(self) -> None:
        if not has_role(self.session.user, "admin"):
            QMessageBox.warning(self, "Adresă", "Doar administratorul poate importa nomenclatorul.")
            return
        if self._addr_county is None or self._addr_locality is None:
            return
        county = self._addr_county.currentText().strip()
        locality = self._addr_locality.currentText().strip()
        if not county or not locality:
            QMessageBox.information(self, "Adresă", "Selectați mai întâi județ și localitate.")
            return
        btn = self._addr_catalog_import_btn
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("Import…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = fetch_street_catalog_for_locality_from_osm(
                county=county,
                locality=locality,
                timeout_seconds=30,
                max_rows=4000,
            )
            inserted = int(self.db.merge_street_catalog_entries(rows))
            self._refresh_addr_street_options()
            QMessageBox.information(
                self,
                "Adresă",
                f"Import finalizat pentru {locality}, {county}.\nIntrări prelucrate: {len(rows)}\nInserate/actualizate: {inserted}",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Adresă", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("Importă acum (OSM)")

    def _build_address_into_host(self, structured: bool) -> None:
        if self._address_host is None:
            return
        self._null_address_widget_refs()
        self._clear_layout_of_widget(self._address_host)
        self._addr_structured_widgets = structured
        self._address_embedded_in_grid = False
        box = QVBoxLayout(self._address_host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        if not structured:
            e = QLineEdit()
            self._edits["address"] = e
            box.addWidget(e)
            return

        self._create_structured_address_widgets()
        hint = QLabel(
            "▼ Deschideți lista din dreapta sau tastați pentru căutare (mod compact; reporniți aplicația "
            "după schimbarea PF_ADDRESS_UI pentru alinierea în grid)."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        box.addWidget(hint)
        for w in (
            self._addr_county,
            self._addr_locality,
            self._addr_zone,
            self._addr_street_type,
            self._addr_street_name,
            self._addr_number,
            self._addr_block,
            self._addr_stair,
            self._addr_floor,
            self._addr_apartment,
            self._addr_intercom,
            self._addr_extra,
        ):
            box.addWidget(w)
        if self._addr_catalog_status_label is not None:
            status_row = QWidget()
            status_row_l = QHBoxLayout(status_row)
            status_row_l.setContentsMargins(0, 0, 0, 0)
            status_row_l.setSpacing(8)
            status_row_l.addWidget(self._addr_catalog_status_label, 1)
            if self._addr_catalog_import_btn is not None:
                status_row_l.addWidget(self._addr_catalog_import_btn, 0)
            box.addWidget(status_row)
        box.addWidget(self._edits["address"])
        self._connect_structured_address_signals_and_refresh()

    def _refresh_addr_locality_options(self) -> None:
        if self._addr_county is None or self._addr_locality is None:
            return
        county = self._addr_county.currentText().strip()
        self._addr_locality.blockSignals(True)
        self._addr_locality.clear()
        locs = list(self._addr_localities_catalog.get(county, []))
        try:
            extra = self.db.list_street_catalog_localities(county=county, limit=5000)
            locs.extend(str(x) for x in extra if x)
        except Exception:
            pass
        for loc in sorted(set(locs), key=lambda x: x.lower()):
            self._addr_locality.addItem(loc)
        self._addr_locality.blockSignals(False)
        self._attach_addr_combo_completer(self._addr_locality)

    def _refresh_addr_street_options(self) -> None:
        if self._addr_street_name is None or self._addr_county is None or self._addr_locality is None:
            return
        county = self._addr_county.currentText().strip()
        locality = self._addr_locality.currentText().strip()
        self._addr_street_name.blockSignals(True)
        self._addr_street_name.clear()
        self._addr_street_type_by_name.clear()
        try:
            rows = self.db.list_street_catalog_entries(county=county, locality=locality, limit=5000)
        except Exception:
            rows = []
        names: List[str] = []
        for r in rows:
            sn = str(r["street_name"] or "").strip()
            if not sn:
                continue
            lk = sn.lower()
            if lk not in self._addr_street_type_by_name:
                self._addr_street_type_by_name[lk] = canonical_street_type(str(r["street_type"] or "").strip())
            names.append(sn)
        for n in sorted(set(names), key=lambda x: x.lower()):
            self._addr_street_name.addItem(n)
        self._addr_street_name.blockSignals(False)
        self._attach_addr_combo_completer(self._addr_street_name)
        self._update_addr_catalog_status(len(set(names)))

    def _on_addr_county_changed(self, _t: str = "") -> None:
        if self._address_ui_syncing:
            return
        self._sync_addr_import_btn_state()
        self._refresh_addr_locality_options()
        self._refresh_addr_street_options()
        self._compose_structured_address_ui()

    def _on_addr_locality_changed(self, _t: str = "") -> None:
        if self._address_ui_syncing:
            return
        self._sync_addr_import_btn_state()
        self._refresh_addr_street_options()
        self._compose_structured_address_ui()

    def _on_addr_street_name_changed(self, _t: str = "") -> None:
        if self._address_ui_syncing:
            return
        if self._addr_street_name is None or self._addr_street_type is None:
            return
        name = self._addr_street_name.currentText().strip()
        if name:
            t = self._addr_street_type_by_name.get(name.lower())
            if t:
                idx = self._addr_street_type.findText(t, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self._addr_street_type.setCurrentIndex(idx)
        self._compose_structured_address_ui()

    def _compose_structured_address_ui(self) -> None:
        if not self._addr_structured_widgets or self._address_ui_syncing:
            return
        if (
            self._addr_county is None
            or self._addr_locality is None
            or self._addr_zone is None
            or self._addr_street_type is None
            or self._addr_street_name is None
        ):
            return
        county = self._addr_county.currentText().strip()
        locality = self._addr_locality.currentText().strip()
        details = compose_address_details_from_parts(
            street_type=self._addr_street_type.currentText().strip(),
            street_name=self._addr_street_name.currentText().strip(),
            number=(self._addr_number.text() if self._addr_number else "").strip(),
            block=(self._addr_block.text() if self._addr_block else "").strip(),
            stair=(self._addr_stair.text() if self._addr_stair else "").strip(),
            floor=(self._addr_floor.text() if self._addr_floor else "").strip(),
            apartment=(self._addr_apartment.text() if self._addr_apartment else "").strip(),
            intercom=(self._addr_intercom.text() if self._addr_intercom else "").strip(),
            extra=(self._addr_extra.text() if self._addr_extra else "").strip(),
        )
        zone = (self._addr_zone.text() if self._addr_zone else "").strip()
        if zone:
            details = f"zona: {zone}, {details}" if details else f"zona: {zone}"
        full = compose_structured_address(county, locality, details)
        self._address_edit_set_text(full)

    def _sync_structured_address_from_string(self, address_value: str) -> None:
        if not self._addr_structured_widgets:
            return
        if (
            self._addr_county is None
            or self._addr_locality is None
            or self._addr_zone is None
            or self._addr_street_type is None
            or self._addr_street_name is None
        ):
            return
        self._address_ui_syncing = True
        try:
            parsed = parse_structured_address(str(address_value or ""))
            county = str(parsed.get("county") or "").strip()
            locality = str(parsed.get("locality") or "").strip()
            if county:
                idx = self._addr_county.findText(county, Qt.MatchFlag.MatchFixedString)
                if idx < 0:
                    idx = self._addr_county.findText(county, Qt.MatchFlag.MatchContains)
                if idx >= 0:
                    self._addr_county.setCurrentIndex(idx)
            self._refresh_addr_locality_options()
            if locality:
                li = self._addr_locality.findText(locality, Qt.MatchFlag.MatchFixedString)
                if li < 0:
                    li = self._addr_locality.findText(locality, Qt.MatchFlag.MatchContains)
                if li >= 0:
                    self._addr_locality.setCurrentIndex(li)
            self._refresh_addr_street_options()
            details_raw = str(parsed.get("details") or "")
            details_zone = ""
            details_rest = details_raw
            zm = re.match(r"^\s*zona:\s*([^,]+)\s*(?:,\s*(.*))?$", details_raw, re.IGNORECASE)
            if zm:
                details_zone = (zm.group(1) or "").strip()
                details_rest = (zm.group(2) or "").strip()
            parts = parse_address_details_to_parts(details_rest)
            self._addr_zone.setText(details_zone)
            st = canonical_street_type(str(parts.get("street_type") or ""))
            if st:
                ti = self._addr_street_type.findText(st, Qt.MatchFlag.MatchFixedString)
                if ti >= 0:
                    self._addr_street_type.setCurrentIndex(ti)
            sn = str(parts.get("street_name") or "").strip()
            if sn:
                ni = self._addr_street_name.findText(sn, Qt.MatchFlag.MatchFixedString)
                if ni < 0:
                    self._addr_street_name.insertItem(0, sn)
                    ni = 0
                self._addr_street_name.setCurrentIndex(ni)
            if self._addr_number:
                self._addr_number.setText(str(parts.get("number") or ""))
            if self._addr_block:
                self._addr_block.setText(str(parts.get("block") or ""))
            if self._addr_stair:
                self._addr_stair.setText(str(parts.get("stair") or ""))
            if self._addr_floor:
                self._addr_floor.setText(str(parts.get("floor") or ""))
            if self._addr_apartment:
                self._addr_apartment.setText(str(parts.get("apartment") or ""))
            if self._addr_intercom:
                self._addr_intercom.setText(str(parts.get("intercom") or ""))
            if self._addr_extra:
                self._addr_extra.setText(str(parts.get("extra") or ""))
        finally:
            self._address_ui_syncing = False
        self._compose_structured_address_ui()

    def _unregister_theme_apply_hook(self) -> None:
        unregister_post_theme_apply_hook(self._on_theme_refresh_patient_form)

    def _on_theme_refresh_patient_form(self) -> None:
        self._on_cnp_field_text_changed()
        self._update_risk_card(self._collect_payload())
        self._sync_new_patient_dirty_indicator()

    def _connect_address_dirty_tracking(self) -> None:
        def _sched(_t: str = "") -> None:
            self._schedule_new_patient_dirty_check()

        waddr = self._edits.get("address")
        if waddr is not None:
            waddr.textChanged.connect(_sched)
        if not self._addr_structured_widgets:
            return
        for w in (
            self._addr_county,
            self._addr_locality,
            self._addr_street_type,
            self._addr_street_name,
        ):
            if w is not None:
                w.currentTextChanged.connect(_sched)
        for w in (
            self._addr_zone,
            self._addr_number,
            self._addr_block,
            self._addr_stair,
            self._addr_floor,
            self._addr_apartment,
            self._addr_intercom,
            self._addr_extra,
        ):
            if w is not None:
                w.textChanged.connect(_sched)

    def _wire_new_patient_dirty_tracking(self) -> None:
        def _sched(_t: str = "") -> None:
            self._schedule_new_patient_dirty_check()

        for k, w in self._edits.items():
            if k == "address":
                continue
            w.textChanged.connect(_sched)
        self._connect_address_dirty_tracking()
        for w in self._texts.values():
            w.textChanged.connect(_sched)

    def _schedule_new_patient_dirty_check(self) -> None:
        if self.session.patient_id() is not None:
            return
        sb = self._save_btn
        if sb is None or not sb.isEnabled():
            return
        self._dirty_debounce.start()

    def _sync_new_patient_dirty_indicator(self) -> None:
        lbl = self._new_patient_dirty_label
        if lbl is None:
            return
        if self.session.patient_id() is not None:
            lbl.clear()
            lbl.setStyleSheet("")
            return
        sb = self._save_btn
        if sb is None or not sb.isEnabled():
            lbl.clear()
            lbl.setStyleSheet("")
            return
        try:
            dirty = self._collect_payload() != self._new_patient_snapshot
        except Exception:
            dirty = False
        if dirty:
            lbl.setText("Modificări nesalvate (salvați cu Ctrl+S sau „Salvează”).")
            lbl.setStyleSheet(self._new_patient_dirty_style())
        else:
            lbl.clear()
            lbl.setStyleSheet("")

    def _new_patient_dirty_style(self) -> str:
        if get_ui_theme() == "dark":
            return "color: #fbbf24; font-weight: 600;"
        return "color: #b45309; font-weight: 600;"

    def _update_icd_catalog_banner(self) -> None:
        banner = self._icd_catalog_banner
        if banner is None:
            return
        cat = self._icd_catalog_cache or {}
        if icd10_catalog_is_configured(cat):
            banner.hide()
            return
        banner.setText(
            "Catalog ICD-10 indisponibil. Adăugați icd10.csv / icd10_ro.csv, generați db/icd10_am_ro.sqlite "
            "sau setați PACIENTI_ICD10_SQLITE. Vezi PACIENTI_DESKTOP.md și docs/CATALOG_ICD10_SOURCES.md."
        )
        banner.show()

    def _risk_warning_colors_active(self) -> str:
        if get_ui_theme() == "dark":
            return "color: #f87171; font-weight: 600;"
        return "color: #c62828; font-weight: 600;"

    def on_show(self) -> None:
        self._refresh_medication_duplicate_status()
        want = self._pf_address_ui_structured()
        if want != self._addr_structured_widgets and self._address_embedded_in_grid:
            mw = self.window()
            fn = getattr(mw, "rebuild_patient_form_page", None)
            if callable(fn):
                fn()
                return
            self.reload_from_session()
            self._ensure_icd10_catalog_loaded()
            return
        if self._address_host is not None and want != self._addr_structured_widgets:
            snap = self._collect_payload()
            self._build_address_into_host(want)
            self._connect_address_dirty_tracking()
            self._wire_patient_form_tab_order()
            if self.session.patient_id() is None:
                self._apply_payload(snap)
                self._on_cnp_field_text_changed()
                self._refresh_icd_primary_summary()
                self._refresh_icd_secondary_summary()
                sb = self._save_btn
                self._set_new_patient_mode(sb is not None and sb.isEnabled())
                self._maybe_restore_longtext_draft()
                self._sync_new_patient_dirty_indicator()
            else:
                self.reload_from_session()
        else:
            self.reload_from_session()
        self._ensure_icd10_catalog_loaded()

    def _new_patient(self) -> None:
        if not has_role(self.session.user, "admin", "medic", "receptie"):
            QMessageBox.warning(self, "Acces", "Rol insuficient.")
            return
        self.session.set_patient_id(None)
        self._apply_payload(empty_patient_payload())
        self._row_version = None
        self._new_patient_snapshot = self._collect_payload()
        self._hint.setText("Pacient nou (nesalvat).")
        self._set_new_patient_mode(True)
        self._maybe_restore_longtext_draft()
        self._sync_new_patient_dirty_indicator()

    def reload_from_session(self) -> None:
        self._refresh_medication_duplicate_status()
        pid = self.session.patient_id()
        if not pid:
            self._apply_payload(empty_patient_payload())
            self._row_version = None
            self._hint.setText('Niciun pacient selectat. Deschide „Pacienți” în meniu și dublu-click.')
            self._set_new_patient_mode(True)
            self._maybe_restore_longtext_draft()
            self._admission_rows = []
            self._admissions_table.setRowCount(0)
            self._admissions_hint.setText("Nu există pacient selectat.")
            self._medication_rows = []
            self._medication_table.setRowCount(0)
            self._medication_hint.setText("Nu există pacient selectat.")
            self._new_patient_snapshot = self._collect_payload()
            self._sync_new_patient_dirty_indicator()
            return
        row = self.db.get_patient(int(pid))
        if not row:
            self._hint.setText(f"Nu există pacient cu ID {pid}.")
            self._sync_new_patient_dirty_indicator()
            return
        d = dict(row)
        self._row_version = int(d.get("row_version") or 0)
        self._hint.setText(f"Pacient ID {pid} (versiune înregistrare: {self._row_version})")
        self._set_new_patient_mode(False)
        self._new_patient_snapshot = {}
        payload = row_to_payload(d)
        self._apply_payload(payload)
        self._refresh_admissions_for_current_patient()
        self._refresh_medication_entries()
        self._refresh_timeline_for_patient(int(pid))
        self._sync_new_patient_dirty_indicator()

    def _apply_payload(self, p: Dict[str, str]) -> None:
        icd_block = ("primary_diagnosis_icd10", "secondary_diagnoses_icd10")
        self._cnp_autofilled_birth_date = ""
        self._cnp_autofilled_gender = ""
        birth_edit = self._edits.get("birth_date")
        gender_edit = self._edits.get("gender")
        if birth_edit is not None:
            birth_edit.setToolTip("")
            birth_edit.setStyleSheet("")
        birth_hint = self._identity_auto_labels.get("birth_date")
        if birth_hint is not None:
            birth_hint.hide()
        if gender_edit is not None:
            gender_edit.setToolTip("")
            gender_edit.setStyleSheet("")
        gender_hint = self._identity_auto_labels.get("gender")
        if gender_hint is not None:
            gender_hint.hide()
        for k in icd_block:
            if k in self._edits:
                self._edits[k].blockSignals(True)
        try:
            for k, w in self._edits.items():
                raw = p.get(k, "")
                if k == "cnp":
                    raw = enforce_max_valid_cnp_prefix(str(raw or ""))
                if k == "address" and isinstance(w, QTextEdit):
                    w.setPlainText(str(raw or ""))
                else:
                    w.setText(str(raw or ""))
            if self._addr_structured_widgets:
                self._sync_structured_address_from_string(str(p.get("address") or ""))
            for k, w in self._texts.items():
                w.setPlainText(p.get(k, ""))
            self._update_summary_card(p)
            self._update_risk_card(p)
        finally:
            for k in icd_block:
                if k in self._edits:
                    self._edits[k].blockSignals(False)
        self._on_cnp_field_text_changed()
        self._refresh_icd_primary_summary()
        self._refresh_icd_secondary_summary()

    def _collect_payload(self) -> Dict[str, str]:
        p = empty_patient_payload()
        for k, w in self._edits.items():
            if k == "cnp":
                p[k] = enforce_max_valid_cnp_prefix(w.text().strip())
            elif k == "address" and isinstance(w, QTextEdit):
                p[k] = w.toPlainText().strip()
            else:
                p[k] = w.text().strip()
        prim_raw = self._edits["primary_diagnosis_icd10"].text().strip()
        p["primary_diagnosis_icd10"] = extract_icd10_code_from_text(prim_raw)
        sec_raw = self._edits["secondary_diagnoses_icd10"].text().strip()
        p["secondary_diagnoses_icd10"] = serialize_icd10_codes_csv(parse_icd10_codes_csv(sec_raw))
        for k, w in self._texts.items():
            p[k] = w.toPlainText().strip()
        return p

    def _set_new_patient_mode(self, is_new: bool) -> None:
        for w in self._edits.values():
            w.setReadOnly(not is_new)
        # Diagnosticele trebuie să poată fi actualizate și pe pacienți existenți.
        for key in ("primary_diagnosis_icd10", "secondary_diagnoses_icd10", "free_diagnosis_text"):
            w = self._edits.get(key)
            if w is not None:
                w.setReadOnly(False)
        if self._addr_structured_widgets:
            for w in (
                self._addr_county,
                self._addr_locality,
                self._addr_street_type,
                self._addr_street_name,
            ):
                if w is not None:
                    w.setEnabled(is_new)
            for w in (
                self._addr_zone,
                self._addr_number,
                self._addr_block,
                self._addr_stair,
                self._addr_floor,
                self._addr_apartment,
                self._addr_intercom,
                self._addr_extra,
            ):
                if w is not None:
                    w.setReadOnly(not is_new)
            addr = self._edits.get("address")
            if addr is not None:
                addr.setReadOnly(True)
        for w in self._texts.values():
            w.setReadOnly(not is_new)
        if self._save_btn is not None:
            can_save = has_role(self.session.user, "admin", "medic", "receptie")
            self._save_btn.setEnabled(can_save)
            self._save_btn.setToolTip("" if can_save else "Rol insuficient pentru salvare.")
        self._sync_new_patient_dirty_indicator()

    def _add_icd10_diagnosis_fields(self, grid: QGridLayout, row: int) -> int:
        prim = QLineEdit()
        prim.setPlaceholderText(
            "Căutare cod sau titlu (catalog: icd10.csv / icd10_ro.csv sau db/icd10_am_ro.sqlite)…"
        )
        self._edits["primary_diagnosis_icd10"] = prim
        sec = QLineEdit()
        sec.setPlaceholderText("Coduri separate prin virgulă; completare pe ultimul segment…")
        self._edits["secondary_diagnoses_icd10"] = sec

        self._icd_primary_summary = QLabel("")
        self._icd_primary_summary.setObjectName("IcdSummaryLabel")
        self._icd_primary_summary.setWordWrap(True)
        self._icd_secondary_summary = QLabel("")
        self._icd_secondary_summary.setObjectName("IcdSummaryLabel")
        self._icd_secondary_summary.setWordWrap(True)
        self._icd_loading_label = QLabel("")
        self._icd_loading_label.setObjectName("HintLabel")

        self._icd_primary_model = QStringListModel(self)
        prim_c = QCompleter(self._icd_primary_model, prim)
        prim_c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        prim_c.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        prim.setCompleter(prim_c)
        prim.textChanged.connect(self._refresh_icd_primary_summary)
        prim.textChanged.connect(lambda _t: self._icd_primary_debounce.start())

        self._icd_secondary_model = QStringListModel(self)
        sec_c = QCompleter(self._icd_secondary_model, sec)
        sec_c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        sec_c.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        sec.setCompleter(sec_c)
        sec.textChanged.connect(lambda _t: self._icd_secondary_debounce.start())
        sec.textChanged.connect(lambda _t: self._icd_secondary_summary_debounce.start())
        pop = sec_c.popup()
        if pop is not None:
            self._icd_secondary_popup_show_notifier = _IcdCompleterPopupShowNotifier(
                self._sync_icd_secondary_snapshot,
                self,
            )
            pop.installEventFilter(self._icd_secondary_popup_show_notifier)
        sec_c.activated[str].connect(self._on_secondary_icd_completer_activated)

        prim_block = QVBoxLayout()
        prim_block.setSpacing(4)
        prim_block.addWidget(prim)
        prim_block.addWidget(self._icd_primary_summary)
        sec_block = QVBoxLayout()
        sec_block.setSpacing(4)
        sec_block.addWidget(sec)
        sec_block.addWidget(self._icd_secondary_summary)

        grid.addWidget(QLabel("Diagnostic principal ICD-10"), row, 0)
        grid.addLayout(prim_block, row, 1)
        row += 1
        grid.addWidget(QLabel("Diagnostice secundare (CSV)"), row, 0)
        grid.addLayout(sec_block, row, 1)
        row += 1
        grid.addWidget(QLabel(""), row, 0)
        grid.addWidget(self._icd_loading_label, row, 1)
        row += 1
        return row

    def _cnp_feedback_colors(self) -> tuple[str, str, str]:
        if get_ui_theme() == "dark":
            return ("#4ade80", "#f87171", "#94a3b8")
        return ("#15803d", "#b91c1c", "#64748b")

    def _on_cnp_field_text_changed(self, _text: str = "") -> None:
        edit = self._edits.get("cnp")
        lbl = self._cnp_feedback_label
        if edit is None or lbl is None:
            return
        ok_c, err_c, pending_c = self._cnp_feedback_colors()
        raw = edit.text().strip()
        if not raw:
            self._clear_cnp_autofill_markers()
            lbl.clear()
            lbl.setStyleSheet("")
            return
        if validate_cnp_partial(edit.text()) == CNP_INPUT_ACCEPTABLE:
            d = derive_cnp_data(raw)
            bd = str(d.get("birth_date") or "")
            gender = str(d.get("gender") or "")
            birth_edit = self._edits.get("birth_date")
            gender_edit = self._edits.get("gender")
            current_birth = birth_edit.text().strip() if birth_edit is not None else ""
            should_autofill_birth = not current_birth or current_birth == self._cnp_autofilled_birth_date
            if birth_edit is not None and bd and should_autofill_birth and current_birth != bd:
                birth_edit.blockSignals(True)
                birth_edit.setText(bd)
                birth_edit.setToolTip("Completat automat din CNP.")
                birth_edit.setStyleSheet(self._cnp_autofill_style())
                birth_edit.blockSignals(False)
                birth_hint = self._identity_auto_labels.get("birth_date")
                if birth_hint is not None:
                    birth_hint.show()
            if should_autofill_birth and bd:
                self._cnp_autofilled_birth_date = bd
            current_gender = gender_edit.text().strip() if gender_edit is not None else ""
            should_autofill_gender = not current_gender or current_gender == self._cnp_autofilled_gender
            if gender_edit is not None and gender and should_autofill_gender and current_gender != gender:
                gender_edit.blockSignals(True)
                gender_edit.setText(gender)
                gender_edit.setToolTip("Completat automat din CNP.")
                gender_edit.setStyleSheet(self._cnp_autofill_style())
                gender_edit.blockSignals(False)
                gender_hint = self._identity_auto_labels.get("gender")
                if gender_hint is not None:
                    gender_hint.show()
            if should_autofill_gender and gender:
                self._cnp_autofilled_gender = gender
            county = str(d.get("county_label") or "")
            lbl.setText(f"Valid · {bd} · {county}")
            lbl.setStyleSheet(f"color: {ok_c};")
            self._update_summary_card(self._collect_payload())
            return
        if len(raw) == 13:
            self._clear_cnp_autofill_markers()
            d = derive_cnp_data(raw)
            err = str(d.get("error") or "CNP invalid")
            lbl.setText(err)
            lbl.setStyleSheet(f"color: {err_c};")
            return
        lbl.setText("Introducere în curs…")
        lbl.setStyleSheet(f"color: {pending_c};")

    def _on_identity_field_text_changed(self, field_key: str) -> None:
        edit = self._edits.get(field_key)
        if edit is None:
            return
        text_value = edit.text().strip()
        if field_key == "birth_date" and text_value != self._cnp_autofilled_birth_date:
            self._cnp_autofilled_birth_date = ""
            edit.setToolTip("")
            edit.setStyleSheet("")
            hint = self._identity_auto_labels.get("birth_date")
            if hint is not None:
                hint.hide()
        elif field_key == "gender" and text_value != self._cnp_autofilled_gender:
            self._cnp_autofilled_gender = ""
            edit.setToolTip("")
            edit.setStyleSheet("")
            hint = self._identity_auto_labels.get("gender")
            if hint is not None:
                hint.hide()
        # Dacă utilizatorul golește câmpul iar CNP-ul este valid, repopulăm automat.
        cnp_edit = self._edits.get("cnp")
        if text_value == "" and cnp_edit is not None and validate_cnp_partial(cnp_edit.text()) == CNP_INPUT_ACCEPTABLE:
            self._on_cnp_field_text_changed()

    def _cnp_autofill_style(self) -> str:
        if get_ui_theme() == "dark":
            return "background-color: rgba(74, 222, 128, 0.22);"
        return "background-color: rgba(34, 197, 94, 0.12);"

    def _clear_cnp_autofill_markers(self) -> None:
        birth_edit = self._edits.get("birth_date")
        if birth_edit is not None and birth_edit.text().strip() == self._cnp_autofilled_birth_date:
            birth_edit.setToolTip("")
            birth_edit.setStyleSheet("")
            birth_hint = self._identity_auto_labels.get("birth_date")
            if birth_hint is not None:
                birth_hint.hide()
            self._cnp_autofilled_birth_date = ""
        gender_edit = self._edits.get("gender")
        if gender_edit is not None and gender_edit.text().strip() == self._cnp_autofilled_gender:
            gender_edit.setToolTip("")
            gender_edit.setStyleSheet("")
            gender_hint = self._identity_auto_labels.get("gender")
            if gender_hint is not None:
                gender_hint.hide()
            self._cnp_autofilled_gender = ""

    def _on_icd_loading_show_timeout(self) -> None:
        if self._icd_search_busy > 0 and self._icd_loading_label is not None:
            self._icd_loading_label.setText("Caută în catalog…")

    def _begin_icd_catalog_search(self) -> None:
        self._icd_search_busy += 1
        if self._icd_search_busy == 1:
            self._icd_loading_show_timer.start()

    def _end_icd_catalog_search(self) -> None:
        self._icd_search_busy = max(0, self._icd_search_busy - 1)
        if self._icd_search_busy == 0:
            self._icd_loading_show_timer.stop()
            if self._icd_loading_label is not None:
                self._icd_loading_label.clear()

    def _icd_title_for_code(self, code: str, cat: Dict[str, str]) -> str:
        c = normalize_icd10_code(code)
        if not c:
            return ""
        return (cat.get(c) or cat.get(c.upper()) or "").strip()

    def _refresh_icd_primary_summary(self) -> None:
        lbl = self._icd_primary_summary
        if lbl is None:
            return
        w = self._edits.get("primary_diagnosis_icd10")
        if w is None:
            return
        self._ensure_icd10_catalog_loaded()
        code = extract_icd10_code_from_text(w.text())
        if not code:
            lbl.clear()
            return
        cat = self._icd_catalog_cache or {}
        if not icd10_catalog_is_configured(cat):
            lbl.setText(f"Cod extras: {code}")
            return
        title = self._icd_title_for_code(code, cat)
        if not title:
            lbl.setText(f"{code} — (lipsește titlul în catalog)")
            return
        short = title if len(title) <= 80 else title[:77] + "…"
        lbl.setText(f"{code} — {short}")

    def _refresh_icd_secondary_summary(self) -> None:
        lbl = self._icd_secondary_summary
        if lbl is None:
            return
        w = self._edits.get("secondary_diagnoses_icd10")
        if w is None:
            return
        self._ensure_icd10_catalog_loaded()
        codes = parse_icd10_codes_csv(w.text())
        if not codes:
            lbl.clear()
            return
        cat = self._icd_catalog_cache or {}
        parts: List[str] = []
        for c in codes[:10]:
            if icd10_catalog_is_configured(cat):
                t = self._icd_title_for_code(c, cat)
                frag = f"{c}: {t}" if t else f"{c}: ?"
                if len(frag) > 48:
                    frag = frag[:45] + "…"
                parts.append(frag)
            else:
                parts.append(c)
        if len(codes) > 10:
            parts.append(f"+{len(codes) - 10} coduri")
        lbl.setText(" · ".join(parts))

    def _wire_patient_form_tab_order(self) -> None:
        keys = [
            "first_name",
            "last_name",
            "cnp",
            "phone",
            "email",
            "birth_date",
            "gender",
            "address",
            "occupation",
            "insurance_provider",
            "insurance_id",
            "emergency_contact_name",
            "emergency_contact_phone",
            "blood_type",
            "height_cm",
            "weight_kg",
        ]
        chain: List = []
        for k in keys:
            if k == "address" and self._addr_structured_widgets:
                for w in (
                    self._addr_county,
                    self._addr_locality,
                    self._addr_zone,
                    self._addr_street_type,
                    self._addr_street_name,
                    self._addr_number,
                    self._addr_block,
                    self._addr_stair,
                    self._addr_floor,
                    self._addr_apartment,
                    self._addr_intercom,
                    self._addr_extra,
                    self._edits.get("address"),
                ):
                    if w is not None:
                        chain.append(w)
                continue
            e = self._edits.get(k)
            if e is not None:
                chain.append(e)
        for ek in ("primary_diagnosis_icd10", "secondary_diagnoses_icd10", "free_diagnosis_text"):
            e = self._edits.get(ek)
            if e is not None:
                chain.append(e)
        for k in self._TEXT_KEYS:
            t = self._texts.get(k)
            if t is not None:
                chain.append(t)
        for k in ("surgeries", "family_history", "lifestyle_notes"):
            t = self._texts.get(k)
            if t is not None:
                chain.append(t)
        for i in range(len(chain) - 1):
            self.setTabOrder(chain[i], chain[i + 1])

    def _focus_patient_field(self, field_key: str) -> None:
        if field_key == "address" and self._addr_structured_widgets and self._addr_county is not None:
            w = self._addr_county
        else:
            w = self._edits.get(field_key)
        if w is None:
            w = self._texts.get(field_key)
        if w is None:
            return
        w.setFocus(Qt.FocusReason.OtherFocusReason)
        scroll = self.findChild(QScrollArea, "PageScrollArea")
        if scroll is not None:
            scroll.ensureWidgetVisible(w, 24, 24)

    def _field_for_patient_policy_error(self, message: str) -> str | None:
        m = message.lower()
        if "cnp invalid" in m:
            return "cnp"
        if "diagnostic principal icd10" in m:
            return "primary_diagnosis_icd10"
        if "diagnostic secundar icd10" in m:
            return "secondary_diagnoses_icd10"
        if "principal nu poate exista" in m or "nu poate exista si in lista" in m:
            return "secondary_diagnoses_icd10"
        if "adres" in m or "strad" in m or "localitate" in m or "jude" in m or "nomenclator" in m:
            return "address"
        return None

    def _show_patient_save_validation_error(self, message: str) -> None:
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Warning)
        mb.setWindowTitle("Nu s-a putut salva")
        mb.setText("Verificați câmpurile marcate în formular.")
        mb.setInformativeText(message)
        mb.exec()
        field = self._field_for_patient_policy_error(message)
        if field:
            self._focus_patient_field(field)

    def _ensure_icd10_catalog_loaded(self) -> Dict[str, str]:
        if self._icd_catalog_cache is None:
            self._icd_catalog_cache = load_icd10_catalog()
            missing = (
                "Catalog ICD-10 indisponibil. Adăugați icd10.csv, icd10_ro.csv (UTF-8, code,title) "
                "sau generați db/icd10_am_ro.sqlite din PDF (scripts/import_icd10_am_pdf_to_csv.py). "
                "Setați PACIENTI_ICD10_LANG=ro pentru RO. Vezi PACIENTI_DESKTOP.md."
            )
            prim = self._edits.get("primary_diagnosis_icd10")
            sec = self._edits.get("secondary_diagnoses_icd10")
            if not icd10_catalog_is_configured(self._icd_catalog_cache or {}):
                if prim is not None:
                    prim.setToolTip(missing)
                if sec is not None:
                    sec.setToolTip(missing)
            else:
                tip = f"Completare din {icd10_catalog_origin_label()}."
                if prim is not None:
                    prim.setToolTip(tip)
                if sec is not None:
                    sec.setToolTip(tip)
        self._update_icd_catalog_banner()
        return self._icd_catalog_cache or {}

    def _sync_icd_secondary_snapshot(self) -> None:
        w = self._edits.get("secondary_diagnoses_icd10")
        if w is not None:
            self._icd_secondary_snapshot = w.text()

    def _on_icd_primary_debounce(self) -> None:
        if self._icd_primary_model is None:
            return
        self._begin_icd_catalog_search()
        try:
            cat = self._ensure_icd10_catalog_loaded()
            if not cat:
                self._icd_primary_model.setStringList([])
                return
            q = self._edits["primary_diagnosis_icd10"].text().strip()
            if len(q) < 1:
                self._icd_primary_model.setStringList([])
                return
            self._icd_primary_model.setStringList(search_icd10_options(cat, q, limit=120))
        finally:
            self._end_icd_catalog_search()

    def _on_icd_secondary_debounce(self) -> None:
        if self._icd_secondary_model is None:
            return
        w = self._edits["secondary_diagnoses_icd10"]
        full = w.text()
        self._icd_secondary_snapshot = full
        self._begin_icd_catalog_search()
        try:
            cat = self._ensure_icd10_catalog_loaded()
            if not cat:
                self._icd_secondary_model.setStringList([])
                return
            seg = icd10_secondary_field_last_segment_query(full)
            if len(seg.strip()) < 1:
                self._icd_secondary_model.setStringList([])
                return
            self._icd_secondary_model.setStringList(search_icd10_options(cat, seg, limit=120))
        finally:
            self._end_icd_catalog_search()

    def _on_secondary_icd_completer_activated(self, choice: str) -> None:
        w = self._edits["secondary_diagnoses_icd10"]
        merged = icd10_merge_secondary_choice(self._icd_secondary_snapshot, choice)
        w.blockSignals(True)
        w.setText(merged)
        w.blockSignals(False)
        w.setCursorPosition(len(merged))
        self._refresh_icd_secondary_summary()

    def _estimate_drg(self) -> None:
        p = self._collect_payload()
        primary = (p.get("primary_diagnosis_icd10") or "").strip()
        sec_raw = (p.get("secondary_diagnoses_icd10") or "").strip()
        secondaries = [x.strip() for x in sec_raw.replace(";", ",").split(",") if x.strip()]
        out = estimate_drg_icm(
            primary_code=primary,
            secondary_codes=secondaries,
            birth_date=(p.get("birth_date") or "").strip(),
            free_diagnosis_text=(p.get("free_diagnosis_text") or "").strip(),
        )
        lines = [
            f"OK: {out.get('ok')}",
            f"DRG: {out.get('drg_code')} — {out.get('drg_label')}",
            f"MDC: {out.get('mdc')}",
            f"ICM estimat: {out.get('icm_estimated')}",
            f"Severitate: {out.get('severity')}",
        ]
        notes = out.get("notes") or []
        if isinstance(notes, list) and notes:
            lines.append("Note: " + "; ".join(str(n) for n in notes[:12]))
        QMessageBox.information(self, "Estimare DRG/ICM", "\n".join(lines))

    def _delete_patient(self) -> None:
        if not has_role(self.session.user, "admin"):
            QMessageBox.warning(self, "Ștergere", "Doar administratorul poate șterge pacienți.")
            return
        pid = self.session.patient_id()
        if not pid:
            QMessageBox.information(self, "Ștergere", "Niciun pacient selectat.")
            return
        if (
            QMessageBox.question(
                self,
                "Confirmare",
                f"Sigur ștergeți pacientul ID {pid}? Operația este ireversibilă.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete_patient(int(pid))
        except Exception as exc:
            QMessageBox.critical(self, "Ștergere", str(exc))
            return
        try:
            uid = self.session.user.get("id")
            self.db.add_audit_log(int(uid) if uid else None, None, "delete_patient_qt", f"patient_id={pid}")
        except Exception:
            pass
        self.session.set_patient_id(None)
        self.reload_from_session()
        QMessageBox.information(self, "Ștergere", "Pacient șters.")

    def _save(self) -> None:
        if not has_role(self.session.user, "admin", "medic", "receptie"):
            QMessageBox.warning(self, "Acces", "Rol insuficient.")
            return
        payload = self._collect_payload()
        if not payload.get("first_name") or not payload.get("last_name"):
            QMessageBox.warning(self, "Validare", "Prenume și nume sunt obligatorii.")
            self._focus_patient_field(
                "first_name" if not (payload.get("first_name") or "").strip() else "last_name"
            )
            return
        sb = self._save_btn
        saving = sb is not None and sb.isEnabled()
        if saving:
            sb.setEnabled(False)
            sb.setText("Se salvează…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pid = self.session.patient_id()
            if pid is None:
                new_id = self.db.create_patient(payload)
                self.session.set_patient_id(new_id)
                self._clear_longtext_draft()
                self._new_patient_snapshot = {}
                self.reload_from_session()
                QMessageBox.information(self, "Fișă pacient", f"Pacient creat. ID {new_id}")
            else:
                self.db.update_patient(
                    int(pid),
                    payload,
                    expected_row_version=self._row_version,
                )
                row = self.db.get_patient(int(pid))
                if row:
                    self._row_version = int(dict(row).get("row_version") or 0)
                self.session.refresh_patient_display()
                self.reload_from_session()
                QMessageBox.information(self, "Fișă pacient", "Pacient actualizat.")
        except ValueError as ve:
            self._show_patient_save_validation_error(str(ve))
        except Exception as exc:
            self._show_patient_save_validation_error(str(exc))
        finally:
            if saving:
                QApplication.restoreOverrideCursor()
                if sb is not None:
                    sb.setText(self._save_btn_default_text)
                    if self.session.patient_id() is None:
                        sb.setEnabled(True)

    def can_navigate_away(self) -> bool:
        if self.session.patient_id() is not None:
            return True
        if not self._new_patient_snapshot:
            return True
        if self._collect_payload() == self._new_patient_snapshot:
            return True
        reply = QMessageBox.question(
            self,
            "Fișă pacient",
            "Există date nesalvate pentru pacient nou. Doriți să părăsiți pagina?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_shortcut_save(self) -> None:
        if self._save_btn is not None and self._save_btn.isEnabled():
            self._save()

    def _on_shortcut_new(self) -> None:
        if self._new_btn is not None and self._new_btn.isEnabled():
            self._new_patient()

    def _on_shortcut_cancel(self) -> None:
        if self.session.patient_id() is None and self._new_patient_snapshot:
            if self._collect_payload() != self._new_patient_snapshot:
                reply = QMessageBox.question(
                    self,
                    "Fișă pacient",
                    "Există date nesalvate. Resetați formularul pacient nou?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        self.reload_from_session()

    def _longtext_draft_key(self) -> str:
        uid = self.session.user.get("id")
        return page_draft_store.build_draft_key(
            self._PF_DRAFT_PREFIX,
            user_id=int(uid) if uid else None,
            scope="new_patient",
        )

    def _collect_longtext_draft(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key in (
            "medical_history",
            "allergies",
            "chronic_conditions",
            "current_medication",
            "surgeries",
            "family_history",
            "lifestyle_notes",
        ):
            t = self._texts.get(key)
            out[key] = t.toPlainText().strip() if t is not None else ""
        return out

    def _has_draft_payload(self, payload: Dict[str, str]) -> bool:
        return any((payload.get(k) or "").strip() for k in payload.keys())

    def _schedule_longtext_draft(self) -> None:
        if self._draft_is_loading:
            return
        if self.session.patient_id() is not None:
            return
        self._draft_timer.start()

    def _flush_longtext_draft(self) -> None:
        if self.session.patient_id() is not None:
            return
        payload = self._collect_longtext_draft()
        key = self._longtext_draft_key()
        if self._has_draft_payload(payload):
            try:
                page_draft_store.save_page_draft(self.db, key, payload)
            except Exception:
                pass
        else:
            try:
                page_draft_store.clear_page_draft(self.db, key)
            except Exception:
                pass

    def _clear_longtext_draft(self) -> None:
        try:
            page_draft_store.clear_page_draft(self.db, self._longtext_draft_key())
        except Exception:
            pass

    def _discard_longtext_draft(self) -> None:
        if self.session.patient_id() is not None:
            QMessageBox.information(
                self,
                "Draft",
                "Draftul de texte este folosit doar pentru modul pacient nou.",
            )
            return
        if QMessageBox.question(
            self,
            "Draft",
            "Ștergeți draftul local pentru textele lungi (pacient nou)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._clear_longtext_draft()
        QMessageBox.information(self, "Draft", "Draft șters.")

    def _maybe_restore_longtext_draft(self) -> None:
        if self._draft_restore_prompted or self.session.patient_id() is not None:
            return
        self._draft_restore_prompted = True
        key = self._longtext_draft_key()
        try:
            data = page_draft_store.load_page_draft(self.db, key)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        payload = {str(k): str(v or "") for k, v in data.items()}
        if not self._has_draft_payload(payload):
            return
        if QMessageBox.question(
            self,
            "Draft detectat",
            "Există un draft local pentru textele lungi (pacient nou). Doriți restaurarea?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._draft_is_loading = True
        try:
            for k, v in payload.items():
                txt = self._texts.get(k)
                if txt is not None and not txt.toPlainText().strip():
                    txt.setPlainText(v)
        finally:
            self._draft_is_loading = False

    def _refresh_admissions_for_current_patient(self) -> None:
        pid = int(self.session.patient_id() or 0)
        self._admissions_table.setRowCount(0)
        if pid <= 0:
            self._admission_rows = []
            self._admissions_hint.setText("Nu există pacient selectat.")
            return
        try:
            self._admission_rows = clinical_qt.list_admissions_rows(self.db, pid, limit=500)
            self._admissions_hint.setText(f"Internări găsite: {len(self._admission_rows)}")
            active_found = False
            for row in self._admission_rows:
                r = self._admissions_table.rowCount()
                self._admissions_table.insertRow(r)
                vals = [
                    str(row.get("id") or ""),
                    str(row.get("mrn") or ""),
                    str(row.get("admission_type") or ""),
                    str(row.get("triage_level") or ""),
                    str(row.get("department") or ""),
                    str(row.get("status") or ""),
                    str(row.get("admitted_at") or ""),
                    str(row.get("discharged_at") or ""),
                ]
                for c, v in enumerate(vals):
                    self._admissions_table.setItem(r, c, QTableWidgetItem(v))
                if str(row.get("status") or "").strip().lower() == "active":
                    active_found = True
                    for c in range(self._admissions_table.columnCount()):
                        item = self._admissions_table.item(r, c)
                        if item is not None:
                            font = item.font()
                            font.setBold(True)
                            item.setFont(font)
            self._update_summary_admission_badge()
        except Exception as exc:
            self._admission_rows = []
            self._admissions_hint.setText(f"Eroare internări: {exc}")

    def _add_medication_entry(self) -> None:
        if not has_role(self.session.user, "admin", "medic", "asistent"):
            QMessageBox.warning(self, "Medicație", "Rol insuficient.")
            return
        pid = int(self.session.patient_id() or 0)
        if pid <= 0:
            QMessageBox.warning(self, "Medicație", "Selectați un pacient.")
            return
        day = (self._med_day.text() or "").strip() or now_ts()[:10]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(self, "Medicație", "Data este invalidă. Format: YYYY-MM-DD")
            return
        text = (self._med_text.text() or "").strip()
        if not text:
            QMessageBox.warning(self, "Medicație", "Completați medicația.")
            return
        notes = (self._med_notes.text() or "").strip()
        uid = self.session.user.get("id")
        try:
            uid_i = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            uid_i = None
        try:
            self.db.add_patient_medication_entry(
                patient_id=pid,
                recorded_at=day,
                medication_text=text,
                notes=notes,
                user_id=uid_i,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Medicație", str(exc))
            return
        self._med_text.clear()
        self._med_notes.clear()
        self._refresh_medication_entries()

    def _filtered_medication_rows(self) -> list[dict]:
        date_from = (self._med_filter_from.text() or "").strip()
        date_to = (self._med_filter_to.text() or "").strip()
        query = (self._med_filter_q.text() or "").strip().lower()
        if date_from:
            datetime.strptime(date_from, "%Y-%m-%d")
        if date_to:
            datetime.strptime(date_to, "%Y-%m-%d")
        out: list[dict] = []
        for row in self._medication_rows:
            day = str(row.get("recorded_at") or "")
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            if query:
                hay = (
                    f"{str(row.get('medication_text') or '')} {str(row.get('notes') or '')}".strip().lower()
                )
                if query not in hay:
                    continue
            out.append(row)
        return out

    def _set_med_filter_today(self) -> None:
        today = now_ts()[:10]
        self._med_filter_from.setText(today)
        self._med_filter_to.setText(today)
        self._refresh_medication_entries()

    def _refresh_medication_duplicate_status(self) -> None:
        raw = str(self.db.get_setting(self._MED_DUP_KEY, "0") or "0").strip().lower()
        enabled = raw in {"1", "true", "yes", "on"}
        self._medication_dup_status.setText(
            f"Duplicate în aceeași zi: {'PERMISE' if enabled else 'BLOCATE'}"
        )
        self._medication_dup_status.setStyleSheet(
            "font-weight: 600; color: #2e7d32;" if enabled else "font-weight: 600; color: #c62828;"
        )

    def _reset_medication_filters(self) -> None:
        self._med_filter_from.clear()
        self._med_filter_to.clear()
        self._med_filter_q.clear()
        self._refresh_medication_entries()

    def _selected_medication_row(self) -> dict | None:
        row_idx = self._medication_table.currentRow()
        if row_idx < 0:
            return None
        date_from = (self._med_filter_from.text() or "").strip()
        date_to = (self._med_filter_to.text() or "").strip()
        query = (self._med_filter_q.text() or "").strip().lower()
        filtered: list[dict] = []
        for row in self._medication_rows:
            day = str(row.get("recorded_at") or "")
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            if query:
                hay = f"{str(row.get('medication_text') or '')} {str(row.get('notes') or '')}".strip().lower()
                if query not in hay:
                    continue
            filtered.append(row)
        if row_idx >= len(filtered):
            return None
        return filtered[row_idx]

    def _load_selected_medication_into_form(self) -> None:
        row = self._selected_medication_row()
        if not row:
            QMessageBox.information(self, "Medicație", "Selectați un rând din tabel.")
            return
        self._med_day.setText(str(row.get("recorded_at") or ""))
        self._med_text.setText(str(row.get("medication_text") or ""))
        self._med_notes.setText(str(row.get("notes") or ""))

    def _on_medication_dblclick(self, _row: int, _col: int) -> None:
        self._load_selected_medication_into_form()

    def _update_selected_medication_entry(self) -> None:
        if not has_role(self.session.user, "admin", "medic", "asistent"):
            QMessageBox.warning(self, "Medicație", "Rol insuficient.")
            return
        pid = int(self.session.patient_id() or 0)
        row = self._selected_medication_row()
        if pid <= 0 or not row:
            QMessageBox.warning(self, "Medicație", "Selectați un rând și un pacient.")
            return
        try:
            self.db.update_patient_medication_entry(
                entry_id=int(row.get("id") or 0),
                patient_id=pid,
                recorded_at=(self._med_day.text() or "").strip(),
                medication_text=(self._med_text.text() or "").strip(),
                notes=(self._med_notes.text() or "").strip(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Medicație", str(exc))
            return
        self._refresh_medication_entries()
        QMessageBox.information(self, "Medicație", "Înregistrare actualizată.")

    def _delete_selected_medication_entry(self) -> None:
        if not has_role(self.session.user, "admin", "medic"):
            QMessageBox.warning(self, "Medicație", "Rol insuficient.")
            return
        pid = int(self.session.patient_id() or 0)
        row = self._selected_medication_row()
        if pid <= 0 or not row:
            QMessageBox.warning(self, "Medicație", "Selectați un rând și un pacient.")
            return
        if (
            QMessageBox.question(
                self,
                "Confirmare",
                "Sigur ștergeți înregistrarea de medicație selectată?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete_patient_medication_entry(
                entry_id=int(row.get("id") or 0),
                patient_id=pid,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Medicație", str(exc))
            return
        self._refresh_medication_entries()
        QMessageBox.information(self, "Medicație", "Înregistrare ștearsă.")

    def _refresh_medication_entries(self) -> None:
        pid = int(self.session.patient_id() or 0)
        self._medication_table.setRowCount(0)
        if pid <= 0:
            self._medication_rows = []
            self._medication_hint.setText("Nu există pacient selectat.")
            return
        try:
            self._medication_rows = [dict(r) for r in self.db.list_patient_medication_entries(pid, limit=365)]
            filtered = self._filtered_medication_rows()
            self._medication_hint.setText(
                f"Înregistrări medicație: {len(self._medication_rows)} (afișate: {len(filtered)})"
            )
            for row in filtered:
                r = self._medication_table.rowCount()
                self._medication_table.insertRow(r)
                vals = [
                    str(row.get("recorded_at") or ""),
                    str(row.get("medication_text") or ""),
                    str(row.get("notes") or ""),
                    str(row.get("created_at") or ""),
                ]
                for c, v in enumerate(vals):
                    self._medication_table.setItem(r, c, QTableWidgetItem(v))
        except Exception as exc:
            self._medication_rows = []
            self._medication_hint.setText(f"Eroare medicație: {exc}")

    def _export_medication_csv(self) -> None:
        if not has_role(self.session.user, "admin", "medic", "asistent", "receptie"):
            QMessageBox.warning(self, "Medicație", "Rol insuficient.")
            return
        pid = int(self.session.patient_id() or 0)
        if pid <= 0:
            QMessageBox.warning(self, "Medicație", "Selectați un pacient.")
            return
        try:
            rows = self._filtered_medication_rows()
        except Exception as exc:
            QMessageBox.warning(self, "Medicație", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "Medicație", "Nu există rânduri de exportat pentru filtrul curent.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EXPORTS_DIR / f"patient_{pid}_medication_{stamp}.csv"
        csv_rows = [
            [
                str(r.get("recorded_at") or ""),
                str(r.get("medication_text") or ""),
                str(r.get("notes") or ""),
                str(r.get("created_at") or ""),
            ]
            for r in rows
        ]
        write_csv_rows(
            out_path,
            ["recorded_at", "medication_text", "notes", "created_at"],
            csv_rows,
        )
        QMessageBox.information(self, "Medicație", f"Export salvat:\n{out_path}")

    def _ensure_patient_for_navigation(self) -> int:
        pid = int(self.session.patient_id() or 0)
        if pid <= 0:
            QMessageBox.information(self, "Navigare", "Selectați un pacient înainte de a deschide modulul clinic.")
            return 0
        return pid

    def _open_export_patient_dialog(self) -> None:
        from pyside_desktop.dialogs.export_patient_dialog import run_export_patient_dialog

        run_export_patient_dialog(self, self.db, self.session)

    def _open_visits_module(self) -> None:
        if self._ensure_patient_for_navigation() <= 0:
            return
        self.session.navigate_requested.emit("Note clinice")

    def _open_new_patient_admission_wizard(self) -> None:
        from pyside_desktop.dialogs.new_patient_admission_wizard import run_new_patient_admission_wizard

        pid, aid = run_new_patient_admission_wizard(self, self.db, self.session)
        if not pid:
            return
        self.session.set_patient_id(int(pid))
        if aid:
            self.session.set_admission_focus_id(int(aid))
            self.session.navigate_requested.emit("Detaliu internare")
        else:
            self.reload_from_session()
            QMessageBox.information(
                self,
                "Wizard",
                "Pacientul a fost creat. Deschideți pagina Internări pentru o internare nouă, dacă e nevoie.",
            )

    def _open_create_admission(self) -> None:
        if self._ensure_patient_for_navigation() <= 0:
            return
        self.session.navigate_requested.emit("Internări")

    def _open_orders_module(self) -> None:
        if self._ensure_patient_for_navigation() <= 0:
            return
        self.session.navigate_requested.emit("Ordine")

    def _open_vitals_module(self) -> None:
        if self._ensure_patient_for_navigation() <= 0:
            return
        self.session.navigate_requested.emit("Vitale")

    def _update_summary_card(self, payload: Dict[str, str]) -> None:
        first = (payload.get("first_name") or "").strip()
        last = (payload.get("last_name") or "").strip()
        full_name = (last + " " + first).strip() or "—"
        pid = self.session.patient_id()
        cnp = (payload.get("cnp") or "").strip()
        masked_cnp = "—"
        if len(cnp) == 13:
            masked_cnp = f"{cnp[:3]}******{cnp[-4:]}"
        gender = (payload.get("gender") or "").strip() or "—"
        birth = (payload.get("birth_date") or "").strip()
        age_str = "—"
        if birth:
            try:
                bd = date.fromisoformat(birth)
                today = date.today()
                age = today.year - bd.year - (
                    1 if (today.month, today.day) < (bd.month, bd.day) else 0
                )
                age_str = f"{age} ani"
            except Exception:
                age_str = "invalid"
        self._summary_label.setText(
            f"{full_name} (ID {pid or '—'}) — vârstă: {age_str}, sex: {gender}, CNP: {masked_cnp}"
        )
        primary = (payload.get("primary_diagnosis_icd10") or "").strip()
        secondary_raw = (payload.get("secondary_diagnoses_icd10") or "").strip()
        secondaries = [s.strip() for s in secondary_raw.replace(";", ",").split(",") if s.strip()]
        sec_display = ", ".join(secondaries[:2])
        diag_parts = []
        if primary:
            diag_parts.append(f"Principal: {primary}")
        if sec_display:
            diag_parts.append(f"Secundare: {sec_display}")
        diag_text = " | ".join(diag_parts) if diag_parts else "Fără diagnostic ICD-10 setat."
        self._summary_diag_label.setText(diag_text)

    def _update_risk_card(self, payload: Dict[str, str]) -> None:
        allergies = (payload.get("allergies") or "").strip()
        chronic = (payload.get("chronic_conditions") or "").strip()
        surgeries = (payload.get("surgeries") or "").strip()
        fam = (payload.get("family_history") or "").strip()
        lines: List[str] = []
        if allergies:
            lines.append(f"Alergii: {allergies}")
        if chronic:
            lines.append(f"Afecțiuni cronice: {chronic}")
        if surgeries:
            lines.append(f"Intervenții: {surgeries}")
        if fam:
            lines.append(f"Istoric familial: {fam}")
        self._risk_summary_label.setText("\n".join(lines) if lines else "Nicio informație de risc completată.")
        if allergies or chronic:
            self._risk_warning_label.setText("AVERTISMENT RISC: verificați alergiile și afecțiunile cronice.")
            self._risk_warning_label.setStyleSheet(self._risk_warning_colors_active())
        else:
            self._risk_warning_label.setText("")
            self._risk_warning_label.setStyleSheet("")

    def _update_summary_admission_badge(self) -> None:
        active = next(
            (row for row in self._admission_rows if str(row.get("status") or "").strip().lower() == "active"),
            None,
        )
        if not active:
            self._summary_admission_label.setText("Internare activă: niciuna.")
            return
        dept = str(active.get("department") or "")
        ward = str(active.get("ward") or "")
        bed = str(active.get("bed") or "")
        adm_id = int(active.get("id") or 0)
        self._summary_admission_label.setText(
            f"Internare activă: {dept or '—'} / {ward or ''} {bed or ''} (ID={adm_id})"
        )

    def _refresh_timeline_for_patient(self, patient_id: int) -> None:
        self._timeline_rows = self._load_recent_events(int(patient_id), limit=self._timeline_limit_value())
        if not hasattr(self, "_timeline_table"):
            # Creăm tabelul o singură dată și îl adăugăm la layout-ul principal, deasupra cardului Acțiuni.
            self._timeline_table = make_table(["Data/ora", "Tip", "Detalii"])
            self._timeline_table.setMinimumHeight(180)
            self._timeline_table.setSortingEnabled(True)
            timeline_card = SectionCard("Evenimente recente")
            tl_bar1 = QHBoxLayout()
            tl_bar1.addWidget(QLabel("Filtru:"))
            self._timeline_filter = QComboBox()
            self._timeline_filter.addItems(["Toate", "Vizite", "Ordine", "Vitale", "Medicație"])
            self._timeline_filter.installEventFilter(self)
            self._timeline_filter.currentTextChanged.connect(
                lambda _v: self._on_timeline_filter_changed()
            )
            tl_bar1.addWidget(self._timeline_filter)
            tl_bar1.addWidget(QLabel("Limită:"))
            self._timeline_limit = QComboBox()
            self._timeline_limit.addItems(["30", "50", "100"])
            self._timeline_limit.setCurrentText("30")
            self._timeline_limit.installEventFilter(self)
            self._timeline_limit.currentTextChanged.connect(
                lambda _v: self._on_timeline_limit_changed()
            )
            tl_bar1.addWidget(self._timeline_limit)
            tl_clear_btn = self._make_icon_button(
                "Reset",
                QStyle.StandardPixmap.SP_DialogResetButton,
            )
            tl_clear_btn.clicked.connect(self._reset_timeline_filters)
            tl_bar1.addWidget(tl_clear_btn)
            tl_bar1.addStretch()
            timeline_card.add_layout(tl_bar1)
            tl_bar2 = QHBoxLayout()
            tl_bar2.addWidget(QLabel("Căutare:"))
            self._timeline_search = QLineEdit()
            self._timeline_search.setPlaceholderText("caută în tip/detalii…")
            self._timeline_search.textChanged.connect(
                lambda _v: self._on_timeline_search_changed()
            )
            tl_bar2.addWidget(self._timeline_search, 1)
            timeline_card.add_layout(tl_bar2)
            timeline_card.add_widget(self._timeline_table, 1)
            self._load_timeline_preferences()
            # Inserăm în layout-ul scrollabil al conținutului, înainte de cardul Acțiuni.
            if isinstance(self._content_layout, QVBoxLayout):
                idx = max(0, self._content_layout.count() - 1)
                self._content_layout.insertWidget(idx, timeline_card)
        table = self._timeline_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        filtered_rows = self._filtered_timeline_rows(self._timeline_rows)
        for row in filtered_rows[: self._timeline_limit_value()]:
            r = table.rowCount()
            table.insertRow(r)
            when = str(row.get("when") or "")
            etype = str(row.get("kind") or "")
            summary = str(row.get("summary") or "")[:100]
            vals = [when, etype, summary]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(v))
        table.setSortingEnabled(True)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj in {self._timeline_filter, self._timeline_limit} and event.type() == QEvent.Type.Wheel:
            # Evită schimbarea accidentală la scroll; selecția rămâne doar la click.
            return True
        return super().eventFilter(obj, event)

    def _load_recent_events(self, patient_id: int, limit: int = 60) -> List[dict]:
        pid = int(patient_id or 0)
        if pid <= 0:
            return []
        out: List[dict] = []
        try:
            for row in self.db.list_visits(pid, limit=50):
                d = dict(row)
                out.append(
                    {
                        "when": str(d.get("visit_date") or ""),
                        "kind": "Vizită",
                        "summary": str(d.get("reason") or d.get("diagnosis") or "Consultație"),
                    }
                )
        except Exception:
            pass
        try:
            for row in self.db.list_orders(pid, limit=50):
                d = dict(row)
                out.append(
                    {
                        "when": str(d.get("ordered_at") or ""),
                        "kind": "Ordin",
                        "summary": f"{str(d.get('order_type') or '')}: {str(d.get('order_text') or '')}".strip(": "),
                    }
                )
        except Exception:
            pass
        try:
            for row in self.db.list_vitals(pid, limit=50):
                d = dict(row)
                out.append(
                    {
                        "when": str(d.get("recorded_at") or ""),
                        "kind": "Vitale",
                        "summary": (
                            f"TA {str(d.get('systolic_bp') or '')}/{str(d.get('diastolic_bp') or '')}, "
                            f"Puls {str(d.get('pulse') or '')}, SpO2 {str(d.get('spo2') or '')}"
                        ),
                    }
                )
        except Exception:
            pass
        try:
            for row in self.db.list_patient_medication_entries(pid, limit=50):
                d = dict(row)
                out.append(
                    {
                        "when": str(d.get("recorded_at") or ""),
                        "kind": "Medicație",
                        "summary": str(d.get("medication_text") or ""),
                    }
                )
        except Exception:
            pass
        out.sort(key=lambda x: str(x.get("when") or ""), reverse=True)
        return out[: max(1, int(limit))]

    def _filtered_timeline_rows(self, rows: List[dict]) -> List[dict]:
        out = list(rows)
        if self._timeline_filter is None:
            selected = ""
        else:
            selected = (self._timeline_filter.currentText() or "").strip().lower()
        if selected and selected != "toate":
            mapping = {
                "vizite": "vizită",
                "ordine": "ordin",
                "vitale": "vitale",
                "medicație": "medicație",
            }
            target = mapping.get(selected, "")
            if target:
                out = [row for row in out if str(row.get("kind") or "").strip().lower() == target]
        query = (self._timeline_search.text() or "").strip().lower() if self._timeline_search is not None else ""
        if query:
            out = [
                row
                for row in out
                if query in f"{str(row.get('kind') or '')} {str(row.get('summary') or '')}".lower()
            ]
        return out

    def _reset_timeline_filters(self) -> None:
        if self._timeline_filter is not None:
            self._timeline_filter.setCurrentText("Toate")
        if self._timeline_search is not None:
            self._timeline_search.clear()
        if self._timeline_limit is not None:
            self._timeline_limit.setCurrentText("30")
        self._save_timeline_preferences()
        self._refresh_timeline_for_patient(int(self.session.patient_id() or 0))

    def _timeline_limit_value(self) -> int:
        if self._timeline_limit is None:
            return 30
        raw = (self._timeline_limit.currentText() or "").strip()
        try:
            return max(10, int(raw))
        except Exception:
            return 30

    def _on_timeline_filter_changed(self) -> None:
        self._save_timeline_preferences()
        self._refresh_timeline_for_patient(int(self.session.patient_id() or 0))

    def _on_timeline_limit_changed(self) -> None:
        self._save_timeline_preferences()
        self._refresh_timeline_for_patient(int(self.session.patient_id() or 0))

    def _on_timeline_search_changed(self) -> None:
        self._timeline_search_debounce.start()

    def _on_timeline_search_debounced(self) -> None:
        self._save_timeline_preferences()
        self._refresh_timeline_for_patient(int(self.session.patient_id() or 0))

    def _load_timeline_preferences(self) -> None:
        if self._timeline_filter is None or self._timeline_limit is None or self._timeline_search is None:
            return
        try:
            filter_value = str(self.db.get_setting(self._TL_FILTER_KEY, "Toate") or "Toate").strip()
            limit_value = str(self.db.get_setting(self._TL_LIMIT_KEY, "30") or "30").strip()
            search_value = str(self.db.get_setting(self._TL_SEARCH_KEY, "") or "")
        except Exception:
            return
        self._timeline_filter.blockSignals(True)
        self._timeline_limit.blockSignals(True)
        self._timeline_search.blockSignals(True)
        try:
            if filter_value in {"Toate", "Vizite", "Ordine", "Vitale", "Medicație"}:
                self._timeline_filter.setCurrentText(filter_value)
            else:
                self._timeline_filter.setCurrentText("Toate")
            if limit_value in {"30", "50", "100"}:
                self._timeline_limit.setCurrentText(limit_value)
            else:
                self._timeline_limit.setCurrentText("30")
            self._timeline_search.setText(search_value)
        finally:
            self._timeline_filter.blockSignals(False)
            self._timeline_limit.blockSignals(False)
            self._timeline_search.blockSignals(False)

    def _save_timeline_preferences(self) -> None:
        if self._timeline_filter is None or self._timeline_limit is None or self._timeline_search is None:
            return
        try:
            self.db.set_settings(
                {
                    self._TL_FILTER_KEY: str(self._timeline_filter.currentText() or "Toate"),
                    self._TL_LIMIT_KEY: str(self._timeline_limit.currentText() or "30"),
                    self._TL_SEARCH_KEY: str(self._timeline_search.text() or ""),
                }
            )
        except Exception:
            pass

    def _open_case_checklist(self) -> None:
        pid = int(self.session.patient_id() or 0)
        if pid <= 0:
            QMessageBox.information(self, "Checklist caz", "Selectați un pacient.")
            return
        active = next(
            (row for row in self._admission_rows if str(row.get("status") or "").strip().lower() == "active"),
            None,
        )
        if active:
            self.session.set_admission_focus_id(int(active.get("id") or 0))
        self.session.navigate_requested.emit("Internări")

    def _open_selected_admission(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._admission_rows):
            return
        pid = int(self.session.patient_id() or 0)
        if pid <= 0:
            return
        adm = self._admission_rows[row].get("id")
        self.session.set_patient_id(pid)
        self.session.set_admission_focus_id(int(adm) if adm is not None else None)
        self.session.navigate_requested.emit("Detaliu internare")
