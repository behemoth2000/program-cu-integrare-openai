from __future__ import annotations

from typing import List, Literal, Optional

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - handled at runtime if missing
    class BaseModel:  # type: ignore[override]
        pass

    def Field(*_args, **_kwargs):  # type: ignore[override]
        return None


class PatientDiagnosisDto(BaseModel):
    primary_icd10: str = ""
    secondary_icd10: List[str] = Field(default_factory=list)
    free_text: str = ""


class PatientDto(BaseModel):
    id: Optional[int] = None
    first_name: str
    last_name: str
    cnp: str = ""
    phone: str = ""
    email: str = ""
    birth_date: str = ""
    address: str = ""
    gender: str = ""
    occupation: str = ""
    insurance_provider: str = ""
    insurance_id: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    blood_type: str = ""
    height_cm: str = ""
    weight_kg: str = ""
    medical_history: str = ""
    allergies: str = ""
    chronic_conditions: str = ""
    current_medication: str = ""
    surgeries: str = ""
    family_history: str = ""
    lifestyle_notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    diagnosis: PatientDiagnosisDto = Field(default_factory=PatientDiagnosisDto)


class PatientPatchDto(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    cnp: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    birth_date: Optional[str] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    occupation: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_id: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    blood_type: Optional[str] = None
    height_cm: Optional[str] = None
    weight_kg: Optional[str] = None
    medical_history: Optional[str] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    current_medication: Optional[str] = None
    surgeries: Optional[str] = None
    family_history: Optional[str] = None
    lifestyle_notes: Optional[str] = None
    expected_updated_at: Optional[str] = None
    diagnosis: Optional[PatientDiagnosisDto] = None


class PatientListItemDto(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""
    reception_flag: str = "-"


class AdmissionListItemDto(BaseModel):
    id: int
    mrn: str = ""
    admission_type: str = ""
    triage_level: str = ""
    department: str = ""
    ward: str = ""
    bed: str = ""
    attending_clinician: str = ""
    chief_complaint: str = ""
    status: str = ""
    admitted_at: str = ""
    discharged_at: str = ""
    discharge_summary: str = ""
    case_finalized_at: str = ""


class AdmissionCreateDto(BaseModel):
    admission_type: str = "inpatient"
    triage_level: str = ""
    department: str = ""
    ward: str = ""
    bed: str = ""
    attending_clinician: str = ""
    chief_complaint: str = ""
    admitted_at: str = ""


class AdmissionCreateResultDto(BaseModel):
    admission_id: int
    patient_id: int
    mrn: str = ""
    status: str = "active"
    admitted_at: str = ""
    completed_booking_id: int = 0


class AdmissionDischargeDto(BaseModel):
    discharge_summary: str = ""


class AdmissionDischargeResultDto(BaseModel):
    admission_id: int
    patient_id: int
    booking_id: int = 0
    status: str = "discharged"
    discharged_at: str = ""
    discharge_summary: str = ""


class AdmissionTransferItemDto(BaseModel):
    id: int
    admission_id: int
    action_type: str = ""
    from_department: str = ""
    from_ward: str = ""
    from_bed: str = ""
    to_department: str = ""
    to_ward: str = ""
    to_bed: str = ""
    notes: str = ""
    transferred_at: str = ""


class AdmissionTransferRequestDto(BaseModel):
    to_department: str = ""
    to_ward: str = ""
    to_bed: str = ""
    transferred_at: str = ""
    notes: str = ""


class AdmissionTransferResultDto(BaseModel):
    admission_id: int
    patient_id: int
    department: str = ""
    ward: str = ""
    bed: str = ""
    transferred_at: str = ""


class CaseValidationResultDto(BaseModel):
    admission_id: int
    eligible: bool = False
    errors: List[str] = Field(default_factory=list)
    finalized: bool = False
    finalized_at: str = ""


class FinalizeCaseRequestDto(BaseModel):
    require_financial_closure: bool = False
    require_siui_drg_submission: bool = False


class FinalizeCaseResultDto(BaseModel):
    admission_id: int
    finalized: bool = True
    finalized_at: str = ""


class AdmissionDiagnosesDto(BaseModel):
    referral_diagnosis: str = ""
    admission_diagnosis: str = ""
    discharge_diagnosis: str = ""
    secondary_diagnoses: str = ""
    dietary_regimen: str = ""
    admission_criteria: str = ""
    discharge_criteria: str = ""


class AdmissionDiagnosesResultDto(BaseModel):
    admission_id: int
    updated_at: str = ""
    updated_by_user_id: int = 0


class BillingRecordCreateDto(BaseModel):
    record_type: str = "partial"
    amount: float = 0.0
    issued_at: str = ""
    notes: str = ""
    cost_center_id: Optional[int] = None


class BillingRecordCreateResultDto(BaseModel):
    billing_id: int
    admission_id: int
    patient_id: int
    record_type: str = ""
    amount: float = 0.0
    currency: str = "RON"
    issued_at: str = ""
    status: str = "issued"
    cost_center_id: int = 0


class CaseInvoiceCreateDto(BaseModel):
    invoice_type: str = "proforma"
    series: str = ""
    invoice_number: str = ""
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total_amount: Optional[float] = None
    issued_at: str = ""
    due_date: str = ""
    status: str = "issued"
    notes: str = ""
    partner_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class CaseInvoiceCreateResultDto(BaseModel):
    invoice_id: int
    patient_id: int
    admission_id: int
    invoice_type: str = ""
    series: str = ""
    invoice_number: str = ""
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total_amount: float = 0.0
    currency: str = "RON"
    issued_at: str = ""
    due_date: str = ""
    partner_id: int = 0
    cost_center_id: int = 0
    status: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class InstitutionalReportItemDto(BaseModel):
    id: int
    admission_id: int
    patient_id: int
    report_type: str = ""
    payload_json: str = ""
    payload_hash: str = ""
    validation_errors: str = ""
    status: str = ""
    external_reference: str = ""
    ack_payload: str = ""
    submitted_at: str = ""
    transport_state: str = ""
    transport_attempts: int = 0
    transport_last_error: str = ""
    transport_http_code: int = 0
    transport_last_attempt_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class BillingRecordItemDto(BaseModel):
    id: int
    admission_id: int
    patient_id: int
    record_type: str = ""
    amount: float = 0.0
    currency: str = "RON"
    issued_at: str = ""
    notes: str = ""
    status: str = ""
    cost_center_id: int = 0


class CaseInvoiceItemDto(BaseModel):
    id: int
    patient_id: int
    admission_id: int
    invoice_type: str = ""
    series: str = ""
    invoice_number: str = ""
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total_amount: float = 0.0
    currency: str = "RON"
    issued_at: str = ""
    due_date: str = ""
    partner_id: int = 0
    cost_center_id: int = 0
    status: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class CaseInvoiceStatusUpdateDto(BaseModel):
    status: str = ""


class CaseInvoiceStatusUpdateResultDto(BaseModel):
    invoice_id: int
    admission_id: int
    status: str = ""
    updated_at: str = ""


class InvoicePaymentItemDto(BaseModel):
    id: int
    invoice_id: int
    admission_id: int
    patient_id: int
    amount: float = 0.0
    currency: str = "RON"
    paid_at: str = ""
    payment_method: str = ""
    reference_no: str = ""
    notes: str = ""
    created_at: str = ""


class InvoicePaymentCreateDto(BaseModel):
    amount: float = 0.0
    paid_at: str = ""
    payment_method: str = "cash"
    reference_no: str = ""
    notes: str = ""


class InvoicePaymentCreateResultDto(BaseModel):
    payment_id: int
    invoice_id: int
    admission_id: int
    patient_id: int
    amount: float = 0.0
    currency: str = "RON"
    paid_at: str = ""
    payment_method: str = ""
    reference_no: str = ""
    notes: str = ""
    created_at: str = ""
    invoice_status: str = ""


class OfferContractItemDto(BaseModel):
    id: int
    patient_id: int
    admission_id: int
    doc_type: str = ""
    package_name: str = ""
    accommodation_type: str = ""
    base_price: float = 0.0
    discount_amount: float = 0.0
    final_price: float = 0.0
    currency: str = "RON"
    status: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class OfferContractCreateDto(BaseModel):
    doc_type: str = "offer"
    package_name: str = ""
    accommodation_type: str = ""
    base_price: float = 0.0
    discount_amount: float = 0.0
    final_price: Optional[float] = None
    status: str = "draft"
    notes: str = ""


class OfferContractCreateResultDto(BaseModel):
    offer_id: int
    patient_id: int
    admission_id: int = 0
    doc_type: str = ""
    package_name: str = ""
    accommodation_type: str = ""
    base_price: float = 0.0
    discount_amount: float = 0.0
    final_price: float = 0.0
    currency: str = "RON"
    status: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class OfferContractStatusUpdateDto(BaseModel):
    status: str = ""


class OfferContractStatusUpdateResultDto(BaseModel):
    offer_id: int
    status: str = ""
    updated_at: str = ""


class MedicalLeaveItemDto(BaseModel):
    id: int
    patient_id: int
    admission_id: int
    series: str = ""
    leave_number: str = ""
    issued_at: str = ""
    start_date: str = ""
    end_date: str = ""
    days_count: int = 0
    diagnosis_code: str = ""
    notes: str = ""
    status: str = ""
    series_rule_id: int = 0
    created_at: str = ""


class MedicalLeaveCreateDto(BaseModel):
    series: str = ""
    leave_number: str = ""
    issued_at: str = ""
    start_date: str = ""
    end_date: str = ""
    diagnosis_code: str = ""
    notes: str = ""
    series_rule_id: Optional[int] = None


class MedicalLeaveCreateResultDto(BaseModel):
    leave_id: int
    patient_id: int
    admission_id: int
    series: str = ""
    leave_number: str = ""
    issued_at: str = ""
    start_date: str = ""
    end_date: str = ""
    days_count: int = 0
    diagnosis_code: str = ""
    notes: str = ""
    status: str = ""
    series_rule_id: int = 0
    created_at: str = ""


class MedicalLeaveCancelResultDto(BaseModel):
    leave_id: int
    status: str = "cancelled"


class CaseConsumptionItemDto(BaseModel):
    id: int
    patient_id: int
    admission_id: int
    item_type: str = ""
    item_name: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_price: float = 0.0
    total_price: float = 0.0
    source: str = ""
    partner_id: int = 0
    cost_center_id: int = 0
    status: str = ""
    notes: str = ""
    recorded_at: str = ""


class CaseConsumptionCreateDto(BaseModel):
    item_type: str = ""
    item_name: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_price: float = 0.0
    source: str = ""
    notes: str = ""
    recorded_at: str = ""
    partner_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class CaseConsumptionCreateResultDto(BaseModel):
    consumption_id: int
    patient_id: int
    admission_id: int
    item_type: str = ""
    item_name: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_price: float = 0.0
    total_price: float = 0.0
    source: str = ""
    partner_id: int = 0
    cost_center_id: int = 0
    status: str = ""
    notes: str = ""
    recorded_at: str = ""


class CaseConsumptionStatusUpdateDto(BaseModel):
    status: str = ""


class CaseConsumptionStatusUpdateResultDto(BaseModel):
    consumption_id: int
    status: str = ""


class OrderItemDto(BaseModel):
    id: int
    admission_id: int = 0
    order_type: str = ""
    priority: str = ""
    order_text: str = ""
    status: str = ""
    ordered_at: str = ""
    completed_at: str = ""


class OrderCreateDto(BaseModel):
    admission_id: Optional[int] = None
    order_type: str = ""
    priority: str = ""
    order_text: str = ""


class OrderCreateResultDto(BaseModel):
    order_id: int
    patient_id: int
    admission_id: int = 0
    order_type: str = ""
    priority: str = ""
    order_text: str = ""
    status: str = ""
    ordered_at: str = ""
    completed_at: str = ""


class OrderStatusUpdateDto(BaseModel):
    status: str = ""


class OrderStatusUpdateResultDto(BaseModel):
    order_id: int
    status: str = ""
    completed_at: str = ""


class VitalItemDto(BaseModel):
    id: int
    admission_id: int = 0
    recorded_at: str = ""
    temperature_c: str = ""
    systolic_bp: str = ""
    diastolic_bp: str = ""
    pulse: str = ""
    respiratory_rate: str = ""
    spo2: str = ""
    pain_score: str = ""
    notes: str = ""


class VitalCreateDto(BaseModel):
    admission_id: Optional[int] = None
    recorded_at: str = ""
    temperature_c: str = ""
    systolic_bp: str = ""
    diastolic_bp: str = ""
    pulse: str = ""
    respiratory_rate: str = ""
    spo2: str = ""
    pain_score: str = ""
    notes: str = ""


class VitalCreateResultDto(BaseModel):
    vital_id: int
    patient_id: int
    admission_id: int = 0
    recorded_at: str = ""
    temperature_c: str = ""
    systolic_bp: str = ""
    diastolic_bp: str = ""
    pulse: str = ""
    respiratory_rate: str = ""
    spo2: str = ""
    pain_score: str = ""
    notes: str = ""


class VisitItemDto(BaseModel):
    id: int
    visit_date: str = ""
    reason: str = ""
    diagnosis: str = ""
    treatment: str = ""
    notes: str = ""
    created_at: str = ""


class VisitCreateDto(BaseModel):
    visit_date: str = ""
    reason: str = ""
    diagnosis: str = ""
    treatment: str = ""
    notes: str = ""


class VisitCreateResultDto(BaseModel):
    visit_id: int
    patient_id: int
    visit_date: str = ""
    reason: str = ""
    diagnosis: str = ""
    treatment: str = ""
    notes: str = ""
    created_at: str = ""


class VisitDeleteResultDto(BaseModel):
    visit_id: int
    patient_id: int
    deleted: bool = True


class MedisInvestigationItemDto(BaseModel):
    id: int
    order_id: int = 0
    patient_id: int = 0
    admission_id: int = 0
    provider: str = ""
    external_request_id: str = ""
    requested_at: str = ""
    request_payload: str = ""
    status: str = ""
    result_received_at: str = ""
    result_summary: str = ""
    result_flag: str = ""
    result_payload: str = ""
    external_result_id: str = ""
    transport_state: str = ""
    transport_attempts: int = 0
    transport_last_error: str = ""
    transport_http_code: int = 0
    transport_last_attempt_at: str = ""
    order_type: str = ""
    priority: str = ""
    order_text: str = ""


class DiagnosisSuggestionDto(BaseModel):
    code: str
    title: str
    evidence: str = ""
    confidence: float = 0.0
    severity: Literal["none", "CC", "MCC"] = "none"


class DrgIcmEstimateDto(BaseModel):
    drg_code: str = ""
    drg_label: str = ""
    severity: Literal["none", "CC", "MCC"] = "none"
    icm_estimated: float = 0.0
    is_official: bool = False
    notes: List[str] = Field(default_factory=list)


class DashboardKpiDto(BaseModel):
    active_admissions: int = 0
    triage_1_2: int = 0
    urgent_orders: int = 0
    vital_alerts_24h: int = 0


class DashboardAdmissionItemDto(BaseModel):
    id: int
    patient_id: int = 0
    mrn: str = ""
    admission_type: str = ""
    triage_level: str = ""
    department: str = ""
    ward: str = ""
    bed: str = ""
    attending_clinician: str = ""
    chief_complaint: str = ""
    admitted_at: str = ""
    first_name: str = ""
    last_name: str = ""
    cnp: str = ""


class DashboardUrgentOrderItemDto(BaseModel):
    id: int
    patient_id: int = 0
    admission_id: int = 0
    order_type: str = ""
    priority: str = ""
    status: str = ""
    ordered_at: str = ""
    order_text: str = ""
    mrn: str = ""
    department: str = ""
    first_name: str = ""
    last_name: str = ""


class DashboardVitalAlertItemDto(BaseModel):
    id: int
    patient_id: int = 0
    admission_id: int = 0
    recorded_at: str = ""
    temperature_c: str = ""
    systolic_bp: str = ""
    diastolic_bp: str = ""
    pulse: str = ""
    respiratory_rate: str = ""
    spo2: str = ""
    pain_score: str = ""
    notes: str = ""
    mrn: str = ""
    department: str = ""
    first_name: str = ""
    last_name: str = ""
    reasons: str = ""


class TimelineEventDto(BaseModel):
    event_id: str
    patient_id: int
    admission_id: int = 0
    event_type: str = ""
    category: str = ""
    occurred_at: str = ""
    actor_user_id: int = 0
    actor_name: str = ""
    title: str = ""
    summary: str = ""
    payload_json: str = ""


class PatientSnapshotDto(BaseModel):
    id: int
    patient_id: int
    version_no: int
    trigger_action: str = ""
    trigger_source: str = ""
    trigger_ref_id: str = ""
    snapshot_json: str = ""
    changed_fields_json: str = ""
    snapshot_hash: str = ""
    created_at: str = ""
    created_by_user_id: int = 0
    created_by_username: str = ""


class PatientSnapshotDiffDto(BaseModel):
    patient_id: int
    from_snapshot_id: int = 0
    to_snapshot_id: int = 0
    changed_fields: List[str] = Field(default_factory=list)
    from_snapshot_created_at: str = ""
    to_snapshot_created_at: str = ""
    diff_json: str = ""


class RestoreSnapshotRequestDto(BaseModel):
    reason: str = ""
    expected_updated_at: str = ""


class RestoreSnapshotResultDto(BaseModel):
    ok: bool = False
    patient_id: int
    restored_snapshot_id: int
    backup_snapshot_id: int = 0
    post_snapshot_id: int = 0
    restored_at: str = ""


class HealthDto(BaseModel):
    status: Literal["ok", "degraded", "error"] = "ok"
    app: str = "PacientiAIIndependent"
    timestamp: str = ""
    checks: dict = Field(default_factory=dict)


class IntegrationQueueItemDto(BaseModel):
    id: int
    provider: str = ""
    operation: str = ""
    entity_type: str = ""
    entity_id: int = 0
    status: str = ""
    attempt_count: int = 0
    next_retry_at: str = ""
    last_error: str = ""
    last_http_code: int = 0
    updated_at: str = ""


class IntegrationDryRunLogItemDto(BaseModel):
    id: int
    provider: str = ""
    operation: str = ""
    dry_run: bool = True
    http_code: int = 0
    latency_ms: int = 0
    ok: bool = False
    error: str = ""
    created_at: str = ""
    correlation_id: str = ""
