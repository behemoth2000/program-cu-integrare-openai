import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, PacientiAIApp, canvas, now_ts


class Manual2ReportingFinanceMedisTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual2_reporting_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def _create_patient_and_admission(self) -> tuple[int, int]:
        patient_payload = {
            "first_name": "Radu",
            "last_name": "Ionescu",
            "cnp": "1980101223344",
            "phone": "0711000000",
            "email": "",
            "birth_date": "1980-01-01",
            "address": "",
            "medical_history": "",
            "allergies": "",
            "chronic_conditions": "",
            "current_medication": "",
            "gender": "M",
            "occupation": "",
            "insurance_provider": "CNAS",
            "insurance_id": "ASIG-001",
            "emergency_contact_name": "",
            "emergency_contact_phone": "",
            "blood_type": "",
            "height_cm": "",
            "weight_kg": "",
            "surgeries": "",
            "family_history": "",
            "lifestyle_notes": "",
        }
        patient_id = self.db.create_patient(patient_payload)
        admission_id, _completed = self.db.create_admission(
            {
                "patient_id": str(patient_id),
                "admission_type": "inpatient",
                "triage_level": "3",
                "department": "Ortopedie",
                "ward": "A",
                "bed": "7",
                "attending_clinician": "Dr Demo",
                "chief_complaint": "durere",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def _schedule_and_discharge(self, patient_id: int, admission_id: int) -> None:
        start = now_ts()
        end = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Ortopedie",
                "ward": "A",
                "bed": "7",
                "operating_room": "",
                "attending_clinician": "Dr Demo",
                "starts_at": start,
                "ends_at": end,
                "notes": "",
            },
            user_id=None,
        )
        self.db.discharge_admission(admission_id, "Evolutie favorabila. Fara complicatii.")

    def _fill_required_diagnoses(self, admission_id: int) -> None:
        self.db.upsert_admission_diagnoses(
            admission_id,
            {
                "referral_diagnosis": "M16",
                "admission_diagnosis": "M16",
                "discharge_diagnosis": "M16",
                "secondary_diagnoses": "",
                "dietary_regimen": "Normocaloric",
                "admission_criteria": "Durere severa + limitare functionala",
                "discharge_criteria": "Pacient stabil, mobilizare cu sprijin",
            },
            user_id=None,
        )

    def _prepare_closed_case(self) -> tuple[int, int]:
        patient_id, admission_id = self._create_patient_and_admission()
        self._fill_required_diagnoses(admission_id)
        self._schedule_and_discharge(patient_id, admission_id)
        self.db.create_billing_record(
            admission_id=admission_id,
            record_type="final",
            amount=1200.0,
            issued_at=now_ts(),
            notes="decont final",
            user_id=None,
        )
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="final",
            series="FCT",
            invoice_number=f"{admission_id:04d}",
            subtotal=1000.0,
            tax_amount=200.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura finala",
            user_id=None,
        )
        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=1200.0,
            paid_at=now_ts(),
            payment_method="card",
            reference_no="POS-001",
            notes="Achitare integrala",
            user_id=None,
        )
        return patient_id, admission_id

    def _prepare_discharged_case_with_final_decont_only(self) -> tuple[int, int]:
        patient_id, admission_id = self._create_patient_and_admission()
        self._fill_required_diagnoses(admission_id)
        self._schedule_and_discharge(patient_id, admission_id)
        self.db.create_billing_record(
            admission_id=admission_id,
            record_type="final",
            amount=550.0,
            issued_at=now_ts(),
            notes="decont final",
            user_id=None,
        )
        return patient_id, admission_id

    def _build_export_test_app(self, patient_id: int, admission_id: int) -> PacientiAIApp:
        app = PacientiAIApp.__new__(PacientiAIApp)
        app.db = self.db
        app.current_user = {"id": 1, "username": "qa_tester", "role": "admin"}
        app.current_patient_id = patient_id
        app._require_role = lambda *args, **kwargs: True  # type: ignore[assignment]
        app._selected_admission_id = lambda: admission_id  # type: ignore[assignment]
        app._audit = lambda *args, **kwargs: None  # type: ignore[assignment]
        return app

    def test_proforma_invoice_created_and_listed(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PRF",
            invoice_number=f"{admission_id:04d}",
            subtotal=300.0,
            tax_amount=57.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura proforma UAT",
            user_id=None,
        )
        self.assertGreater(invoice_id, 0)
        rows = self.db.list_case_invoices(admission_id)
        selected = next((row for row in rows if int(row["id"]) == int(invoice_id)), None)
        self.assertIsNotNone(selected)
        self.assertEqual("proforma", selected["invoice_type"])
        self.assertEqual("issued", selected["status"])

    def test_admission_discharge_flow_preserves_transfers(self) -> None:
        patient_id = self.db.create_patient(
            {
                "first_name": "Regina",
                "last_name": "Flow",
                "cnp": "",
                "phone": "",
                "email": "",
                "birth_date": "",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
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
        )
        admitted_at = now_ts()
        admitted_end = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "admission",
                "department": "Medicina interna",
                "ward": "B",
                "bed": "12",
                "operating_room": "",
                "attending_clinician": "Dr Flux",
                "starts_at": admitted_at,
                "ends_at": admitted_end,
                "notes": "Programare internare",
            },
            user_id=None,
        )
        admission_id, completed_admit_booking = self.db.create_admission(
            {
                "patient_id": str(patient_id),
                "admission_type": "inpatient",
                "triage_level": "3",
                "department": "Medicina interna",
                "ward": "B",
                "bed": "12",
                "attending_clinician": "Dr Flux",
                "chief_complaint": "observatie",
                "admitted_at": admitted_at,
            },
            user_id=None,
        )
        self.assertIsNotNone(completed_admit_booking)

        discharge_start = now_ts()
        discharge_end = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Medicina interna",
                "ward": "B",
                "bed": "12",
                "operating_room": "",
                "attending_clinician": "Dr Flux",
                "starts_at": discharge_start,
                "ends_at": discharge_end,
                "notes": "Programare externare",
            },
            user_id=None,
        )
        discharge_booking_id = self.db.discharge_admission(admission_id, "Externare fara incidente.")
        self.assertIsNotNone(discharge_booking_id)

        admissions = self.db.list_admissions(patient_id, include_closed=True, limit=10)
        current = next((row for row in admissions if int(row["id"]) == int(admission_id)), None)
        self.assertIsNotNone(current)
        self.assertEqual("discharged", current["status"])

        transfers = self.db.list_admission_transfers(admission_id, limit=20)
        actions = [str(row["action_type"] or "").lower() for row in transfers]
        self.assertIn("admit", actions)
        self.assertIn("discharge", actions)

    def test_fo_exports_generate_without_errors(self) -> None:
        if canvas is None:
            self.skipTest("reportlab indisponibil pentru export PDF.")
        patient_id, admission_id = self._prepare_discharged_case_with_final_decont_only()
        app = self._build_export_test_app(patient_id, admission_id)

        admission_path = app.export_selected_admission_pdf(silent=True)
        discharge_path = app.export_selected_discharge_ticket_pdf(silent=True)
        self.assertIsNotNone(admission_path)
        self.assertIsNotNone(discharge_path)
        self.assertTrue(admission_path.exists())
        self.assertTrue(discharge_path.exists())
        if admission_path and admission_path.exists():
            admission_path.unlink(missing_ok=True)
        if discharge_path and discharge_path.exists():
            discharge_path.unlink(missing_ok=True)

    def test_final_invoice_requires_discharge(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        with self.assertRaisesRegex(ValueError, "Factura finala se poate emite doar dupa externare"):
            self.db.create_case_invoice(
                admission_id=admission_id,
                invoice_type="final",
                series="FCT",
                invoice_number=f"PRE-{admission_id}",
                subtotal=500.0,
                tax_amount=100.0,
                total_amount=None,
                issued_at=now_ts(),
                due_date=datetime.now().strftime("%Y-%m-%d"),
                status="issued",
                notes="Factura finala inainte de externare",
                user_id=None,
            )

        self._fill_required_diagnoses(admission_id)
        self._schedule_and_discharge(_patient_id, admission_id)
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="final",
            series="FCT",
            invoice_number=f"POST-{admission_id}",
            subtotal=500.0,
            tax_amount=100.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura finala dupa externare",
            user_id=None,
        )
        self.assertGreater(invoice_id, 0)

    def test_institutional_reporting_lifecycle_siui_and_drg(self) -> None:
        _patient_id, admission_id = self._prepare_closed_case()

        siui_id = self.db.create_institutional_report(admission_id=admission_id, report_type="siui", user_id=None)
        siui = self.db.get_institutional_report(siui_id)
        self.assertIsNotNone(siui)
        self.assertEqual(siui["status"], "validated")
        self.assertEqual((siui["validation_errors"] or "").strip(), "")

        self.db.mark_institutional_report_submitted(
            report_id=siui_id,
            external_reference="SIUI-ACK-001",
            ack_payload="OK",
            user_id=None,
        )
        self.assertTrue(self.db.has_submitted_institutional_report(admission_id, "siui"))

        drg_id = self.db.create_institutional_report(admission_id=admission_id, report_type="drg", user_id=None)
        drg = self.db.get_institutional_report(drg_id)
        self.assertIsNotNone(drg)
        self.assertEqual(drg["status"], "validated")
        self.assertEqual((drg["validation_errors"] or "").strip(), "")
        self.db.mark_institutional_report_submitted(
            report_id=drg_id,
            external_reference="DRG-ACK-001",
            ack_payload="OK",
            user_id=None,
        )
        self.assertTrue(self.db.has_submitted_institutional_report(admission_id, "drg"))

    def test_medis_request_and_result_flow_updates_order(self) -> None:
        patient_id, admission_id = self._create_patient_and_admission()
        order_id = self.db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma",
            user_id=None,
        )

        medis_id = self.db.create_medis_investigation(
            order_id=order_id,
            provider="MEDIS",
            external_request_id="REQ-001",
            requested_at=now_ts(),
            request_payload="{\"panel\":\"CBC\"}",
            user_id=None,
        )
        self.assertGreater(medis_id, 0)

        orders_after_send = self.db.list_orders(patient_id)
        sent_order = next(item for item in orders_after_send if int(item["id"]) == int(order_id))
        self.assertEqual(sent_order["status"], "in_progress")

        self.db.record_medis_result(
            investigation_id=medis_id,
            result_summary="Hb 13.5 g/dL, WBC normal",
            result_payload="{\"hb\":13.5,\"wbc\":7.2}",
            result_flag="normal",
            result_received_at=now_ts(),
            user_id=None,
        )

        medis_rows = self.db.list_medis_investigations(patient_id)
        saved = next(item for item in medis_rows if int(item["id"]) == int(medis_id))
        self.assertEqual(saved["status"], "result_received")
        self.assertEqual(saved["result_flag"], "normal")

        orders_after_result = self.db.list_orders(patient_id)
        done_order = next(item for item in orders_after_result if int(item["id"]) == int(order_id))
        self.assertEqual(done_order["status"], "done")

    def test_financial_closure_requires_final_invoice_paid(self) -> None:
        patient_id, admission_id = self._create_patient_and_admission()
        self._fill_required_diagnoses(admission_id)
        self._schedule_and_discharge(patient_id, admission_id)
        self.db.create_billing_record(
            admission_id=admission_id,
            record_type="final",
            amount=800.0,
            issued_at=now_ts(),
            notes="decont final",
            user_id=None,
        )

        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="final",
            series="FCT",
            invoice_number=f"PART-{admission_id}",
            subtotal=700.0,
            tax_amount=100.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura finala",
            user_id=None,
        )
        self.assertFalse(self.db.is_case_financially_closed(admission_id))

        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=300.0,
            paid_at=now_ts(),
            payment_method="cash",
            reference_no="CH-1",
            notes="plata partiala",
            user_id=None,
        )
        self.assertFalse(self.db.is_case_financially_closed(admission_id))

        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=500.0,
            paid_at=now_ts(),
            payment_method="bank_transfer",
            reference_no="TR-2",
            notes="rest plata",
            user_id=None,
        )
        self.assertTrue(self.db.is_case_financially_closed(admission_id))

        snapshot = self.db.get_case_financial_snapshot(admission_id)
        self.assertAlmostEqual(snapshot["invoice_total"], 800.0)
        self.assertAlmostEqual(snapshot["invoice_paid_total"], 800.0)
        self.assertAlmostEqual(snapshot["invoice_outstanding"], 0.0)
        self.assertEqual(snapshot["financially_closed"], 1.0)

    def test_case_validation_rules_on_off(self) -> None:
        _patient_id, admission_id = self._prepare_discharged_case_with_final_decont_only()

        errors_off = self.db.collect_case_validation_errors(
            admission_id,
            require_financial_closure=False,
            require_siui_drg_submission=False,
        )
        self.assertEqual(errors_off, [])

        errors_on = self.db.collect_case_validation_errors(
            admission_id,
            require_financial_closure=True,
            require_siui_drg_submission=True,
        )
        self.assertTrue(
            any("inchiderea economica" in message.lower() for message in errors_on),
            errors_on,
        )
        self.assertTrue(any("siui" in message.lower() for message in errors_on), errors_on)
        self.assertTrue(any("drg" in message.lower() for message in errors_on), errors_on)

        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="final",
            series="FCT",
            invoice_number=f"RULE-{admission_id}",
            subtotal=450.0,
            tax_amount=100.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura finala pentru inchidere economica",
            user_id=None,
        )
        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=300.0,
            paid_at=now_ts(),
            payment_method="cash",
            reference_no="RULE-CASH",
            notes="plata partiala",
            user_id=None,
        )
        still_blocked = self.db.collect_case_validation_errors(
            admission_id,
            require_financial_closure=True,
            require_siui_drg_submission=True,
        )
        self.assertTrue(any("inchiderea economica" in message.lower() for message in still_blocked), still_blocked)

        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=250.0,
            paid_at=now_ts(),
            payment_method="card",
            reference_no="RULE-CARD",
            notes="rest plata",
            user_id=None,
        )
        self.assertTrue(self.db.is_case_financially_closed(admission_id))

        siui_id = self.db.create_institutional_report(admission_id=admission_id, report_type="siui", user_id=None)
        self.db.mark_institutional_report_submitted(
            report_id=siui_id,
            external_reference="SIUI-RULE-ACK",
            ack_payload="OK",
            user_id=None,
        )
        drg_id = self.db.create_institutional_report(admission_id=admission_id, report_type="drg", user_id=None)
        self.db.mark_institutional_report_submitted(
            report_id=drg_id,
            external_reference="DRG-RULE-ACK",
            ack_payload="OK",
            user_id=None,
        )

        errors_resolved = self.db.collect_case_validation_errors(
            admission_id,
            require_financial_closure=True,
            require_siui_drg_submission=True,
        )
        self.assertEqual(errors_resolved, [])
        self.db.finalize_admission_case(
            admission_id,
            user_id=None,
            require_financial_closure=True,
            require_siui_drg_submission=True,
        )
        closure = self.db.get_admission_case_closure(admission_id)
        self.assertIsNotNone(closure)


if __name__ == "__main__":
    unittest.main()
