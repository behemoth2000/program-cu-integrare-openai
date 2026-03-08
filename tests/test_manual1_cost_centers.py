import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class Manual1CostCentersTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual1_cost_{uuid4().hex}.db"
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
                "first_name": "Cost",
                "last_name": "Center",
                "cnp": "1900101223344",
                "phone": "",
                "email": "",
                "birth_date": "1990-01-01",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "gender": "M",
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
                "department": "Chirurgie",
                "ward": "B",
                "bed": "9",
                "attending_clinician": "Dr Cost",
                "chief_complaint": "test",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def test_cost_center_hierarchy(self) -> None:
        parent_id = self.db.create_cost_center(code="CC-HQ", name="Headquarters")
        child_id = self.db.create_cost_center(code="CC-CHIR", name="Chirurgie", parent_id=parent_id)
        rows = self.db.list_cost_centers(include_inactive=True)
        child = next((r for r in rows if int(r["id"]) == int(child_id)), None)
        self.assertIsNotNone(child)
        self.assertEqual(int(parent_id), int(child["parent_id"] or 0))
        self.assertEqual("CC-HQ", child["parent_code"])

    def test_enforcement_on_off_for_consumption_and_invoice(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        cc_id = self.db.create_cost_center(code="CC-FIN", name="Financiar")

        self.db.set_setting("ENABLE_COST_CENTER_ENFORCEMENT", "1")
        with self.assertRaisesRegex(ValueError, "Centru de cost obligatoriu"):
            self.db.add_case_consumption(
                admission_id=admission_id,
                item_type="material",
                item_name="Test",
                unit="buc",
                quantity=1,
                unit_price=10,
                source="ward_stock",
                notes="",
                recorded_at=now_ts(),
                user_id=None,
            )
        with self.assertRaisesRegex(ValueError, "Centru de cost obligatoriu"):
            self.db.create_case_invoice(
                admission_id=admission_id,
                invoice_type="proforma",
                series="CC",
                invoice_number="001",
                subtotal=10,
                tax_amount=1.9,
                total_amount=None,
                issued_at=now_ts(),
                due_date=datetime.now().strftime("%Y-%m-%d"),
                status="issued",
                notes="",
                user_id=None,
            )

        consumption_id = self.db.add_case_consumption(
            admission_id=admission_id,
            item_type="material",
            item_name="Bandaj",
            unit="buc",
            quantity=1,
            unit_price=10,
            source="ward_stock",
            notes="ok",
            recorded_at=now_ts(),
            cost_center_id=cc_id,
            user_id=None,
        )
        self.assertGreater(consumption_id, 0)
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="CC",
            invoice_number="002",
            subtotal=10,
            tax_amount=1.9,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="ok",
            cost_center_id=cc_id,
            user_id=None,
        )
        self.assertGreater(invoice_id, 0)

        self.db.set_setting("ENABLE_COST_CENTER_ENFORCEMENT", "0")
        invoice2_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="CC",
            invoice_number="003",
            subtotal=20,
            tax_amount=3.8,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="fara enforcement",
            user_id=None,
        )
        self.assertGreater(invoice2_id, 0)

    def test_document_profile_can_require_cost_center(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        cc_id = self.db.create_cost_center(code="CC-PROF", name="Profil")
        self.db.set_setting("ENABLE_COST_CENTER_ENFORCEMENT", "0")
        self.db.set_document_type_profile(document_type="case_invoice", require_cost_center=True)

        with self.assertRaisesRegex(ValueError, "Centru de cost obligatoriu"):
            self.db.create_case_invoice(
                admission_id=admission_id,
                invoice_type="proforma",
                series="PF",
                invoice_number="001",
                subtotal=15,
                tax_amount=2.85,
                total_amount=None,
                issued_at=now_ts(),
                due_date=datetime.now().strftime("%Y-%m-%d"),
                status="issued",
                notes="profil",
                user_id=None,
            )

        ok_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PF",
            invoice_number="002",
            subtotal=15,
            tax_amount=2.85,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="profil ok",
            cost_center_id=cc_id,
            user_id=None,
        )
        self.assertGreater(ok_id, 0)


if __name__ == "__main__":
    unittest.main()

