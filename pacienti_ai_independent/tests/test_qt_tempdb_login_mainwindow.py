"""
Teste Qt cu SQLite temporar: login programatic + MainWindow (fără exec UI).

Necesită PySide6. În CI (variabila CI setată) se folosește QT_QPA_PLATFORM=offscreen dacă e suportat.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyside_desktop.nav_constants import EXPECTED_ADMIN_NAV_LABELS
from pyside_desktop.shared_qss import apply_application_stylesheet, apply_theme_palette
from qt_test_seed import SEED_PASSWORDS, fixed_seed_passwords
from pyside_desktop.services.patient_store import empty_patient_payload

try:
    from PySide6.QtWidgets import QApplication

    _HAS_QT = True
except ImportError:
    QApplication = None  # type: ignore[misc, assignment]
    _HAS_QT = False

@unittest.skipUnless(_HAS_QT, "PySide6 nu este instalat")
class QtTempDbLoginMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv("CI"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication(sys.argv)
        apply_application_stylesheet(cls._app, "light", "comfort")
        apply_theme_palette(cls._app, "light")

    def _make_db(self, db_path: Path) -> object:
        from db.database import Database

        return Database(db_path)

    @staticmethod
    def _make_cnp(s: int, yy: int, mm: int, dd: int, county: int, nnn: int) -> str:
        from db.cnp_utils import cnp_control_digit

        first12 = f"{s}{yy:02d}{mm:02d}{dd:02d}{county:02d}{nnn:03d}"
        return first12 + str(cnp_control_digit(first12))

    def test_login_dialog_success(self) -> None:
        from pyside_desktop.login_dialog import PysideLoginDialog

        with fixed_seed_passwords() as admin_pw:
            # Windows: SQLite poate ține fișierul deschis până la GC; ignore_cleanup_errors evită teardown strict.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "t.sqlite"
                db = self._make_db(db_path)
                dlg = PysideLoginDialog(db, hospital_name="Spital Test")
                dlg._user_edit.setText("admin")
                dlg._pass_edit.setText("wrong")
                dlg._on_login()
                self.assertIsNone(dlg.user)

                dlg._pass_edit.setText(admin_pw)
                dlg._on_login()
                self.assertIsNotNone(dlg.user)
                assert dlg.user is not None
                self.assertEqual(str(dlg.user.get("username", "")).lower(), "admin")
                self.assertEqual(dlg.user.get("role"), "admin")
                dlg.deleteLater()
                del dlg
                del db
                self._app.processEvents()

    def test_main_window_builds_with_real_db(self) -> None:
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords() as admin_pw:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "mw.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", admin_pw)
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                win = MainWindow(db=db, user=user, hospital_name="Unit Test")
                try:
                    self.assertGreater(len(win._stack_pages), 0)
                    self.assertIsNotNone(win.session)
                    self.assertFalse(win.session.enterprise_read_ready())
                    self.assertEqual(win.windowTitle(), "Unit Test – Pacienți AI (Qt)")
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_main_window_grab_after_show_has_pixels(self) -> None:
        """Randare fereastră completă offscreen (nu doar QLabel izolat)."""
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords() as admin_pw:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "grab.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", admin_pw)
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                win = MainWindow(db=db, user=user, hospital_name="Grab Test")
                try:
                    win.resize(960, 720)
                    win.show()
                    self._app.processEvents()
                    pix = win.grab()
                    self.assertFalse(pix.isNull(), msg="grab MainWindow")
                    img = pix.toImage()
                    self.assertFalse(img.isNull())
                    self.assertGreaterEqual(img.width(), 100)
                    self.assertGreaterEqual(img.height(), 100)
                    found_opaque = False
                    for y in (24, 80, 160):
                        for x in (24, 120, 240):
                            if y < img.height() and x < img.width():
                                if img.pixelColor(x, y).alpha() > 0:
                                    found_opaque = True
                                    break
                        if found_opaque:
                            break
                    self.assertTrue(
                        found_opaque,
                        msg="MainWindow ar trebui să aibă pixeli opaci după show() offscreen",
                    )
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_main_window_navigate_all_nav_rows(self) -> None:
        """Each sidebar row: stack index matches nav; on_show runs without error."""
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords() as admin_pw:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "nav.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", admin_pw)
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                win = MainWindow(db=db, user=user, hospital_name="Nav Test")
                try:
                    n = win._nav.count()
                    self.assertGreater(n, 0)
                    self.assertEqual(n, len(win._stack_pages))
                    labels: list[str] = []
                    for i in range(n):
                        it = win._nav.item(i)
                        labels.append(it.text() if it else "?")
                        win._nav.setCurrentRow(i)
                        self._app.processEvents()
                        self.assertEqual(
                            win._stack.currentIndex(),
                            i,
                            msg=f"nav i={i} label={labels[i]!r}",
                        )
                    # admin vede toate paginile definite în MainWindow (inclusiv Setări, Utilizatori)
                    self.assertIn("Tablou de bord", labels)
                    self.assertIn("Setări", labels)
                    self.assertEqual(frozenset(labels), EXPECTED_ADMIN_NAV_LABELS)
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_main_window_medic_role_has_audit_not_admin_only_pages(self) -> None:
        """Medic: Audit visible; Utilizatori / Setări hidden; walk all nav rows."""
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "med.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("medic", SEED_PASSWORDS["medic"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                self.assertEqual(user["role"], "medic")
                win = MainWindow(db=db, user=user, hospital_name="Medic RBAC")
                try:
                    n = win._nav.count()
                    labels = [win._nav.item(i).text() if win._nav.item(i) else "?" for i in range(n)]
                    self.assertIn("Audit", labels)
                    self.assertNotIn("Utilizatori", labels)
                    self.assertNotIn("Setări", labels)
                    self.assertIn("Tablou de bord", labels)
                    for i in range(n):
                        win._nav.setCurrentRow(i)
                        self._app.processEvents()
                        self.assertEqual(win._stack.currentIndex(), i)
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_main_window_asistent_role_excludes_stats_partners_audit(self) -> None:
        """Asistent: Istoric 360 yes; Statistici / Parteneri / Audit / admin pages no."""
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "asist.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("asistent", SEED_PASSWORDS["asistent"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                self.assertEqual(user["role"], "asistent")
                win = MainWindow(db=db, user=user, hospital_name="Asistent RBAC")
                try:
                    n = win._nav.count()
                    labels = [win._nav.item(i).text() if win._nav.item(i) else "?" for i in range(n)]
                    self.assertIn("Istoric 360", labels)
                    self.assertNotIn("Statistici", labels)
                    self.assertNotIn("Parteneri", labels)
                    self.assertNotIn("Audit", labels)
                    self.assertNotIn("Utilizatori", labels)
                    self.assertNotIn("Setări", labels)
                    self.assertIn("Tablou de bord", labels)
                    self.assertIn("Pacienți", labels)
                    for i in range(n):
                        win._nav.setCurrentRow(i)
                        self._app.processEvents()
                        self.assertEqual(win._stack.currentIndex(), i)
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_main_window_reception_role_excludes_admin_only_pages(self) -> None:
        """Receptie: Statistici / Parteneri / Istoric 360 yes; no Audit / Utilizatori / Setări."""
        from pyside_desktop.main_window import MainWindow

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "rec.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("receptie", SEED_PASSWORDS["receptie"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                self.assertEqual(user["role"], "receptie")
                win = MainWindow(db=db, user=user, hospital_name="Receptie RBAC")
                try:
                    n = win._nav.count()
                    self.assertGreater(n, 0)
                    self.assertEqual(n, len(win._stack_pages))
                    labels: list[str] = []
                    for i in range(n):
                        it = win._nav.item(i)
                        labels.append(it.text() if it else "?")
                    self.assertNotIn("Audit", labels)
                    self.assertNotIn("Utilizatori", labels)
                    self.assertNotIn("Setări", labels)
                    self.assertIn("Tablou de bord", labels)
                    self.assertIn("Pacienți", labels)
                    self.assertIn("Statistici", labels)
                    self.assertIn("Parteneri", labels)
                    self.assertIn("Istoric 360", labels)
                    for i in range(n):
                        win._nav.setCurrentRow(i)
                        self._app.processEvents()
                        self.assertEqual(win._stack.currentIndex(), i)
                finally:
                    win._alert_timer.stop()
                    win.close()
                    win.deleteLater()
                    self._app.processEvents()
                    del win
                    del db
                    self._app.processEvents()

    def test_nav_guard_pages_expose_can_navigate_away(self) -> None:
        """Smoke: pagini cu modificări nesalvate trebuie să expună hook-ul de navigare."""
        from pyside_desktop.pages.admission_detail_page import AdmissionDetailPage
        from pyside_desktop.pages.patient_form_page import PatientFormPage
        from pyside_desktop.session import AppSession

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "nav_hook.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", SEED_PASSWORDS["admin"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                session = AppSession(user)
                for page in (PatientFormPage(db, session), AdmissionDetailPage(db, session)):
                    fn = getattr(page, "can_navigate_away", None)
                    self.assertTrue(callable(fn))
                    self.assertIsInstance(fn(), bool)
                del page
                del db
                self._app.processEvents()

    def test_patient_form_cnp_autofill_marks_and_preserves_manual_fields(self) -> None:
        from pyside_desktop.pages.patient_form_page import PatientFormPage
        from pyside_desktop.session import AppSession

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "cnp_autofill.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", SEED_PASSWORDS["admin"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                page = PatientFormPage(db, AppSession(user))
                try:
                    page.show()
                    self._app.processEvents()
                    cnp_edit = page._edits["cnp"]
                    birth_edit = page._edits["birth_date"]
                    gender_edit = page._edits["gender"]
                    valid_cnp_1980_m = self._make_cnp(1, 80, 1, 15, 40, 123)
                    valid_cnp_2001_f = self._make_cnp(6, 1, 2, 3, 40, 222)

                    cnp_edit.setText(valid_cnp_1980_m)
                    self._app.processEvents()
                    self.assertEqual("1980-01-15", birth_edit.text().strip())
                    self.assertEqual("M", gender_edit.text().strip())
                    self.assertEqual("auto din CNP", page._identity_auto_labels["birth_date"].text())
                    self.assertTrue(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertTrue(page._identity_auto_labels["gender"].isVisible())

                    birth_edit.setText("1970-01-01")
                    gender_edit.setText("X")
                    self._app.processEvents()
                    self.assertFalse(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertFalse(page._identity_auto_labels["gender"].isVisible())

                    cnp_edit.setText(valid_cnp_2001_f)
                    self._app.processEvents()
                    self.assertEqual("1970-01-01", birth_edit.text().strip())
                    self.assertEqual("X", gender_edit.text().strip())

                    # Dacă utilizatorul golește câmpurile manuale, acestea revin din CNP-ul valid curent.
                    birth_edit.setText("")
                    gender_edit.setText("")
                    self._app.processEvents()
                    self.assertEqual("2001-02-03", birth_edit.text().strip())
                    self.assertEqual("F", gender_edit.text().strip())
                    self.assertTrue(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertTrue(page._identity_auto_labels["gender"].isVisible())
                finally:
                    page.close()
                    page.deleteLater()
                    self._app.processEvents()
                    del page
                    del db
                    self._app.processEvents()

    def test_patient_form_cnp_invalid_or_empty_clears_auto_markers(self) -> None:
        from pyside_desktop.pages.patient_form_page import PatientFormPage
        from pyside_desktop.session import AppSession

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "cnp_autofill_clear.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", SEED_PASSWORDS["admin"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                page = PatientFormPage(db, AppSession(user))
                try:
                    page.show()
                    self._app.processEvents()
                    cnp_edit = page._edits["cnp"]
                    birth_edit = page._edits["birth_date"]
                    gender_edit = page._edits["gender"]
                    valid_cnp = self._make_cnp(1, 80, 1, 15, 40, 123)
                    wrong_last_digit = (int(valid_cnp[-1]) + 1) % 10
                    invalid_cnp = valid_cnp[:12] + str(wrong_last_digit)

                    cnp_edit.setText(valid_cnp)
                    self._app.processEvents()
                    self.assertEqual("1980-01-15", birth_edit.text().strip())
                    self.assertEqual("M", gender_edit.text().strip())
                    self.assertTrue(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertTrue(page._identity_auto_labels["gender"].isVisible())

                    cnp_edit.setText(invalid_cnp)
                    self._app.processEvents()
                    self.assertFalse(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertFalse(page._identity_auto_labels["gender"].isVisible())
                    self.assertEqual("", birth_edit.toolTip())
                    self.assertEqual("", gender_edit.toolTip())

                    cnp_edit.setText("")
                    self._app.processEvents()
                    self.assertFalse(page._identity_auto_labels["birth_date"].isVisible())
                    self.assertFalse(page._identity_auto_labels["gender"].isVisible())
                finally:
                    page.close()
                    page.deleteLater()
                    self._app.processEvents()
                    del page
                    del db
                    self._app.processEvents()

    def test_patient_form_risk_card_populates_and_warns(self) -> None:
        from pyside_desktop.pages.patient_form_page import PatientFormPage
        from pyside_desktop.session import AppSession

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "risk_card.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", SEED_PASSWORDS["admin"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                page = PatientFormPage(db, AppSession(user))
                try:
                    page.show()
                    self._app.processEvents()

                    page._texts["allergies"].setPlainText("Penicilină")
                    page._texts["chronic_conditions"].setPlainText("HTA")
                    page._texts["surgeries"].setPlainText("Apendicectomie")
                    page._texts["family_history"].setPlainText("Diabet")
                    page._update_risk_card(page._collect_payload())
                    self._app.processEvents()

                    summary = page._risk_summary_label.text()
                    warning = page._risk_warning_label.text()
                    self.assertIn("Alergii: Penicilină", summary)
                    self.assertIn("Afecțiuni cronice: HTA", summary)
                    self.assertIn("Intervenții: Apendicectomie", summary)
                    self.assertIn("Istoric familial: Diabet", summary)
                    self.assertIn("AVERTISMENT RISC", warning)

                    page._texts["allergies"].setPlainText("")
                    page._texts["chronic_conditions"].setPlainText("")
                    page._texts["surgeries"].setPlainText("")
                    page._texts["family_history"].setPlainText("")
                    page._update_risk_card(page._collect_payload())
                    self._app.processEvents()

                    self.assertEqual(
                        "Nicio informație de risc completată.",
                        page._risk_summary_label.text(),
                    )
                    self.assertEqual("", page._risk_warning_label.text())
                finally:
                    page.close()
                    page.deleteLater()
                    self._app.processEvents()
                    del page
                    del db
                    self._app.processEvents()

    def test_patient_form_existing_patient_diagnosis_fields_are_editable(self) -> None:
        from pyside_desktop.pages.patient_form_page import PatientFormPage
        from pyside_desktop.session import AppSession

        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "existing_patient_dx.sqlite"
                db = self._make_db(db_path)
                row = db.authenticate_user("admin", SEED_PASSWORDS["admin"])
                self.assertIsNotNone(row)
                assert row is not None
                user = {
                    "id": int(row["id"]),
                    "username": row["username"],
                    "role": str(row["role"] or "").lower(),
                    "display_name": row["display_name"] or row["username"],
                }
                payload = empty_patient_payload()
                payload["first_name"] = "Ion"
                payload["last_name"] = "Popescu"
                pid = int(db.create_patient(payload))
                session = AppSession(user)
                session.set_patient_id(pid)
                page = PatientFormPage(db, session)
                try:
                    page.show()
                    self._app.processEvents()

                    self.assertTrue(page._save_btn is not None and page._save_btn.isEnabled())
                    self.assertFalse(page._edits["primary_diagnosis_icd10"].isReadOnly())
                    self.assertFalse(page._edits["secondary_diagnoses_icd10"].isReadOnly())
                    self.assertFalse(page._edits["free_diagnosis_text"].isReadOnly())
                finally:
                    page.close()
                    page.deleteLater()
                    self._app.processEvents()
                    del page
                    del db
                    self._app.processEvents()

    def test_seed_roles_authenticate(self) -> None:
        """All four seed users authenticate with SEED_PASSWORDS (sanity for RBAC tests)."""
        with fixed_seed_passwords():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = Path(tmp) / "seed.sqlite"
                db = self._make_db(db_path)
                for username, pw in SEED_PASSWORDS.items():
                    row = db.authenticate_user(username, pw)
                    self.assertIsNotNone(row, msg=f"auth failed for {username}")
                    assert row is not None
                    self.assertEqual(str(row["username"] or "").lower(), username)
                del db


if __name__ == "__main__":
    unittest.main()
