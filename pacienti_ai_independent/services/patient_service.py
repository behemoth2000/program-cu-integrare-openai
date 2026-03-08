from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from pacienti_ai_independent.domain.dto import (
    AdmissionCreateDto,
    AdmissionCreateResultDto,
    AdmissionDiagnosesDto,
    AdmissionDiagnosesResultDto,
    AdmissionDischargeDto,
    AdmissionDischargeResultDto,
    AdmissionListItemDto,
    AdmissionTransferRequestDto,
    AdmissionTransferResultDto,
    BillingRecordCreateDto,
    BillingRecordCreateResultDto,
    AdmissionTransferItemDto,
    BillingRecordItemDto,
    CaseConsumptionCreateDto,
    CaseConsumptionCreateResultDto,
    CaseConsumptionStatusUpdateDto,
    CaseConsumptionStatusUpdateResultDto,
    CaseValidationResultDto,
    CaseConsumptionItemDto,
    CaseInvoiceCreateDto,
    CaseInvoiceCreateResultDto,
    CaseInvoiceItemDto,
    CaseInvoiceStatusUpdateDto,
    CaseInvoiceStatusUpdateResultDto,
    DashboardAdmissionItemDto,
    DashboardKpiDto,
    DashboardUrgentOrderItemDto,
    DashboardVitalAlertItemDto,
    DiagnosisSuggestionDto,
    DrgIcmEstimateDto,
    FinalizeCaseRequestDto,
    FinalizeCaseResultDto,
    InstitutionalReportItemDto,
    MedisInvestigationItemDto,
    MedicalLeaveCancelResultDto,
    MedicalLeaveCreateDto,
    MedicalLeaveCreateResultDto,
    MedicalLeaveItemDto,
    InvoicePaymentCreateDto,
    InvoicePaymentCreateResultDto,
    InvoicePaymentItemDto,
    OrderCreateDto,
    OrderCreateResultDto,
    OrderStatusUpdateDto,
    OrderStatusUpdateResultDto,
    OrderItemDto,
    OfferContractCreateDto,
    OfferContractCreateResultDto,
    OfferContractStatusUpdateDto,
    OfferContractStatusUpdateResultDto,
    VitalItemDto,
    VitalCreateDto,
    VitalCreateResultDto,
    VisitCreateDto,
    VisitCreateResultDto,
    VisitDeleteResultDto,
    VisitItemDto,
    PatientDiagnosisDto,
    PatientDto,
    PatientListItemDto,
    PatientPatchDto,
    PatientSnapshotDiffDto,
    PatientSnapshotDto,
    RestoreSnapshotResultDto,
    TimelineEventDto,
    OfferContractItemDto,
)
from pacienti_ai_independent.pacienti_ai_app import (
    _estimate_drg_icm,
    _extract_icd10_code_from_text,
    _load_icd10_catalog,
    _normalize_icd10_code,
    _parse_icd10_codes_csv,
    _rule_based_diagnosis_suggestions,
    _serialize_icd10_codes_csv,
    now_ts,
)
from pacienti_ai_independent.repositories import PatientRepository


class PatientService:
    def __init__(self, repository: PatientRepository) -> None:
        self.repository = repository
        self.icd10_catalog = _load_icd10_catalog()

    @staticmethod
    def _base_payload() -> Dict[str, str]:
        return {
            "first_name": "",
            "last_name": "",
            "cnp": "",
            "phone": "",
            "email": "",
            "birth_date": "",
            "address": "",
            "medical_history": "",
            "allergies": "",
            "chronic_conditions": "",
            "current_medication": "",
            "primary_diagnosis_icd10": "",
            "secondary_diagnoses_icd10": "",
            "free_diagnosis_text": "",
            "gender": "",
            "occupation": "",
            "insurance_provider": "",
            "insurance_id": "",
            "emergency_contact_name": "",
            "emergency_contact_phone": "",
            "blood_type": "",
            "height_cm": "",
            "weight_kg": "",
            "surgeries": "",
            "family_history": "",
            "lifestyle_notes": "",
        }

    def _row_to_dto(self, row: Dict[str, Any]) -> PatientDto:
        diag = PatientDiagnosisDto(
            primary_icd10=str(row.get("primary_diagnosis_icd10") or ""),
            secondary_icd10=_parse_icd10_codes_csv(str(row.get("secondary_diagnoses_icd10") or "")),
            free_text=str(row.get("free_diagnosis_text") or ""),
        )
        return PatientDto(
            id=int(row.get("id") or 0),
            first_name=str(row.get("first_name") or ""),
            last_name=str(row.get("last_name") or ""),
            cnp=str(row.get("cnp") or ""),
            phone=str(row.get("phone") or ""),
            email=str(row.get("email") or ""),
            birth_date=str(row.get("birth_date") or ""),
            address=str(row.get("address") or ""),
            gender=str(row.get("gender") or ""),
            occupation=str(row.get("occupation") or ""),
            insurance_provider=str(row.get("insurance_provider") or ""),
            insurance_id=str(row.get("insurance_id") or ""),
            emergency_contact_name=str(row.get("emergency_contact_name") or ""),
            emergency_contact_phone=str(row.get("emergency_contact_phone") or ""),
            blood_type=str(row.get("blood_type") or ""),
            height_cm=str(row.get("height_cm") or ""),
            weight_kg=str(row.get("weight_kg") or ""),
            medical_history=str(row.get("medical_history") or ""),
            allergies=str(row.get("allergies") or ""),
            chronic_conditions=str(row.get("chronic_conditions") or ""),
            current_medication=str(row.get("current_medication") or ""),
            surgeries=str(row.get("surgeries") or ""),
            family_history=str(row.get("family_history") or ""),
            lifestyle_notes=str(row.get("lifestyle_notes") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            diagnosis=diag,
        )

    def _apply_diagnosis_to_payload(self, payload: Dict[str, str], diagnosis: Optional[PatientDiagnosisDto]) -> None:
        if diagnosis is None:
            return
        primary_code = _normalize_icd10_code(diagnosis.primary_icd10)
        secondary_codes = [_normalize_icd10_code(item) for item in (diagnosis.secondary_icd10 or []) if item]
        secondary_codes = [item for item in secondary_codes if item and item != primary_code]
        payload["primary_diagnosis_icd10"] = primary_code
        payload["secondary_diagnoses_icd10"] = _serialize_icd10_codes_csv(secondary_codes)
        payload["free_diagnosis_text"] = str(diagnosis.free_text or "").strip()

    def get_patient(self, patient_id: int) -> PatientDto:
        row = self.repository.get_patient(patient_id)
        if not row:
            raise ValueError("Pacient inexistent.")
        return self._row_to_dto(row)

    def list_patients(self, search: str = "", status_filter: str = "all", status_date: str = "") -> List[PatientListItemDto]:
        rows = self.repository.list_patients(
            search=(search or "").strip(),
            status_filter=(status_filter or "all").strip() or "all",
            status_date=(status_date or "").strip(),
        )
        out: List[PatientListItemDto] = []
        for row in rows:
            out.append(
                PatientListItemDto(
                    id=int(row.get("id") or 0),
                    first_name=str(row.get("first_name") or ""),
                    last_name=str(row.get("last_name") or ""),
                    phone=str(row.get("phone") or ""),
                    email=str(row.get("email") or ""),
                    reception_flag=str(row.get("reception_flag") or "-") or "-",
                )
            )
        return out

    def list_admissions(self, patient_id: int, include_closed: bool = True, limit: int = 200) -> List[AdmissionListItemDto]:
        rows = self.repository.list_admissions(
            int(patient_id),
            include_closed=bool(include_closed),
            limit=max(1, int(limit)),
        )
        out: List[AdmissionListItemDto] = []
        for row in rows:
            out.append(
                AdmissionListItemDto(
                    id=int(row.get("id") or 0),
                    mrn=str(row.get("mrn") or ""),
                    admission_type=str(row.get("admission_type") or ""),
                    triage_level=str(row.get("triage_level") or ""),
                    department=str(row.get("department") or ""),
                    ward=str(row.get("ward") or ""),
                    bed=str(row.get("bed") or ""),
                    attending_clinician=str(row.get("attending_clinician") or ""),
                    chief_complaint=str(row.get("chief_complaint") or ""),
                    status=str(row.get("status") or ""),
                    admitted_at=str(row.get("admitted_at") or ""),
                    discharged_at=str(row.get("discharged_at") or ""),
                    discharge_summary=str(row.get("discharge_summary") or ""),
                    case_finalized_at=str(row.get("case_finalized_at") or ""),
                )
            )
        return out

    def get_active_admission(self, patient_id: int) -> Optional[AdmissionListItemDto]:
        row = self.repository.get_active_admission(int(patient_id))
        if not row:
            return None
        return AdmissionListItemDto(
            id=int(row.get("id") or 0),
            mrn=str(row.get("mrn") or ""),
            admission_type=str(row.get("admission_type") or ""),
            triage_level=str(row.get("triage_level") or ""),
            department=str(row.get("department") or ""),
            ward=str(row.get("ward") or ""),
            bed=str(row.get("bed") or ""),
            attending_clinician=str(row.get("attending_clinician") or ""),
            chief_complaint=str(row.get("chief_complaint") or ""),
            status=str(row.get("status") or ""),
            admitted_at=str(row.get("admitted_at") or ""),
            discharged_at="",
            discharge_summary="",
            case_finalized_at="",
        )

    def create_admission(
        self,
        *,
        patient_id: int,
        payload: AdmissionCreateDto,
        user_id: Optional[int],
    ) -> AdmissionCreateResultDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        admitted_at = str(payload.admitted_at or "").strip() or now_ts()
        try:
            datetime.strptime(admitted_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            raise ValueError("Data invalida. Format: YYYY-MM-DD HH:MM:SS")
        triage_level = str(payload.triage_level or "").strip()
        if triage_level not in {"1", "2", "3", "4", "5"}:
            raise ValueError("Triage invalid. Valorile permise sunt 1..5.")
        admission_type = str(payload.admission_type or "").strip().lower() or "inpatient"
        if self.repository.has_active_bed_conflict(
            department=str(payload.department or "").strip(),
            ward=str(payload.ward or "").strip(),
            bed=str(payload.bed or "").strip(),
        ):
            raise ValueError(
                "Patul selectat este deja ocupat de o internare activa. "
                "Alege alta combinatie sectie/salon/pat."
            )
        row = self.repository.create_admission(
            patient_id=int(patient_id),
            payload={
                "admission_type": admission_type,
                "triage_level": triage_level,
                "department": str(payload.department or "").strip(),
                "ward": str(payload.ward or "").strip(),
                "bed": str(payload.bed or "").strip(),
                "attending_clinician": str(payload.attending_clinician or "").strip(),
                "chief_complaint": str(payload.chief_complaint or "").strip(),
                "admitted_at": admitted_at,
            },
            user_id=user_id,
        )
        return AdmissionCreateResultDto(
            admission_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or int(patient_id)),
            mrn=str(row.get("mrn") or "").strip(),
            status=str(row.get("status") or "active").strip() or "active",
            admitted_at=str(row.get("admitted_at") or admitted_at).strip(),
            completed_booking_id=int(row.get("completed_booking_id") or 0),
        )

    def discharge_admission(
        self,
        *,
        admission_id: int,
        payload: AdmissionDischargeDto,
    ) -> AdmissionDischargeResultDto:
        row = self.repository.discharge_admission(
            admission_id=int(admission_id),
            discharge_summary=str(payload.discharge_summary or "").strip(),
        )
        return AdmissionDischargeResultDto(
            admission_id=int(row.get("id") or int(admission_id)),
            patient_id=int(row.get("patient_id") or 0),
            booking_id=int(row.get("booking_id") or 0),
            status=str(row.get("status") or "discharged").strip() or "discharged",
            discharged_at=str(row.get("discharged_at") or "").strip(),
            discharge_summary=str(row.get("discharge_summary") or "").strip(),
        )

    def transfer_admission(
        self,
        *,
        admission_id: int,
        payload: AdmissionTransferRequestDto,
        user_id: Optional[int],
    ) -> AdmissionTransferResultDto:
        transferred_at = str(payload.transferred_at or "").strip() or now_ts()
        try:
            datetime.strptime(transferred_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            raise ValueError("Moment transfer invalid. Format: YYYY-MM-DD HH:MM:SS")
        row = self.repository.transfer_admission(
            admission_id=int(admission_id),
            to_department=str(payload.to_department or "").strip(),
            to_ward=str(payload.to_ward or "").strip(),
            to_bed=str(payload.to_bed or "").strip(),
            transferred_at=transferred_at,
            notes=str(payload.notes or "").strip(),
            user_id=user_id,
        )
        return AdmissionTransferResultDto(
            admission_id=int(row.get("id") or int(admission_id)),
            patient_id=int(row.get("patient_id") or 0),
            department=str(row.get("department") or "").strip(),
            ward=str(row.get("ward") or "").strip(),
            bed=str(row.get("bed") or "").strip(),
            transferred_at=transferred_at,
        )

    def validate_admission_case(
        self,
        *,
        admission_id: int,
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
    ) -> CaseValidationResultDto:
        errors = self.repository.collect_case_validation_errors(
            admission_id=int(admission_id),
            require_financial_closure=bool(require_financial_closure),
            require_siui_drg_submission=bool(require_siui_drg_submission),
        )
        closure = self.repository.get_admission_case_closure(int(admission_id))
        finalized_at = str((closure or {}).get("finalized_at") or "").strip()
        return CaseValidationResultDto(
            admission_id=int(admission_id),
            eligible=not bool(errors),
            errors=[str(item or "").strip() for item in errors if str(item or "").strip()],
            finalized=bool(closure),
            finalized_at=finalized_at,
        )

    def finalize_admission_case(
        self,
        *,
        admission_id: int,
        payload: FinalizeCaseRequestDto,
        user_id: Optional[int],
    ) -> FinalizeCaseResultDto:
        closure = self.repository.finalize_admission_case(
            admission_id=int(admission_id),
            user_id=user_id,
            require_financial_closure=bool(payload.require_financial_closure),
            require_siui_drg_submission=bool(payload.require_siui_drg_submission),
        )
        finalized_at = str(closure.get("finalized_at") or "").strip()
        return FinalizeCaseResultDto(
            admission_id=int(admission_id),
            finalized=True,
            finalized_at=finalized_at,
        )

    def list_admission_transfers(self, admission_id: int, limit: int = 300) -> List[AdmissionTransferItemDto]:
        rows = self.repository.list_admission_transfers(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[AdmissionTransferItemDto] = []
        for row in rows:
            out.append(
                AdmissionTransferItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    action_type=str(row.get("action_type") or ""),
                    from_department=str(row.get("from_department") or ""),
                    from_ward=str(row.get("from_ward") or ""),
                    from_bed=str(row.get("from_bed") or ""),
                    to_department=str(row.get("to_department") or ""),
                    to_ward=str(row.get("to_ward") or ""),
                    to_bed=str(row.get("to_bed") or ""),
                    notes=str(row.get("notes") or ""),
                    transferred_at=str(row.get("transferred_at") or ""),
                )
            )
        return out

    def list_orders_for_admission(self, admission_id: int, limit: int = 200) -> List[OrderItemDto]:
        rows = self.repository.list_orders_for_admission(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[OrderItemDto] = []
        for row in rows:
            out.append(
                OrderItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    order_type=str(row.get("order_type") or ""),
                    priority=str(row.get("priority") or ""),
                    order_text=str(row.get("order_text") or ""),
                    status=str(row.get("status") or ""),
                    ordered_at=str(row.get("ordered_at") or ""),
                    completed_at=str(row.get("completed_at") or ""),
                )
            )
        return out

    def list_vitals_for_admission(self, admission_id: int, limit: int = 300) -> List[VitalItemDto]:
        rows = self.repository.list_vitals_for_admission(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[VitalItemDto] = []
        for row in rows:
            out.append(
                VitalItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    recorded_at=str(row.get("recorded_at") or ""),
                    temperature_c=str(row.get("temperature_c") or ""),
                    systolic_bp=str(row.get("systolic_bp") or ""),
                    diastolic_bp=str(row.get("diastolic_bp") or ""),
                    pulse=str(row.get("pulse") or ""),
                    respiratory_rate=str(row.get("respiratory_rate") or ""),
                    spo2=str(row.get("spo2") or ""),
                    pain_score=str(row.get("pain_score") or ""),
                    notes=str(row.get("notes") or ""),
                )
            )
        return out

    def list_institutional_reports(self, admission_id: int, limit: int = 300) -> List[InstitutionalReportItemDto]:
        rows = self.repository.list_institutional_reports(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[InstitutionalReportItemDto] = []
        for row in rows:
            out.append(
                InstitutionalReportItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    report_type=str(row.get("report_type") or ""),
                    payload_json=str(row.get("payload_json") or ""),
                    payload_hash=str(row.get("payload_hash") or ""),
                    validation_errors=str(row.get("validation_errors") or ""),
                    status=str(row.get("status") or ""),
                    external_reference=str(row.get("external_reference") or ""),
                    ack_payload=str(row.get("ack_payload") or ""),
                    submitted_at=str(row.get("submitted_at") or ""),
                    transport_state=str(row.get("transport_state") or ""),
                    transport_attempts=int(row.get("transport_attempts") or 0),
                    transport_last_error=str(row.get("transport_last_error") or ""),
                    transport_http_code=int(row.get("transport_http_code") or 0),
                    transport_last_attempt_at=str(row.get("transport_last_attempt_at") or ""),
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                )
            )
        return out

    def institutional_reporting_status(self, admission_id: int) -> Dict[str, bool]:
        aid = int(admission_id)
        return {
            "siui": bool(self.repository.has_submitted_institutional_report(aid, "siui")),
            "drg": bool(self.repository.has_submitted_institutional_report(aid, "drg")),
        }

    def list_billing_records(self, admission_id: int, limit: int = 200) -> List[BillingRecordItemDto]:
        rows = self.repository.list_billing_records(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[BillingRecordItemDto] = []
        for row in rows:
            out.append(
                BillingRecordItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    record_type=str(row.get("record_type") or ""),
                    amount=float(row.get("amount") or 0.0),
                    currency=str(row.get("currency") or "RON") or "RON",
                    issued_at=str(row.get("issued_at") or ""),
                    notes=str(row.get("notes") or ""),
                    status=str(row.get("status") or ""),
                    cost_center_id=int(row.get("cost_center_id") or 0),
                )
            )
        return out

    def save_admission_diagnoses(
        self,
        *,
        admission_id: int,
        payload: AdmissionDiagnosesDto,
        user_id: Optional[int],
    ) -> AdmissionDiagnosesResultDto:
        row = self.repository.upsert_admission_diagnoses(
            admission_id=int(admission_id),
            payload={
                "referral_diagnosis": str(payload.referral_diagnosis or "").strip(),
                "admission_diagnosis": str(payload.admission_diagnosis or "").strip(),
                "discharge_diagnosis": str(payload.discharge_diagnosis or "").strip(),
                "secondary_diagnoses": str(payload.secondary_diagnoses or "").strip(),
                "dietary_regimen": str(payload.dietary_regimen or "").strip(),
                "admission_criteria": str(payload.admission_criteria or "").strip(),
                "discharge_criteria": str(payload.discharge_criteria or "").strip(),
            },
            user_id=user_id,
        )
        return AdmissionDiagnosesResultDto(
            admission_id=int(row.get("admission_id") or int(admission_id)),
            updated_at=str(row.get("updated_at") or "").strip(),
            updated_by_user_id=int(row.get("updated_by_user_id") or 0),
        )

    def issue_billing_record(
        self,
        *,
        admission_id: int,
        payload: BillingRecordCreateDto,
        user_id: Optional[int],
    ) -> BillingRecordCreateResultDto:
        row = self.repository.create_billing_record(
            admission_id=int(admission_id),
            record_type=str(payload.record_type or "").strip(),
            amount=float(payload.amount or 0.0),
            issued_at=str(payload.issued_at or "").strip(),
            notes=str(payload.notes or "").strip(),
            cost_center_id=payload.cost_center_id,
            user_id=user_id,
        )
        return BillingRecordCreateResultDto(
            billing_id=int(row.get("id") or 0),
            admission_id=int(row.get("admission_id") or int(admission_id)),
            patient_id=int(row.get("patient_id") or 0),
            record_type=str(row.get("record_type") or "").strip(),
            amount=float(row.get("amount") or 0.0),
            currency=str(row.get("currency") or "RON").strip() or "RON",
            issued_at=str(row.get("issued_at") or "").strip(),
            status=str(row.get("status") or "").strip(),
            cost_center_id=int(row.get("cost_center_id") or 0),
        )

    def issue_case_invoice(
        self,
        *,
        admission_id: int,
        payload: CaseInvoiceCreateDto,
        user_id: Optional[int],
    ) -> CaseInvoiceCreateResultDto:
        row = self.repository.create_case_invoice(
            admission_id=int(admission_id),
            invoice_type=str(payload.invoice_type or "").strip(),
            series=str(payload.series or "").strip(),
            invoice_number=str(payload.invoice_number or "").strip(),
            subtotal=float(payload.subtotal or 0.0),
            tax_amount=float(payload.tax_amount or 0.0),
            total_amount=float(payload.total_amount) if payload.total_amount is not None else None,
            issued_at=str(payload.issued_at or "").strip(),
            due_date=str(payload.due_date or "").strip(),
            status=str(payload.status or "").strip(),
            notes=str(payload.notes or "").strip(),
            partner_id=payload.partner_id,
            cost_center_id=payload.cost_center_id,
            user_id=user_id,
        )
        return CaseInvoiceCreateResultDto(
            invoice_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or 0),
            admission_id=int(row.get("admission_id") or int(admission_id)),
            invoice_type=str(row.get("invoice_type") or "").strip(),
            series=str(row.get("series") or "").strip(),
            invoice_number=str(row.get("invoice_number") or "").strip(),
            subtotal=float(row.get("subtotal") or 0.0),
            tax_amount=float(row.get("tax_amount") or 0.0),
            total_amount=float(row.get("total_amount") or 0.0),
            currency=str(row.get("currency") or "RON").strip() or "RON",
            issued_at=str(row.get("issued_at") or "").strip(),
            due_date=str(row.get("due_date") or "").strip(),
            partner_id=int(row.get("partner_id") or 0),
            cost_center_id=int(row.get("cost_center_id") or 0),
            status=str(row.get("status") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
            updated_at=str(row.get("updated_at") or "").strip(),
        )

    def register_invoice_payment(
        self,
        *,
        invoice_id: int,
        payload: InvoicePaymentCreateDto,
        user_id: Optional[int],
    ) -> InvoicePaymentCreateResultDto:
        row = self.repository.create_invoice_payment(
            invoice_id=int(invoice_id),
            amount=float(payload.amount or 0.0),
            paid_at=str(payload.paid_at or "").strip(),
            payment_method=str(payload.payment_method or "").strip(),
            reference_no=str(payload.reference_no or "").strip(),
            notes=str(payload.notes or "").strip(),
            user_id=user_id,
        )
        return InvoicePaymentCreateResultDto(
            payment_id=int(row.get("id") or 0),
            invoice_id=int(row.get("invoice_id") or int(invoice_id)),
            admission_id=int(row.get("admission_id") or 0),
            patient_id=int(row.get("patient_id") or 0),
            amount=float(row.get("amount") or 0.0),
            currency=str(row.get("currency") or "RON").strip() or "RON",
            paid_at=str(row.get("paid_at") or "").strip(),
            payment_method=str(row.get("payment_method") or "").strip(),
            reference_no=str(row.get("reference_no") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
            invoice_status=str(row.get("invoice_status") or "").strip(),
        )

    def update_case_invoice_status(
        self,
        *,
        invoice_id: int,
        payload: CaseInvoiceStatusUpdateDto,
    ) -> CaseInvoiceStatusUpdateResultDto:
        row = self.repository.update_case_invoice_status(
            invoice_id=int(invoice_id),
            status=str(payload.status or "").strip(),
        )
        return CaseInvoiceStatusUpdateResultDto(
            invoice_id=int(row.get("id") or int(invoice_id)),
            admission_id=int(row.get("admission_id") or 0),
            status=str(row.get("status") or "").strip(),
            updated_at=str(row.get("updated_at") or "").strip(),
        )

    def list_case_invoices(self, admission_id: int, limit: int = 500) -> List[CaseInvoiceItemDto]:
        rows = self.repository.list_case_invoices(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[CaseInvoiceItemDto] = []
        for row in rows:
            out.append(
                CaseInvoiceItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    invoice_type=str(row.get("invoice_type") or ""),
                    series=str(row.get("series") or ""),
                    invoice_number=str(row.get("invoice_number") or ""),
                    subtotal=float(row.get("subtotal") or 0.0),
                    tax_amount=float(row.get("tax_amount") or 0.0),
                    total_amount=float(row.get("total_amount") or 0.0),
                    currency=str(row.get("currency") or "RON") or "RON",
                    issued_at=str(row.get("issued_at") or ""),
                    due_date=str(row.get("due_date") or ""),
                    partner_id=int(row.get("partner_id") or 0),
                    cost_center_id=int(row.get("cost_center_id") or 0),
                    status=str(row.get("status") or ""),
                    notes=str(row.get("notes") or ""),
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                )
            )
        return out

    def list_invoice_payments(self, invoice_id: int, limit: int = 500) -> List[InvoicePaymentItemDto]:
        rows = self.repository.list_invoice_payments(
            int(invoice_id),
            limit=max(1, int(limit)),
        )
        out: List[InvoicePaymentItemDto] = []
        for row in rows:
            out.append(
                InvoicePaymentItemDto(
                    id=int(row.get("id") or 0),
                    invoice_id=int(row.get("invoice_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    amount=float(row.get("amount") or 0.0),
                    currency=str(row.get("currency") or "RON") or "RON",
                    paid_at=str(row.get("paid_at") or ""),
                    payment_method=str(row.get("payment_method") or ""),
                    reference_no=str(row.get("reference_no") or ""),
                    notes=str(row.get("notes") or ""),
                    created_at=str(row.get("created_at") or ""),
                )
            )
        return out

    def create_offer_contract(
        self,
        *,
        patient_id: int,
        admission_id: int,
        payload: OfferContractCreateDto,
        user_id: Optional[int],
    ) -> OfferContractCreateResultDto:
        row = self.repository.create_offer_contract(
            patient_id=int(patient_id),
            admission_id=int(admission_id),
            doc_type=str(payload.doc_type or "").strip(),
            package_name=str(payload.package_name or "").strip(),
            accommodation_type=str(payload.accommodation_type or "").strip(),
            base_price=float(payload.base_price or 0.0),
            discount_amount=float(payload.discount_amount or 0.0),
            final_price=float(payload.final_price) if payload.final_price is not None else None,
            status=str(payload.status or "").strip(),
            notes=str(payload.notes or "").strip(),
            user_id=user_id,
        )
        return OfferContractCreateResultDto(
            offer_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or int(patient_id)),
            admission_id=int(row.get("admission_id") or int(admission_id)),
            doc_type=str(row.get("doc_type") or "").strip(),
            package_name=str(row.get("package_name") or "").strip(),
            accommodation_type=str(row.get("accommodation_type") or "").strip(),
            base_price=float(row.get("base_price") or 0.0),
            discount_amount=float(row.get("discount_amount") or 0.0),
            final_price=float(row.get("final_price") or 0.0),
            currency=str(row.get("currency") or "RON").strip() or "RON",
            status=str(row.get("status") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
            updated_at=str(row.get("updated_at") or "").strip(),
        )

    def update_offer_contract_status(
        self,
        *,
        offer_id: int,
        payload: OfferContractStatusUpdateDto,
    ) -> OfferContractStatusUpdateResultDto:
        row = self.repository.update_offer_contract_status(
            offer_id=int(offer_id),
            status=str(payload.status or "").strip(),
        )
        return OfferContractStatusUpdateResultDto(
            offer_id=int(row.get("id") or int(offer_id)),
            status=str(row.get("status") or "").strip(),
            updated_at=str(row.get("updated_at") or "").strip(),
        )

    def list_offer_contracts(self, admission_id: int, limit: int = 300) -> List[OfferContractItemDto]:
        rows = self.repository.list_offer_contracts(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[OfferContractItemDto] = []
        for row in rows:
            out.append(
                OfferContractItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    doc_type=str(row.get("doc_type") or ""),
                    package_name=str(row.get("package_name") or ""),
                    accommodation_type=str(row.get("accommodation_type") or ""),
                    base_price=float(row.get("base_price") or 0.0),
                    discount_amount=float(row.get("discount_amount") or 0.0),
                    final_price=float(row.get("final_price") or 0.0),
                    currency=str(row.get("currency") or "RON") or "RON",
                    status=str(row.get("status") or ""),
                    notes=str(row.get("notes") or ""),
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                )
            )
        return out

    def create_medical_leave(
        self,
        *,
        admission_id: int,
        payload: MedicalLeaveCreateDto,
        user_id: Optional[int],
    ) -> MedicalLeaveCreateResultDto:
        row = self.repository.create_medical_leave(
            admission_id=int(admission_id),
            series=str(payload.series or "").strip(),
            leave_number=str(payload.leave_number or "").strip(),
            issued_at=str(payload.issued_at or "").strip(),
            start_date=str(payload.start_date or "").strip(),
            end_date=str(payload.end_date or "").strip(),
            diagnosis_code=str(payload.diagnosis_code or "").strip(),
            notes=str(payload.notes or "").strip(),
            series_rule_id=payload.series_rule_id,
            user_id=user_id,
        )
        return MedicalLeaveCreateResultDto(
            leave_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or 0),
            admission_id=int(row.get("admission_id") or int(admission_id)),
            series=str(row.get("series") or "").strip(),
            leave_number=str(row.get("leave_number") or "").strip(),
            issued_at=str(row.get("issued_at") or "").strip(),
            start_date=str(row.get("start_date") or "").strip(),
            end_date=str(row.get("end_date") or "").strip(),
            days_count=int(row.get("days_count") or 0),
            diagnosis_code=str(row.get("diagnosis_code") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            status=str(row.get("status") or "").strip(),
            series_rule_id=int(row.get("series_rule_id") or 0),
            created_at=str(row.get("created_at") or "").strip(),
        )

    def cancel_medical_leave(self, *, leave_id: int) -> MedicalLeaveCancelResultDto:
        row = self.repository.cancel_medical_leave(leave_id=int(leave_id))
        return MedicalLeaveCancelResultDto(
            leave_id=int(row.get("id") or int(leave_id)),
            status=str(row.get("status") or "cancelled").strip() or "cancelled",
        )

    def list_medical_leaves(self, admission_id: int, limit: int = 300) -> List[MedicalLeaveItemDto]:
        rows = self.repository.list_medical_leaves(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[MedicalLeaveItemDto] = []
        for row in rows:
            out.append(
                MedicalLeaveItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    series=str(row.get("series") or ""),
                    leave_number=str(row.get("leave_number") or ""),
                    issued_at=str(row.get("issued_at") or ""),
                    start_date=str(row.get("start_date") or ""),
                    end_date=str(row.get("end_date") or ""),
                    days_count=int(row.get("days_count") or 0),
                    diagnosis_code=str(row.get("diagnosis_code") or ""),
                    notes=str(row.get("notes") or ""),
                    status=str(row.get("status") or ""),
                    series_rule_id=int(row.get("series_rule_id") or 0),
                    created_at=str(row.get("created_at") or ""),
                )
            )
        return out

    def create_case_consumption(
        self,
        *,
        admission_id: int,
        payload: CaseConsumptionCreateDto,
        user_id: Optional[int],
    ) -> CaseConsumptionCreateResultDto:
        row = self.repository.create_case_consumption(
            admission_id=int(admission_id),
            item_type=str(payload.item_type or "").strip(),
            item_name=str(payload.item_name or "").strip(),
            unit=str(payload.unit or "").strip(),
            quantity=float(payload.quantity or 0.0),
            unit_price=float(payload.unit_price or 0.0),
            source=str(payload.source or "").strip(),
            notes=str(payload.notes or "").strip(),
            recorded_at=str(payload.recorded_at or "").strip(),
            partner_id=payload.partner_id,
            cost_center_id=payload.cost_center_id,
            user_id=user_id,
        )
        return CaseConsumptionCreateResultDto(
            consumption_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or 0),
            admission_id=int(row.get("admission_id") or int(admission_id)),
            item_type=str(row.get("item_type") or "").strip(),
            item_name=str(row.get("item_name") or "").strip(),
            unit=str(row.get("unit") or "").strip(),
            quantity=float(row.get("quantity") or 0.0),
            unit_price=float(row.get("unit_price") or 0.0),
            total_price=float(row.get("total_price") or 0.0),
            source=str(row.get("source") or "").strip(),
            partner_id=int(row.get("partner_id") or 0),
            cost_center_id=int(row.get("cost_center_id") or 0),
            status=str(row.get("status") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            recorded_at=str(row.get("recorded_at") or "").strip(),
        )

    def update_case_consumption_status(
        self,
        *,
        consumption_id: int,
        payload: CaseConsumptionStatusUpdateDto,
    ) -> CaseConsumptionStatusUpdateResultDto:
        row = self.repository.update_case_consumption_status(
            consumption_id=int(consumption_id),
            status=str(payload.status or "").strip(),
        )
        return CaseConsumptionStatusUpdateResultDto(
            consumption_id=int(row.get("id") or int(consumption_id)),
            status=str(row.get("status") or "").strip(),
        )

    def list_case_consumptions(self, admission_id: int, limit: int = 500) -> List[CaseConsumptionItemDto]:
        rows = self.repository.list_case_consumptions(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        out: List[CaseConsumptionItemDto] = []
        for row in rows:
            out.append(
                CaseConsumptionItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    item_type=str(row.get("item_type") or ""),
                    item_name=str(row.get("item_name") or ""),
                    unit=str(row.get("unit") or ""),
                    quantity=float(row.get("quantity") or 0.0),
                    unit_price=float(row.get("unit_price") or 0.0),
                    total_price=float(row.get("total_price") or 0.0),
                    source=str(row.get("source") or ""),
                    partner_id=int(row.get("partner_id") or 0),
                    cost_center_id=int(row.get("cost_center_id") or 0),
                    status=str(row.get("status") or ""),
                    notes=str(row.get("notes") or ""),
                    recorded_at=str(row.get("recorded_at") or ""),
                )
            )
        return out

    def create_order(
        self,
        *,
        patient_id: int,
        payload: OrderCreateDto,
        user_id: Optional[int],
    ) -> OrderCreateResultDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        row = self.repository.create_order(
            patient_id=int(patient_id),
            admission_id=payload.admission_id,
            order_type=str(payload.order_type or "").strip(),
            priority=str(payload.priority or "").strip(),
            order_text=str(payload.order_text or "").strip(),
            user_id=user_id,
        )
        return OrderCreateResultDto(
            order_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or int(patient_id)),
            admission_id=int(row.get("admission_id") or 0),
            order_type=str(row.get("order_type") or "").strip(),
            priority=str(row.get("priority") or "").strip(),
            order_text=str(row.get("order_text") or "").strip(),
            status=str(row.get("status") or "").strip(),
            ordered_at=str(row.get("ordered_at") or "").strip(),
            completed_at=str(row.get("completed_at") or "").strip(),
        )

    def update_order_status(
        self,
        *,
        order_id: int,
        payload: OrderStatusUpdateDto,
    ) -> OrderStatusUpdateResultDto:
        row = self.repository.update_order_status(
            order_id=int(order_id),
            status=str(payload.status or "").strip(),
        )
        return OrderStatusUpdateResultDto(
            order_id=int(row.get("id") or int(order_id)),
            status=str(row.get("status") or "").strip(),
            completed_at=str(row.get("completed_at") or "").strip(),
        )

    def list_orders(self, patient_id: int, limit: int = 300) -> List[OrderItemDto]:
        rows = self.repository.list_orders(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        out: List[OrderItemDto] = []
        for row in rows:
            out.append(
                OrderItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    order_type=str(row.get("order_type") or ""),
                    priority=str(row.get("priority") or ""),
                    order_text=str(row.get("order_text") or ""),
                    status=str(row.get("status") or ""),
                    ordered_at=str(row.get("ordered_at") or ""),
                    completed_at=str(row.get("completed_at") or ""),
                )
            )
        return out

    def create_vital(
        self,
        *,
        patient_id: int,
        payload: VitalCreateDto,
        user_id: Optional[int],
    ) -> VitalCreateResultDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        db_payload = {
            "recorded_at": str(payload.recorded_at or "").strip(),
            "temperature_c": str(payload.temperature_c or "").strip(),
            "systolic_bp": str(payload.systolic_bp or "").strip(),
            "diastolic_bp": str(payload.diastolic_bp or "").strip(),
            "pulse": str(payload.pulse or "").strip(),
            "respiratory_rate": str(payload.respiratory_rate or "").strip(),
            "spo2": str(payload.spo2 or "").strip(),
            "pain_score": str(payload.pain_score or "").strip(),
            "notes": str(payload.notes or "").strip(),
        }
        row = self.repository.create_vital(
            patient_id=int(patient_id),
            admission_id=payload.admission_id,
            payload=db_payload,
            user_id=user_id,
        )
        return VitalCreateResultDto(
            vital_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or int(patient_id)),
            admission_id=int(row.get("admission_id") or 0),
            recorded_at=str(row.get("recorded_at") or "").strip(),
            temperature_c=str(row.get("temperature_c") or "").strip(),
            systolic_bp=str(row.get("systolic_bp") or "").strip(),
            diastolic_bp=str(row.get("diastolic_bp") or "").strip(),
            pulse=str(row.get("pulse") or "").strip(),
            respiratory_rate=str(row.get("respiratory_rate") or "").strip(),
            spo2=str(row.get("spo2") or "").strip(),
            pain_score=str(row.get("pain_score") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )

    def list_vitals(self, patient_id: int, limit: int = 300) -> List[VitalItemDto]:
        rows = self.repository.list_vitals(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        out: List[VitalItemDto] = []
        for row in rows:
            out.append(
                VitalItemDto(
                    id=int(row.get("id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    recorded_at=str(row.get("recorded_at") or ""),
                    temperature_c=str(row.get("temperature_c") or ""),
                    systolic_bp=str(row.get("systolic_bp") or ""),
                    diastolic_bp=str(row.get("diastolic_bp") or ""),
                    pulse=str(row.get("pulse") or ""),
                    respiratory_rate=str(row.get("respiratory_rate") or ""),
                    spo2=str(row.get("spo2") or ""),
                    pain_score=str(row.get("pain_score") or ""),
                    notes=str(row.get("notes") or ""),
                )
            )
        return out

    def create_visit(
        self,
        *,
        patient_id: int,
        payload: VisitCreateDto,
    ) -> VisitCreateResultDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        row = self.repository.create_visit(
            patient_id=int(patient_id),
            visit_date=str(payload.visit_date or "").strip(),
            reason=str(payload.reason or "").strip(),
            diagnosis=str(payload.diagnosis or "").strip(),
            treatment=str(payload.treatment or "").strip(),
            notes=str(payload.notes or "").strip(),
        )
        return VisitCreateResultDto(
            visit_id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or int(patient_id)),
            visit_date=str(row.get("visit_date") or "").strip(),
            reason=str(row.get("reason") or "").strip(),
            diagnosis=str(row.get("diagnosis") or "").strip(),
            treatment=str(row.get("treatment") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
        )

    def delete_visit(self, *, visit_id: int) -> VisitDeleteResultDto:
        row = self.repository.delete_visit(int(visit_id))
        return VisitDeleteResultDto(
            visit_id=int(row.get("id") or int(visit_id)),
            patient_id=int(row.get("patient_id") or 0),
            deleted=True,
        )

    def list_visits(self, patient_id: int, limit: int = 200) -> List[VisitItemDto]:
        rows = self.repository.list_visits(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        out: List[VisitItemDto] = []
        for row in rows:
            out.append(
                VisitItemDto(
                    id=int(row.get("id") or 0),
                    visit_date=str(row.get("visit_date") or ""),
                    reason=str(row.get("reason") or ""),
                    diagnosis=str(row.get("diagnosis") or ""),
                    treatment=str(row.get("treatment") or ""),
                    notes=str(row.get("notes") or ""),
                    created_at=str(row.get("created_at") or ""),
                )
            )
        return out

    def list_medis_investigations(
        self,
        patient_id: int,
        *,
        admission_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[MedisInvestigationItemDto]:
        rows = self.repository.list_medis_investigations(
            int(patient_id),
            admission_id=admission_id,
            limit=max(1, int(limit)),
        )
        out: List[MedisInvestigationItemDto] = []
        for row in rows:
            out.append(
                MedisInvestigationItemDto(
                    id=int(row.get("id") or 0),
                    order_id=int(row.get("order_id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    provider=str(row.get("provider") or ""),
                    external_request_id=str(row.get("external_request_id") or ""),
                    requested_at=str(row.get("requested_at") or ""),
                    request_payload=str(row.get("request_payload") or ""),
                    status=str(row.get("status") or ""),
                    result_received_at=str(row.get("result_received_at") or ""),
                    result_summary=str(row.get("result_summary") or ""),
                    result_flag=str(row.get("result_flag") or ""),
                    result_payload=str(row.get("result_payload") or ""),
                    external_result_id=str(row.get("external_result_id") or ""),
                    transport_state=str(row.get("transport_state") or ""),
                    transport_attempts=int(row.get("transport_attempts") or 0),
                    transport_last_error=str(row.get("transport_last_error") or ""),
                    transport_http_code=int(row.get("transport_http_code") or 0),
                    transport_last_attempt_at=str(row.get("transport_last_attempt_at") or ""),
                    order_type=str(row.get("order_type") or ""),
                    priority=str(row.get("priority") or ""),
                    order_text=str(row.get("order_text") or ""),
                )
            )
        return out

    def list_patient_timeline(
        self,
        patient_id: int,
        *,
        limit: int = 500,
        category: str = "",
        event_type: str = "",
        date_from: str = "",
        date_to: str = "",
        admission_id: Optional[int] = None,
    ) -> List[TimelineEventDto]:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        rows = self.repository.list_patient_timeline(
            int(patient_id),
            limit=max(1, int(limit)),
            category=(category or "").strip(),
            event_type=(event_type or "").strip(),
            date_from=(date_from or "").strip(),
            date_to=(date_to or "").strip(),
            admission_id=admission_id,
        )
        out: List[TimelineEventDto] = []
        for row in rows:
            out.append(
                TimelineEventDto(
                    event_id=str(row.get("event_id") or ""),
                    patient_id=int(row.get("patient_id") or patient_id or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    event_type=str(row.get("event_type") or ""),
                    category=str(row.get("category") or ""),
                    occurred_at=str(row.get("occurred_at") or ""),
                    actor_user_id=int(row.get("actor_user_id") or 0),
                    actor_name=str(row.get("actor_name") or ""),
                    title=str(row.get("title") or ""),
                    summary=str(row.get("summary") or ""),
                    payload_json=str(row.get("payload_json") or ""),
                )
            )
        return out

    def list_patient_snapshots(self, patient_id: int, *, limit: int = 200) -> List[PatientSnapshotDto]:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        rows = self.repository.list_patient_snapshots(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        out: List[PatientSnapshotDto] = []
        for row in rows:
            out.append(
                PatientSnapshotDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    version_no=int(row.get("version_no") or 0),
                    trigger_action=str(row.get("trigger_action") or ""),
                    trigger_source=str(row.get("trigger_source") or ""),
                    trigger_ref_id=str(row.get("trigger_ref_id") or ""),
                    snapshot_json=str(row.get("snapshot_json") or ""),
                    changed_fields_json=str(row.get("changed_fields_json") or ""),
                    snapshot_hash=str(row.get("snapshot_hash") or ""),
                    created_at=str(row.get("created_at") or ""),
                    created_by_user_id=int(row.get("created_by_user_id") or 0),
                    created_by_username=str(row.get("created_by_username") or ""),
                )
            )
        return out

    def get_patient_snapshot(self, patient_id: int, snapshot_id: int) -> PatientSnapshotDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        row = self.repository.get_patient_snapshot(int(patient_id), int(snapshot_id))
        if not row:
            raise ValueError("Snapshot inexistent.")
        return PatientSnapshotDto(
            id=int(row.get("id") or 0),
            patient_id=int(row.get("patient_id") or 0),
            version_no=int(row.get("version_no") or 0),
            trigger_action=str(row.get("trigger_action") or ""),
            trigger_source=str(row.get("trigger_source") or ""),
            trigger_ref_id=str(row.get("trigger_ref_id") or ""),
            snapshot_json=str(row.get("snapshot_json") or ""),
            changed_fields_json=str(row.get("changed_fields_json") or ""),
            snapshot_hash=str(row.get("snapshot_hash") or ""),
            created_at=str(row.get("created_at") or ""),
            created_by_user_id=int(row.get("created_by_user_id") or 0),
            created_by_username=str(row.get("created_by_username") or ""),
        )

    def get_patient_snapshot_diff(self, patient_id: int, snapshot_id: int) -> PatientSnapshotDiffDto:
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        row = self.repository.get_patient_snapshot_diff(int(patient_id), int(snapshot_id))
        return PatientSnapshotDiffDto(
            patient_id=int(row.get("patient_id") or 0),
            from_snapshot_id=int(row.get("from_snapshot_id") or 0),
            to_snapshot_id=int(row.get("to_snapshot_id") or 0),
            changed_fields=[str(item) for item in (row.get("changed_fields") or []) if str(item).strip()],
            from_snapshot_created_at=str(row.get("from_snapshot_created_at") or ""),
            to_snapshot_created_at=str(row.get("to_snapshot_created_at") or ""),
            diff_json=str(row.get("diff_json") or ""),
        )

    def restore_patient_snapshot(
        self,
        *,
        patient_id: int,
        snapshot_id: int,
        reason: str,
        user_id: Optional[int],
        expected_updated_at: str = "",
    ) -> RestoreSnapshotResultDto:
        reason_txt = (reason or "").strip()
        expected_updated_at_txt = (expected_updated_at or "").strip()
        if not reason_txt:
            raise ValueError("Motiv restore obligatoriu.")
        if not self.repository.get_patient(int(patient_id)):
            raise ValueError("Pacient inexistent.")
        if not self.repository.get_patient_snapshot(int(patient_id), int(snapshot_id)):
            raise ValueError("Snapshot inexistent.")
        row = self.repository.restore_patient_snapshot(
            patient_id=int(patient_id),
            snapshot_id=int(snapshot_id),
            user_id=user_id,
            reason=reason_txt,
            expected_updated_at=expected_updated_at_txt,
        )
        return RestoreSnapshotResultDto(
            ok=bool(row.get("ok", False)),
            patient_id=int(row.get("patient_id") or 0),
            restored_snapshot_id=int(row.get("restored_snapshot_id") or 0),
            backup_snapshot_id=int(row.get("backup_snapshot_id") or 0),
            post_snapshot_id=int(row.get("post_snapshot_id") or 0),
            restored_at=str(row.get("restored_at") or ""),
        )

    def get_dashboard_kpis(self, department: str = "") -> DashboardKpiDto:
        row = self.repository.get_dashboard_kpis((department or "").strip())
        return DashboardKpiDto(
            active_admissions=int(row.get("active_admissions") or 0),
            triage_1_2=int(row.get("triage_1_2") or 0),
            urgent_orders=int(row.get("urgent_orders") or 0),
            vital_alerts_24h=int(row.get("vital_alerts_24h") or 0),
        )

    def list_dashboard_active_admissions(self, department: str = "", limit: int = 500) -> List[DashboardAdmissionItemDto]:
        rows = self.repository.list_active_admissions_dashboard(
            department=(department or "").strip(),
            limit=max(1, int(limit)),
        )
        out: List[DashboardAdmissionItemDto] = []
        for row in rows:
            out.append(
                DashboardAdmissionItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    mrn=str(row.get("mrn") or ""),
                    admission_type=str(row.get("admission_type") or ""),
                    triage_level=str(row.get("triage_level") or ""),
                    department=str(row.get("department") or ""),
                    ward=str(row.get("ward") or ""),
                    bed=str(row.get("bed") or ""),
                    attending_clinician=str(row.get("attending_clinician") or ""),
                    chief_complaint=str(row.get("chief_complaint") or ""),
                    admitted_at=str(row.get("admitted_at") or ""),
                    first_name=str(row.get("first_name") or ""),
                    last_name=str(row.get("last_name") or ""),
                    cnp=str(row.get("cnp") or ""),
                )
            )
        return out

    def list_dashboard_urgent_orders(self, department: str = "", limit: int = 500) -> List[DashboardUrgentOrderItemDto]:
        rows = self.repository.list_urgent_orders_dashboard(
            department=(department or "").strip(),
            limit=max(1, int(limit)),
        )
        out: List[DashboardUrgentOrderItemDto] = []
        for row in rows:
            out.append(
                DashboardUrgentOrderItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    order_type=str(row.get("order_type") or ""),
                    priority=str(row.get("priority") or ""),
                    status=str(row.get("status") or ""),
                    ordered_at=str(row.get("ordered_at") or ""),
                    order_text=str(row.get("order_text") or ""),
                    mrn=str(row.get("mrn") or ""),
                    department=str(row.get("department") or ""),
                    first_name=str(row.get("first_name") or ""),
                    last_name=str(row.get("last_name") or ""),
                )
            )
        return out

    def list_dashboard_vital_alerts(
        self,
        department: str = "",
        hours: int = 24,
        limit: int = 500,
    ) -> List[DashboardVitalAlertItemDto]:
        rows = self.repository.list_vital_alerts_dashboard(
            department=(department or "").strip(),
            hours=max(1, int(hours)),
            limit=max(1, int(limit)),
        )
        out: List[DashboardVitalAlertItemDto] = []
        for row in rows:
            out.append(
                DashboardVitalAlertItemDto(
                    id=int(row.get("id") or 0),
                    patient_id=int(row.get("patient_id") or 0),
                    admission_id=int(row.get("admission_id") or 0),
                    recorded_at=str(row.get("recorded_at") or ""),
                    temperature_c=str(row.get("temperature_c") or ""),
                    systolic_bp=str(row.get("systolic_bp") or ""),
                    diastolic_bp=str(row.get("diastolic_bp") or ""),
                    pulse=str(row.get("pulse") or ""),
                    respiratory_rate=str(row.get("respiratory_rate") or ""),
                    spo2=str(row.get("spo2") or ""),
                    pain_score=str(row.get("pain_score") or ""),
                    notes=str(row.get("notes") or ""),
                    mrn=str(row.get("mrn") or ""),
                    department=str(row.get("department") or ""),
                    first_name=str(row.get("first_name") or ""),
                    last_name=str(row.get("last_name") or ""),
                    reasons=str(row.get("reasons") or ""),
                )
            )
        return out

    def create_patient(self, dto: PatientDto) -> PatientDto:
        payload = self._base_payload()
        dto_data = dto.model_dump() if hasattr(dto, "model_dump") else dto.__dict__
        for key in payload.keys():
            if key in {"primary_diagnosis_icd10", "secondary_diagnoses_icd10", "free_diagnosis_text"}:
                continue
            value = dto_data.get(key)
            if value is not None:
                payload[key] = str(value).strip()
        self._apply_diagnosis_to_payload(payload, dto.diagnosis)
        if not payload["first_name"] or not payload["last_name"]:
            raise ValueError("first_name si last_name sunt obligatorii.")
        row = self.repository.create_patient(payload)
        return self._row_to_dto(row)

    def patch_patient(self, patient_id: int, patch: PatientPatchDto) -> PatientDto:
        current = self.repository.get_patient(patient_id)
        if not current:
            raise ValueError("Pacient inexistent.")
        payload = self._base_payload()
        for key in payload.keys():
            payload[key] = str(current.get(key) or "").strip()

        patch_data = patch.model_dump(exclude_unset=True) if hasattr(patch, "model_dump") else dict(patch.__dict__)
        expected_updated_at = str(patch_data.pop("expected_updated_at", "") or "").strip()
        current_updated_at = str(current.get("updated_at") or "").strip()
        if expected_updated_at and expected_updated_at != current_updated_at:
            raise ValueError(
                "Conflict de concurenta: fisa pacientului a fost modificata intre timp. "
                f"updated_at curent={current_updated_at or '-'}."
            )

        for key, value in patch_data.items():
            if key == "diagnosis":
                continue
            if key in payload and value is not None:
                payload[key] = str(value).strip()
        diag_patch = patch_data.get("diagnosis")
        if diag_patch is not None:
            if not isinstance(diag_patch, PatientDiagnosisDto):
                diag_patch = PatientDiagnosisDto(**diag_patch)
            self._apply_diagnosis_to_payload(payload, diag_patch)
        row = self.repository.update_patient(patient_id, payload)
        return self._row_to_dto(row)

    def delete_patient(self, patient_id: int, *, expected_updated_at: str = "") -> None:
        expected_updated_at_txt = (expected_updated_at or "").strip()
        if expected_updated_at_txt:
            row = self.repository.get_patient(int(patient_id))
            if row:
                current_updated_at = str(row.get("updated_at") or "").strip()
                if current_updated_at != expected_updated_at_txt:
                    raise ValueError(
                        "Conflict de concurenta: fisa pacientului a fost modificata intre timp. "
                        f"updated_at curent={current_updated_at or '-'}."
                    )
        deleted = self.repository.delete_patient(int(patient_id))
        if not deleted:
            raise ValueError("Pacient inexistent.")

    def diagnosis_suggestions(
        self,
        *,
        patient_id: int,
        user_id: Optional[int],
        correlation_id: str,
    ) -> List[DiagnosisSuggestionDto]:
        patient = self.repository.get_patient(patient_id)
        if not patient:
            raise ValueError("Pacient inexistent.")
        visits = self.repository.list_recent_visits(patient_id, limit=25)
        orders = self.repository.list_recent_orders(patient_id, limit=25)
        investigations = self.repository.list_recent_investigations(patient_id, limit=25)
        context_sections = {
            "history": str(patient.get("medical_history") or ""),
            "chronic": str(patient.get("chronic_conditions") or ""),
            "medication": str(patient.get("current_medication") or ""),
            "visits": "\n".join(
                f"{row.get('visit_date')} | {row.get('reason')} | {row.get('diagnosis')} | {row.get('notes')}"
                for row in visits
            ),
            "orders": "\n".join(
                f"{row.get('ordered_at')} | {row.get('order_type')} | {row.get('status')} | {row.get('order_text')}"
                for row in orders
            ),
            "investigations": "\n".join(
                f"{row.get('requested_at')} | {row.get('status')} | {row.get('result_summary')} | {row.get('result_payload')}"
                for row in investigations
            ),
            "free_diag": str(patient.get("free_diagnosis_text") or ""),
        }
        existing_codes = [_normalize_icd10_code(str(patient.get("primary_diagnosis_icd10") or ""))]
        existing_codes.extend(_parse_icd10_codes_csv(str(patient.get("secondary_diagnoses_icd10") or "")))
        raw_rows = _rule_based_diagnosis_suggestions(
            context_sections=context_sections,
            icd10_catalog=self.icd10_catalog,
            existing_codes=existing_codes,
            limit=12,
        )
        result = [
            DiagnosisSuggestionDto(
                code=str(item.get("code") or ""),
                title=str(item.get("title") or item.get("code") or ""),
                evidence=str(item.get("evidence") or ""),
                confidence=float(item.get("confidence") or 0.0),
                severity=str(item.get("severity") or "none"),
            )
            for item in raw_rows
            if str(item.get("code") or "").strip()
        ]
        self.repository.log_diagnosis_suggestions(
            patient_id=patient_id,
            request_payload={
                "patient_id": patient_id,
                "existing_codes": existing_codes,
            },
            response_payload={"suggestions": [item.model_dump() for item in result]},
            source="rules",
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return result

    def drg_icm_estimate(
        self,
        *,
        patient_id: int,
        diagnosis: Optional[PatientDiagnosisDto],
        user_id: Optional[int],
        correlation_id: str,
    ) -> DrgIcmEstimateDto:
        patient = self.repository.get_patient(patient_id)
        if not patient:
            raise ValueError("Pacient inexistent.")

        if diagnosis is None:
            primary = _normalize_icd10_code(str(patient.get("primary_diagnosis_icd10") or ""))
            secondary = _parse_icd10_codes_csv(str(patient.get("secondary_diagnoses_icd10") or ""))
            free_text = str(patient.get("free_diagnosis_text") or "")
        else:
            primary = _extract_icd10_code_from_text(diagnosis.primary_icd10)
            secondary = [_normalize_icd10_code(item) for item in (diagnosis.secondary_icd10 or []) if item]
            secondary = [item for item in secondary if item and item != primary]
            free_text = str(diagnosis.free_text or "")

        estimate = _estimate_drg_icm(
            primary_code=primary,
            secondary_codes=secondary,
            birth_date=str(patient.get("birth_date") or ""),
            free_diagnosis_text=free_text,
        )
        result = DrgIcmEstimateDto(
            drg_code=str(estimate.get("drg_code") or ""),
            drg_label=str(estimate.get("drg_label") or ""),
            severity=str(estimate.get("severity") or "none"),
            icm_estimated=float(estimate.get("icm_estimated") or 0.0),
            is_official=bool(estimate.get("is_official") or False),
            notes=[str(item) for item in (estimate.get("notes") or [])],
        )
        self.repository.save_drg_icm_simulation(
            patient_id=patient_id,
            primary_icd10=primary,
            secondary_icd10_csv=_serialize_icd10_codes_csv(secondary),
            free_text=free_text,
            result_payload=result.model_dump(),
            is_official=False,
            user_id=user_id,
            correlation_id=correlation_id,
        )
        return result

    def integration_queue(self, limit: int = 200, status: str = "") -> List[Dict[str, Any]]:
        return self.repository.list_integration_queue(limit=limit, status=status)

    def job_executions(self, limit: int = 200, job_name: str = "") -> List[Dict[str, Any]]:
        return self.repository.list_job_executions(limit=limit, job_name=job_name)

    def integration_dry_run_logs(
        self,
        *,
        limit: int = 200,
        provider: str = "",
        operation: str = "",
    ) -> List[Dict[str, Any]]:
        return self.repository.list_integration_dry_run_logs(
            limit=limit,
            provider=provider,
            operation=operation,
        )

    def enqueue_shadow_write(
        self,
        *,
        action_key: str,
        source: str,
        payload_json: str,
        payload_hash: str = "",
    ) -> int:
        return int(
            self.repository.enqueue_shadow_write(
                action_key=action_key,
                source=source,
                payload_json=payload_json,
                payload_hash=payload_hash,
            )
        )

    def shadow_sync_status(self, lookback_hours: int = 24) -> Dict[str, Any]:
        return self.repository.shadow_sync_status(lookback_hours=lookback_hours)

    def shadow_sync_errors(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.repository.shadow_sync_errors(limit=limit)

    def process_shadow_sync(
        self,
        *,
        max_jobs: int,
        max_retries: int,
        stop_on_error_rate: float,
        processor: Callable[[Dict[str, Any]], Tuple[bool, str]],
    ) -> Dict[str, Any]:
        return self.repository.process_shadow_sync(
            max_jobs=max_jobs,
            max_retries=max_retries,
            stop_on_error_rate=stop_on_error_rate,
            processor=processor,
        )

    def health(self) -> Dict[str, Any]:
        return self.repository.startup_health()
