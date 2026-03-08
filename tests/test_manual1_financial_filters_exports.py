import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class Manual1FinancialFiltersExportsTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual1_filters_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def _create_patient_and_admission(self) -> tuple[int, int]:
        patient_id = self.db.create_patient(
            {
                "first_name": "Filtru",
                "last_name": "Financiar",
                "cnp": "1950101223344",
                "phone": "",
                "email": "",
                "birth_date": "1995-01-01",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "gender": "F",
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
        admission_id, _ = self.db.create_admission(
            {
                "patient_id": str(patient_id),
                "admission_type": "inpatient",
                "triage_level": "3",
                "department": "Ortopedie",
                "ward": "A",
                "bed": "2",
                "attending_clinician": "Dr Export",
                "chief_complaint": "test",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def test_financial_filters_and_html_export(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        partner_id = self.db.create_business_partner(
            {
                "code": "PAY001",
                "name": "Platitor Contractual",
                "partner_type": "payer",
                "fiscal_code": "RO11112222",
                "city": "Bucuresti",
                "active": True,
            }
        )
        cc_id = self.db.create_cost_center(code="CC-ORTHO", name="Ortopedie")

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        old_invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="FF",
            invoice_number="001",
            subtotal=100,
            tax_amount=19,
            total_amount=None,
            issued_at=yesterday,
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="old invoice",
            partner_id=partner_id,
            cost_center_id=cc_id,
            user_id=None,
        )
        self.assertGreater(old_invoice_id, 0)
        self.db.update_case_invoice_status(old_invoice_id, "cancelled")

        fresh_invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="FF",
            invoice_number="002",
            subtotal=200,
            tax_amount=38,
            total_amount=None,
            issued_at=today,
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="fresh invoice",
            partner_id=partner_id,
            cost_center_id=cc_id,
            user_id=None,
        )
        self.assertGreater(fresh_invoice_id, 0)

        day = datetime.now().strftime("%Y-%m-%d")
        filtered = self.db.list_case_invoices_filtered(
            date_from=day,
            date_to=day,
            status="issued",
            partner_id=partner_id,
            cost_center_id=cc_id,
            location="Ortopedie",
        )
        self.assertEqual(1, len(filtered))
        self.assertEqual(int(fresh_invoice_id), int(filtered[0]["id"]))

        self.db.set_setting("ENABLE_HTML_EXPORTS_FINANCIAL", "1")
        out_path = Path(tempfile.gettempdir()) / f"manual1_invoices_{uuid4().hex}.html"
        exported = self.db.export_case_invoices_html(
            out_path,
            date_from=day,
            date_to=day,
            status="issued",
            partner_id=partner_id,
            cost_center_id=cc_id,
            location="Ortopedie",
        )
        self.assertTrue(exported.exists())
        content = exported.read_text(encoding="utf-8")
        self.assertIn("Export facturi caz", content)
        self.assertIn("Platitor Contractual", content)
        self.assertIn("CC-ORTHO", content)
        exported.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

