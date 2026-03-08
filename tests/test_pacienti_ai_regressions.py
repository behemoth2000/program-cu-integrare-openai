import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class PacientiAIRegressionsTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_regression_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_legacy_password_hash_is_upgraded_on_login(self) -> None:
        self.assertIsNotNone(self.db.authenticate_user("admin", "Admin!234"))

        with self.db._connect() as conn:
            legacy_hash = hashlib.sha256("password".encode("utf-8")).hexdigest()
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (legacy_hash, "admin"),
            )
            conn.commit()

        self.assertIsNotNone(self.db.authenticate_user("admin", "password"))

        with self.db._connect() as conn:
            upgraded_hash = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()[0]

        self.assertTrue(upgraded_hash.startswith("pbkdf2_sha256$"))

    def test_create_patient_inserts_record(self) -> None:
        patient_payload = {
            "first_name": "Ion",
            "last_name": "Pop",
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
        self.assertGreater(patient_id, 0)

    def test_urgent_orders_kpi_respects_department_filter(self) -> None:
        patient_payload = {
            "first_name": "Ana",
            "last_name": "Ionescu",
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

        admission_id = self.db.create_admission(
            {
                "patient_id": str(patient_id),
                "admission_type": "inpatient",
                "triage_level": "2",
                "department": "Cardio",
                "ward": "A",
                "bed": "1",
                "attending_clinician": "Dr Test",
                "chief_complaint": "test",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        self.db.add_order(patient_id, admission_id, "lab", "urgent", "Ordine test", None)

        kpi_all = self.db.get_dashboard_kpis("")
        kpi_cardio = self.db.get_dashboard_kpis("Cardio")
        kpi_other = self.db.get_dashboard_kpis("Neurologie")

        self.assertGreaterEqual(kpi_all["urgent_orders"], 1)
        self.assertGreaterEqual(kpi_cardio["urgent_orders"], 1)
        self.assertEqual(kpi_other["urgent_orders"], 0)


if __name__ == "__main__":
    unittest.main()
