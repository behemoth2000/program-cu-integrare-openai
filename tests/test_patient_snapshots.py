import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database


def _patient_payload(first_name: str = "Ana", last_name: str = "Popescu") -> dict:
    return {
        "first_name": first_name,
        "last_name": last_name,
        "cnp": "",
        "phone": "0712345678",
        "email": "",
        "birth_date": "1980-01-10",
        "address": "Craiova, jud. Dolj",
        "medical_history": "HTA veche",
        "allergies": "",
        "chronic_conditions": "",
        "current_medication": "",
        "primary_diagnosis_icd10": "I10",
        "secondary_diagnoses_icd10": "",
        "free_diagnosis_text": "",
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


class PatientSnapshotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_snapshots_{uuid4().hex}.db"
        self.db = Database(self.db_path)
        self.patient_id = self.db.create_patient(_patient_payload())

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except Exception:
            pass

    def test_snapshot_versioning_hash_and_diff(self) -> None:
        sid1 = self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="create_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        self.assertGreater(sid1, 0)

        payload2 = _patient_payload(first_name="Anca", last_name="Popescu")
        payload2["phone"] = "0700000000"
        payload2["address"] = "Bucuresti, jud. Bucuresti"
        self.db.update_patient(self.patient_id, payload2)
        sid2 = self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="update_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        self.assertGreater(sid2, sid1)

        rows = self.db.list_patient_snapshots(self.patient_id, limit=20)
        self.assertEqual(2, len(rows))
        self.assertEqual(2, int(rows[0]["version_no"]))
        self.assertEqual(1, int(rows[1]["version_no"]))
        self.assertNotEqual(str(rows[0]["snapshot_hash"] or ""), str(rows[1]["snapshot_hash"] or ""))

        diff = self.db.get_patient_snapshot_diff(self.patient_id, sid2)
        changed = set(diff.get("changed_fields") or [])
        self.assertIn("first_name", changed)
        self.assertIn("phone", changed)
        self.assertIn("address", changed)
        self.assertEqual(sid1, int(diff.get("from_snapshot_id") or 0))
        self.assertEqual(sid2, int(diff.get("to_snapshot_id") or 0))

    def test_snapshot_not_created_for_invalid_patient(self) -> None:
        with self.assertRaises(ValueError):
            self.db.create_patient_snapshot(
                patient_id=0,
                trigger_action="invalid",
                trigger_source="unit_test",
                created_by_user_id=1,
            )


if __name__ == "__main__":
    unittest.main()
