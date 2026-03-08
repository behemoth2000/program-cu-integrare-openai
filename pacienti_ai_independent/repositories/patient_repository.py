from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class PatientRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_patient(self, patient_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.get_patient(int(patient_id))
        return dict(row) if row else None

    def create_patient(self, payload: Dict[str, str]) -> Dict[str, Any]:
        new_id = self.db.create_patient(payload)
        row = self.db.get_patient(new_id)
        if not row:
            raise ValueError("Pacientul creat nu a putut fi incarcat.")
        return dict(row)

    def update_patient(self, patient_id: int, payload: Dict[str, str]) -> Dict[str, Any]:
        self.db.update_patient(int(patient_id), payload)
        row = self.db.get_patient(int(patient_id))
        if not row:
            raise ValueError("Pacient inexistent.")
        return dict(row)

    def delete_patient(self, patient_id: int) -> bool:
        pid = int(patient_id)
        row = self.db.get_patient(pid)
        if not row:
            return False
        self.db.delete_patient(pid)
        return True

    def list_patients(self, search: str = "", status_filter: str = "all", status_date: str = "") -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_patients(
                search=(search or "").strip(),
                status_filter=(status_filter or "all").strip() or "all",
                status_date=(status_date or "").strip(),
            )
        ]

    def list_recent_visits(self, patient_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.list_visits(int(patient_id), limit=max(1, int(limit)))]

    def list_visits(self, patient_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.list_visits(int(patient_id), limit=max(1, int(limit)))]

    def create_visit(
        self,
        *,
        patient_id: int,
        visit_date: str,
        reason: str,
        diagnosis: str,
        treatment: str,
        notes: str,
    ) -> Dict[str, Any]:
        visit_id = int(
            self.db.add_visit(
                int(patient_id),
                str(visit_date or "").strip(),
                str(reason or "").strip(),
                str(diagnosis or "").strip(),
                str(treatment or "").strip(),
                str(notes or "").strip(),
            )
        )
        row = None
        for item in self.db.list_visits(int(patient_id), limit=2000):
            if int(item["id"] or 0) == visit_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Consultatia adaugata nu a putut fi reincarcata.")
        row["patient_id"] = int(patient_id)
        return row

    def delete_visit(self, visit_id: int) -> Dict[str, Any]:
        vid = int(visit_id)
        with self.db._connect() as conn:
            row = conn.execute(
                """
                SELECT id, patient_id, visit_date, reason, diagnosis, treatment, notes, created_at
                FROM visits
                WHERE id = ?
                LIMIT 1
                """,
                (vid,),
            ).fetchone()
            if not row:
                raise ValueError("Consultatie inexistenta.")
            conn.execute("DELETE FROM visits WHERE id = ?", (vid,))
            conn.commit()
        return dict(row)

    def list_admissions(self, patient_id: int, include_closed: bool = True, limit: int = 200) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_admissions(
                int(patient_id),
                include_closed=bool(include_closed),
                limit=max(1, int(limit)),
            )
        ]

    def get_active_admission(self, patient_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.get_active_admission(int(patient_id))
        return dict(row) if row else None

    def get_admission(self, admission_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.get_admission_for_export(int(admission_id))
        return dict(row) if row else None

    def has_active_bed_conflict(
        self,
        *,
        department: str,
        ward: str,
        bed: str,
        exclude_admission_id: Optional[int] = None,
    ) -> bool:
        return bool(
            self.db.has_active_bed_conflict(
                (department or "").strip(),
                (ward or "").strip(),
                (bed or "").strip(),
                exclude_admission_id=int(exclude_admission_id) if exclude_admission_id else None,
            )
        )

    def create_admission(
        self,
        *,
        patient_id: int,
        payload: Dict[str, str],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        db_payload = {
            "patient_id": str(int(patient_id)),
            "admission_type": str(payload.get("admission_type") or "").strip(),
            "triage_level": str(payload.get("triage_level") or "").strip(),
            "department": str(payload.get("department") or "").strip(),
            "ward": str(payload.get("ward") or "").strip(),
            "bed": str(payload.get("bed") or "").strip(),
            "attending_clinician": str(payload.get("attending_clinician") or "").strip(),
            "chief_complaint": str(payload.get("chief_complaint") or "").strip(),
            "admitted_at": str(payload.get("admitted_at") or "").strip(),
        }
        admission_id, completed_booking_id = self.db.create_admission(db_payload, user_id)
        row = self.get_admission(int(admission_id))
        if not row:
            raise ValueError("Internarea creata nu a putut fi reincarcata.")
        row["completed_booking_id"] = int(completed_booking_id or 0)
        return row

    def discharge_admission(
        self,
        *,
        admission_id: int,
        discharge_summary: str,
    ) -> Dict[str, Any]:
        booking_id = self.db.discharge_admission(
            int(admission_id),
            str(discharge_summary or "").strip(),
        )
        row = self.get_admission(int(admission_id))
        if not row:
            raise ValueError("Internarea externata nu a putut fi reincarcata.")
        row["booking_id"] = int(booking_id or 0)
        return row

    def transfer_admission(
        self,
        *,
        admission_id: int,
        to_department: str,
        to_ward: str,
        to_bed: str,
        transferred_at: str,
        notes: str,
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        self.db.transfer_admission(
            int(admission_id),
            to_department=str(to_department or "").strip(),
            to_ward=str(to_ward or "").strip(),
            to_bed=str(to_bed or "").strip(),
            transferred_at=str(transferred_at or "").strip(),
            notes=str(notes or "").strip(),
            user_id=user_id,
        )
        row = self.get_admission(int(admission_id))
        if not row:
            raise ValueError("Internarea transferata nu a putut fi reincarcata.")
        return row

    def collect_case_validation_errors(
        self,
        *,
        admission_id: int,
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
    ) -> List[str]:
        return list(
            self.db.collect_case_validation_errors(
                int(admission_id),
                require_financial_closure=bool(require_financial_closure),
                require_siui_drg_submission=bool(require_siui_drg_submission),
            )
        )

    def get_admission_case_closure(self, admission_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.get_admission_case_closure(int(admission_id))
        return dict(row) if row else None

    def finalize_admission_case(
        self,
        *,
        admission_id: int,
        user_id: Optional[int],
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
    ) -> Dict[str, Any]:
        self.db.finalize_admission_case(
            int(admission_id),
            user_id=user_id,
            require_financial_closure=bool(require_financial_closure),
            require_siui_drg_submission=bool(require_siui_drg_submission),
        )
        row = self.get_admission_case_closure(int(admission_id))
        if not row:
            raise ValueError("Finalizarea cazului nu a putut fi confirmata.")
        return row

    def list_admission_transfers(self, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_admission_transfers(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def list_orders_for_admission(self, admission_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_orders_for_admission(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def list_vitals_for_admission(self, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_vitals_for_admission(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def list_institutional_reports(self, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_institutional_reports(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def has_submitted_institutional_report(self, admission_id: int, report_type: str) -> bool:
        return bool(
            self.db.has_submitted_institutional_report(
                int(admission_id),
                (report_type or "").strip().lower(),
            )
        )

    def upsert_admission_diagnoses(
        self,
        *,
        admission_id: int,
        payload: Dict[str, str],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        self.db.upsert_admission_diagnoses(int(admission_id), dict(payload or {}), user_id)
        row = self.db.get_admission_diagnoses(int(admission_id))
        if not row:
            raise ValueError("Diagnosticele internarii nu au putut fi reincarcate.")
        return dict(row)

    def create_billing_record(
        self,
        *,
        admission_id: int,
        record_type: str,
        amount: float,
        issued_at: str,
        notes: str,
        cost_center_id: Optional[int],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        billing_id = int(
            self.db.create_billing_record(
                admission_id=int(admission_id),
                record_type=str(record_type or "").strip(),
                amount=float(amount),
                issued_at=str(issued_at or "").strip(),
                notes=str(notes or "").strip(),
                cost_center_id=cost_center_id,
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_billing_records(int(admission_id), limit=2000):
            if int(item["id"] or 0) == billing_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Decontul emis nu a putut fi reincarcat.")
        return row

    def list_billing_records(self, admission_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_billing_records(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def create_case_invoice(
        self,
        *,
        admission_id: int,
        invoice_type: str,
        series: str,
        invoice_number: str,
        subtotal: float,
        tax_amount: float,
        total_amount: Optional[float],
        issued_at: str,
        due_date: str,
        status: str,
        notes: str,
        partner_id: Optional[int],
        cost_center_id: Optional[int],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        invoice_id = int(
            self.db.create_case_invoice(
                admission_id=int(admission_id),
                invoice_type=str(invoice_type or "").strip(),
                series=str(series or "").strip(),
                invoice_number=str(invoice_number or "").strip(),
                subtotal=float(subtotal),
                tax_amount=float(tax_amount),
                total_amount=float(total_amount) if total_amount is not None else None,
                issued_at=str(issued_at or "").strip(),
                due_date=str(due_date or "").strip(),
                status=str(status or "").strip(),
                notes=str(notes or "").strip(),
                partner_id=partner_id,
                cost_center_id=cost_center_id,
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_case_invoices(int(admission_id), limit=2000):
            if int(item["id"] or 0) == invoice_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Factura emisa nu a putut fi reincarcata.")
        return row

    def list_case_invoices(self, admission_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_case_invoices(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def update_case_invoice_status(self, *, invoice_id: int, status: str) -> Dict[str, Any]:
        iid = int(invoice_id)
        admission_id = 0
        with self.db._connect() as conn:
            row_before = conn.execute(
                "SELECT admission_id FROM case_invoices WHERE id = ? LIMIT 1",
                (iid,),
            ).fetchone()
            if not row_before:
                raise ValueError("Factura inexistenta.")
            admission_id = int(row_before["admission_id"] or 0)
        self.db.update_case_invoice_status(iid, str(status or "").strip())
        row = None
        if admission_id > 0:
            for item in self.db.list_case_invoices(admission_id, limit=2000):
                if int(item["id"] or 0) == iid:
                    row = dict(item)
                    break
        if row is None:
            raise ValueError("Factura actualizata nu a putut fi reincarcata.")
        return row

    def create_invoice_payment(
        self,
        *,
        invoice_id: int,
        amount: float,
        paid_at: str,
        payment_method: str,
        reference_no: str,
        notes: str,
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        payment_id = int(
            self.db.register_invoice_payment(
                invoice_id=int(invoice_id),
                amount=float(amount),
                paid_at=str(paid_at or "").strip(),
                payment_method=str(payment_method or "").strip(),
                reference_no=str(reference_no or "").strip(),
                notes=str(notes or "").strip(),
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_invoice_payments(int(invoice_id), limit=2000):
            if int(item["id"] or 0) == payment_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Plata inregistrata nu a putut fi reincarcata.")

        invoice_status = ""
        admission_id = int(row.get("admission_id") or 0)
        if admission_id > 0:
            for inv in self.db.list_case_invoices(admission_id, limit=2000):
                if int(inv["id"] or 0) == int(invoice_id):
                    invoice_status = str(inv["status"] or "").strip()
                    break
        row["invoice_status"] = invoice_status
        return row

    def list_invoice_payments(self, invoice_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_invoice_payments(
                int(invoice_id),
                limit=max(1, int(limit)),
            )
        ]

    def create_offer_contract(
        self,
        *,
        patient_id: int,
        admission_id: int,
        doc_type: str,
        package_name: str,
        accommodation_type: str,
        base_price: float,
        discount_amount: float,
        final_price: Optional[float],
        status: str,
        notes: str,
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        offer_id = int(
            self.db.create_offer_contract(
                patient_id=int(patient_id),
                admission_id=int(admission_id),
                doc_type=str(doc_type or "").strip(),
                package_name=str(package_name or "").strip(),
                accommodation_type=str(accommodation_type or "").strip(),
                base_price=float(base_price),
                discount_amount=float(discount_amount),
                final_price=float(final_price) if final_price is not None else None,
                status=str(status or "").strip(),
                notes=str(notes or "").strip(),
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_offer_contracts(int(admission_id), limit=2000):
            if int(item["id"] or 0) == offer_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Oferta/contractul creat nu a putut fi reincarcat.")
        return row

    def list_offer_contracts(self, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_offer_contracts(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def update_offer_contract_status(self, *, offer_id: int, status: str) -> Dict[str, Any]:
        oid = int(offer_id)
        admission_id = 0
        with self.db._connect() as conn:
            row_before = conn.execute(
                "SELECT admission_id FROM offer_contracts WHERE id = ? LIMIT 1",
                (oid,),
            ).fetchone()
            if not row_before:
                raise ValueError("Document oferta/contract inexistent.")
            admission_id = int(row_before["admission_id"] or 0)
        self.db.update_offer_contract_status(oid, str(status or "").strip())
        row = None
        if admission_id > 0:
            for item in self.db.list_offer_contracts(admission_id, limit=2000):
                if int(item["id"] or 0) == oid:
                    row = dict(item)
                    break
        if row is None:
            raise ValueError("Documentul actualizat nu a putut fi reincarcat.")
        return row

    def create_medical_leave(
        self,
        *,
        admission_id: int,
        series: str,
        leave_number: str,
        issued_at: str,
        start_date: str,
        end_date: str,
        diagnosis_code: str,
        notes: str,
        series_rule_id: Optional[int],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        leave_id = int(
            self.db.create_medical_leave(
                admission_id=int(admission_id),
                series=str(series or "").strip(),
                leave_number=str(leave_number or "").strip(),
                issued_at=str(issued_at or "").strip(),
                start_date=str(start_date or "").strip(),
                end_date=str(end_date or "").strip(),
                diagnosis_code=str(diagnosis_code or "").strip(),
                notes=str(notes or "").strip(),
                series_rule_id=series_rule_id,
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_medical_leaves(int(admission_id), limit=2000):
            if int(item["id"] or 0) == leave_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Concediul medical creat nu a putut fi reincarcat.")
        return row

    def list_medical_leaves(self, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_medical_leaves(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def cancel_medical_leave(self, *, leave_id: int) -> Dict[str, Any]:
        lid = int(leave_id)
        admission_id = 0
        with self.db._connect() as conn:
            row_before = conn.execute(
                "SELECT admission_id FROM medical_leaves WHERE id = ? LIMIT 1",
                (lid,),
            ).fetchone()
            if not row_before:
                raise ValueError("Concediu medical inexistent.")
            admission_id = int(row_before["admission_id"] or 0)
        self.db.cancel_medical_leave(lid)
        row = None
        if admission_id > 0:
            for item in self.db.list_medical_leaves(admission_id, limit=2000):
                if int(item["id"] or 0) == lid:
                    row = dict(item)
                    break
        if row is None:
            raise ValueError("Concediul medical actualizat nu a putut fi reincarcat.")
        return row

    def create_case_consumption(
        self,
        *,
        admission_id: int,
        item_type: str,
        item_name: str,
        unit: str,
        quantity: float,
        unit_price: float,
        source: str,
        notes: str,
        recorded_at: str,
        partner_id: Optional[int],
        cost_center_id: Optional[int],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        consumption_id = int(
            self.db.add_case_consumption(
                admission_id=int(admission_id),
                item_type=str(item_type or "").strip(),
                item_name=str(item_name or "").strip(),
                unit=str(unit or "").strip(),
                quantity=float(quantity),
                unit_price=float(unit_price),
                source=str(source or "").strip(),
                notes=str(notes or "").strip(),
                recorded_at=str(recorded_at or "").strip(),
                partner_id=partner_id,
                cost_center_id=cost_center_id,
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_case_consumptions(int(admission_id), limit=2000):
            if int(item["id"] or 0) == consumption_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Consumul adaugat nu a putut fi reincarcat.")
        return row

    def list_case_consumptions(self, admission_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_case_consumptions(
                int(admission_id),
                limit=max(1, int(limit)),
            )
        ]

    def update_case_consumption_status(self, *, consumption_id: int, status: str) -> Dict[str, Any]:
        cid = int(consumption_id)
        admission_id = 0
        with self.db._connect() as conn:
            row_before = conn.execute(
                "SELECT admission_id FROM case_consumptions WHERE id = ? LIMIT 1",
                (cid,),
            ).fetchone()
            if not row_before:
                raise ValueError("Consum inexistent.")
            admission_id = int(row_before["admission_id"] or 0)
        self.db.update_case_consumption_status(cid, str(status or "").strip())
        row = None
        if admission_id > 0:
            for item in self.db.list_case_consumptions(admission_id, limit=2000):
                if int(item["id"] or 0) == cid:
                    row = dict(item)
                    break
        if row is None:
            raise ValueError("Consumul actualizat nu a putut fi reincarcat.")
        return row

    def create_order(
        self,
        *,
        patient_id: int,
        admission_id: Optional[int],
        order_type: str,
        priority: str,
        order_text: str,
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        order_id = int(
            self.db.add_order(
                patient_id=int(patient_id),
                admission_id=int(admission_id) if admission_id else None,
                order_type=str(order_type or "").strip(),
                priority=str(priority or "").strip(),
                order_text=str(order_text or "").strip(),
                user_id=user_id,
            )
        )
        row = self.db.get_order_by_id(order_id)
        if not row:
            raise ValueError("Ordinul creat nu a putut fi reincarcat.")
        out = dict(row)
        out["patient_id"] = int(patient_id)
        return out

    def list_orders(self, patient_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_orders(
                int(patient_id),
                limit=max(1, int(limit)),
            )
        ]

    def update_order_status(self, *, order_id: int, status: str) -> Dict[str, Any]:
        oid = int(order_id)
        current = self.db.get_order_by_id(oid)
        if not current:
            raise ValueError("Ordin inexistent.")
        self.db.update_order_status(oid, str(status or "").strip())
        row = self.db.get_order_by_id(oid)
        if not row:
            raise ValueError("Ordinul actualizat nu a putut fi reincarcat.")
        return dict(row)

    def create_vital(
        self,
        *,
        patient_id: int,
        admission_id: Optional[int],
        payload: Dict[str, str],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        vital_id = int(
            self.db.add_vital(
                patient_id=int(patient_id),
                admission_id=int(admission_id) if admission_id else None,
                payload=dict(payload or {}),
                user_id=user_id,
            )
        )
        row = None
        for item in self.db.list_vitals(int(patient_id), limit=2000):
            if int(item["id"] or 0) == vital_id:
                row = dict(item)
                break
        if row is None:
            raise ValueError("Semnele vitale adaugate nu au putut fi reincarcate.")
        row["patient_id"] = int(patient_id)
        return row

    def list_vitals(self, patient_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_vitals(
                int(patient_id),
                limit=max(1, int(limit)),
            )
        ]

    def get_dashboard_kpis(self, department: str = "") -> Dict[str, int]:
        row = self.db.get_dashboard_kpis(department=(department or "").strip())
        return {
            "active_admissions": int(row.get("active_admissions") or 0),
            "triage_1_2": int(row.get("triage_1_2") or 0),
            "urgent_orders": int(row.get("urgent_orders") or 0),
            "vital_alerts_24h": int(row.get("vital_alerts_24h") or 0),
        }

    def list_active_admissions_dashboard(self, department: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_active_admissions_dashboard(
                department=(department or "").strip(),
                limit=max(1, int(limit)),
            )
        ]

    def list_urgent_orders_dashboard(self, department: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_urgent_orders_dashboard(
                department=(department or "").strip(),
                limit=max(1, int(limit)),
            )
        ]

    def list_vital_alerts_dashboard(self, department: str = "", hours: int = 24, limit: int = 500) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_vital_alerts_dashboard(
                department=(department or "").strip(),
                hours=max(1, int(hours)),
                limit=max(1, int(limit)),
            )
        ]

    def list_medis_investigations(
        self,
        patient_id: int,
        *,
        admission_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        aid = int(admission_id) if admission_id is not None else None
        return [
            dict(row)
            for row in self.db.list_medis_investigations(
                int(patient_id),
                admission_id=aid,
                limit=max(1, int(limit)),
            )
        ]

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
    ) -> List[Dict[str, Any]]:
        aid = int(admission_id) if admission_id is not None else None
        return [
            dict(row) if not isinstance(row, dict) else row
            for row in self.db.list_patient_timeline(
                int(patient_id),
                limit=max(1, int(limit)),
                category=(category or "").strip(),
                event_type=(event_type or "").strip(),
                date_from=(date_from or "").strip(),
                date_to=(date_to or "").strip(),
                admission_id=aid,
            )
        ]

    def list_patient_snapshots(self, patient_id: int, *, limit: int = 200) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_patient_snapshots(
                int(patient_id),
                limit=max(1, int(limit)),
            )
        ]

    def get_patient_snapshot(self, patient_id: int, snapshot_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.get_patient_snapshot(int(patient_id), int(snapshot_id))
        return dict(row) if row else None

    def get_patient_snapshot_diff(self, patient_id: int, snapshot_id: int) -> Dict[str, Any]:
        return dict(self.db.get_patient_snapshot_diff(int(patient_id), int(snapshot_id)))

    def restore_patient_snapshot(
        self,
        *,
        patient_id: int,
        snapshot_id: int,
        user_id: Optional[int],
        reason: str,
        expected_updated_at: str = "",
    ) -> Dict[str, Any]:
        return dict(
            self.db.restore_patient_from_snapshot(
                patient_id=int(patient_id),
                snapshot_id=int(snapshot_id),
                restored_by_user_id=user_id,
                reason=(reason or "").strip(),
                expected_updated_at=(expected_updated_at or "").strip(),
            )
        )

    def list_recent_orders(self, patient_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.list_orders(int(patient_id), limit=max(1, int(limit)))]

    def list_recent_investigations(self, patient_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.list_medis_investigations(int(patient_id), limit=max(1, int(limit)))]

    def log_diagnosis_suggestions(
        self,
        *,
        patient_id: int,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
        source: str,
        user_id: Optional[int],
        correlation_id: str,
    ) -> int:
        return self.db.log_diagnosis_suggestions(
            patient_id=int(patient_id),
            request_json=json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
            response_json=json.dumps(response_payload, ensure_ascii=False, sort_keys=True),
            source=(source or "").strip() or "rules",
            user_id=user_id,
            correlation_id=correlation_id,
        )

    def save_drg_icm_simulation(
        self,
        *,
        patient_id: int,
        primary_icd10: str,
        secondary_icd10_csv: str,
        free_text: str,
        result_payload: Dict[str, Any],
        is_official: bool,
        user_id: Optional[int],
        correlation_id: str,
    ) -> int:
        return self.db.save_drg_icm_simulation(
            patient_id=int(patient_id),
            primary_icd10=(primary_icd10 or "").strip(),
            secondary_icd10_csv=(secondary_icd10_csv or "").strip(),
            free_text=(free_text or "").strip(),
            result_json=json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
            is_official=bool(is_official),
            user_id=user_id,
            correlation_id=correlation_id,
        )

    def get_idempotency(
        self,
        *,
        endpoint: str,
        key: str,
    ) -> Optional[Dict[str, Any]]:
        return self.db.get_api_idempotency(endpoint=(endpoint or "").strip(), key=(key or "").strip())

    def save_idempotency(
        self,
        *,
        endpoint: str,
        key: str,
        request_body: Any,
        response_status: int,
        response_body: Any,
        user_id: Optional[int],
    ) -> None:
        request_json = json.dumps(request_body, ensure_ascii=False, sort_keys=True)
        response_json = json.dumps(response_body, ensure_ascii=False, sort_keys=True)
        request_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        self.db.save_api_idempotency(
            endpoint=(endpoint or "").strip(),
            key=(key or "").strip(),
            request_hash=request_hash,
            response_status=int(response_status),
            response_json=response_json,
            user_id=user_id,
        )

    def compute_request_hash(self, request_body: Any) -> str:
        payload = json.dumps(request_body, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def list_integration_queue(self, limit: int = 200, status: str = "") -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_integration_queue_jobs(
                limit=max(1, int(limit)),
                status=(status or "").strip(),
            )
        ]

    def list_job_executions(self, limit: int = 200, job_name: str = "") -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_job_executions(
                limit=max(1, int(limit)),
                job_name=(job_name or "").strip(),
            )
        ]

    def list_integration_dry_run_logs(
        self,
        *,
        limit: int = 200,
        provider: str = "",
        operation: str = "",
    ) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_integration_dry_run_logs(
                limit=max(1, int(limit)),
                provider=(provider or "").strip(),
                operation=(operation or "").strip(),
            )
        ]

    def enqueue_shadow_write(
        self,
        *,
        action_key: str,
        source: str,
        payload_json: str,
        payload_hash: str = "",
    ) -> int:
        return int(
            self.db.enqueue_shadow_write_event(
                action_key=(action_key or "").strip(),
                source=(source or "").strip(),
                payload_json=(payload_json or "").strip(),
                payload_hash=(payload_hash or "").strip(),
            )
        )

    def shadow_sync_status(self, lookback_hours: int = 24) -> Dict[str, Any]:
        return self.db.get_shadow_sync_status(lookback_hours=max(1, int(lookback_hours or 24)))

    def shadow_sync_errors(self, limit: int = 200) -> List[Dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.list_shadow_sync_errors(limit=max(1, int(limit)))
        ]

    def process_shadow_sync(
        self,
        *,
        max_jobs: int,
        max_retries: int,
        stop_on_error_rate: float,
        processor: Callable[[Dict[str, Any]], Tuple[bool, str]],
    ) -> Dict[str, Any]:
        return self.db.process_shadow_sync_jobs(
            max_jobs=max_jobs,
            max_retries=max_retries,
            stop_on_error_rate=stop_on_error_rate,
            processor=processor,
        )

    def startup_health(self) -> Dict[str, Any]:
        return self.db.run_startup_self_check()

    def now(self) -> str:
        return now_ts()
