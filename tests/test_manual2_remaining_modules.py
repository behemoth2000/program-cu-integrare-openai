import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class Manual2RemainingModulesTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual2_{uuid4().hex}.db"
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
            "first_name": "Mara",
            "last_name": "Stan",
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
        patient_id = self.db.create_patient(patient_payload)
        admission_id, _completed_booking = self.db.create_admission(
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

    def test_offer_contract_create_and_status_update(self) -> None:
        patient_id, admission_id = self._create_patient_and_admission()
        offer_id = self.db.create_offer_contract(
            patient_id=patient_id,
            admission_id=admission_id,
            doc_type="offer",
            package_name="Pachet ortopedic",
            accommodation_type="vip",
            base_price=1200.0,
            discount_amount=200.0,
            final_price=None,
            status="draft",
            notes="Oferta initiala",
            user_id=None,
        )
        self.assertGreater(offer_id, 0)

        rows = self.db.list_offer_contracts(admission_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "draft")
        self.assertEqual(float(rows[0]["final_price"]), 1000.0)

        self.db.update_offer_contract_status(offer_id, "signed")
        rows_after = self.db.list_offer_contracts(admission_id)
        self.assertEqual(rows_after[0]["status"], "signed")

    def test_medical_leave_create_and_cancel(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        leave_id = self.db.create_medical_leave(
            admission_id=admission_id,
            series="CM",
            leave_number="0001",
            issued_at=now_ts(),
            start_date="2026-03-01",
            end_date="2026-03-05",
            diagnosis_code="M16",
            notes="Concediu post-operator",
            user_id=None,
        )
        self.assertGreater(leave_id, 0)

        leaves = self.db.list_medical_leaves(admission_id)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(int(leaves[0]["days_count"]), 5)
        self.assertEqual(leaves[0]["status"], "issued")

        self.db.cancel_medical_leave(leave_id)
        leaves_after = self.db.list_medical_leaves(admission_id)
        self.assertEqual(leaves_after[0]["status"], "cancelled")

    def test_case_consumption_and_financial_snapshot(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        consumption_id = self.db.add_case_consumption(
            admission_id=admission_id,
            item_type="material",
            item_name="Set pansament",
            unit="set",
            quantity=2.0,
            unit_price=15.0,
            source="pharmacy",
            notes="Consum sala",
            recorded_at=now_ts(),
            user_id=None,
        )
        self.assertGreater(consumption_id, 0)

        rows = self.db.list_case_consumptions(admission_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["total_price"]), 30.0)

        self.db.update_case_consumption_status(consumption_id, "sent_pharmacy")
        rows_after = self.db.list_case_consumptions(admission_id)
        self.assertEqual(rows_after[0]["status"], "sent_pharmacy")

        self.db.create_billing_record(
            admission_id=admission_id,
            record_type="partial",
            amount=10.0,
            issued_at=now_ts(),
            notes="Avans",
            user_id=None,
        )
        snapshot = self.db.get_case_financial_snapshot(admission_id)
        self.assertAlmostEqual(snapshot["consumption_total"], 30.0)
        self.assertAlmostEqual(snapshot["partial_total"], 10.0)
        self.assertAlmostEqual(snapshot["final_total"], 0.0)
        self.assertAlmostEqual(snapshot["remaining_to_cover"], 20.0)


if __name__ == "__main__":
    unittest.main()
