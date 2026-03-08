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


class PatientTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_timeline_{uuid4().hex}.db"
        self.db = Database(self.db_path)
        self.patient_id = self.db.create_patient(_patient_payload())
        self.admission_id, _ = self.db.create_admission(
            {
                "patient_id": str(self.patient_id),
                "admission_type": "inpatient",
                "triage_level": "2",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "12",
                "attending_clinician": "Dr Demo",
                "chief_complaint": "Durere",
                "admitted_at": "2026-03-06 09:00:00",
            },
            user_id=1,
        )
        self.db.add_visit(
            self.patient_id,
            "2026-03-06",
            "Control",
            "I10",
            "Tratament",
            "note consultatie",
        )
        self.db.add_order(
            patient_id=self.patient_id,
            admission_id=self.admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma",
            user_id=1,
        )
        self.db.add_vital(
            patient_id=self.patient_id,
            admission_id=self.admission_id,
            payload={
                "recorded_at": "2026-03-06 10:00:00",
                "temperature_c": "38.1",
                "systolic_bp": "120",
                "diastolic_bp": "80",
                "pulse": "90",
                "respiratory_rate": "18",
                "spo2": "98",
                "pain_score": "3",
                "notes": "febra",
            },
            user_id=1,
        )
        self.db.add_ai_message(self.patient_id, "assistant", "Sugestie test")
        self.db.add_audit_log(1, self.patient_id, "timeline_test_action", "admission_id=1")
        self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="manual_test",
            trigger_source="unit_test",
            created_by_user_id=1,
        )

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except Exception:
            pass

    def test_timeline_contains_multi_source_events(self) -> None:
        rows = self.db.list_patient_timeline(self.patient_id, limit=500)
        event_types = {str(row.get("event_type") or "") for row in rows}
        categories = {str(row.get("category") or "") for row in rows}
        self.assertIn("admission", event_types)
        self.assertIn("visit", event_types)
        self.assertIn("medical_order", event_types)
        self.assertIn("vital", event_types)
        self.assertIn("audit", event_types)
        self.assertIn("ai_message", event_types)
        self.assertIn("patient_snapshot", event_types)
        self.assertIn("clinic", categories)
        self.assertIn("snapshot", categories)
        self.assertIn("audit", categories)
        self.assertIn("ai", categories)

    def test_timeline_filters_category_event_type_and_admission(self) -> None:
        snapshot_rows = self.db.list_patient_timeline(self.patient_id, category="snapshot", limit=200)
        self.assertGreaterEqual(len(snapshot_rows), 1)
        self.assertTrue(all(str(row.get("category") or "") == "snapshot" for row in snapshot_rows))

        order_rows = self.db.list_patient_timeline(self.patient_id, event_type="medical_order", limit=200)
        self.assertGreaterEqual(len(order_rows), 1)
        self.assertTrue(all(str(row.get("event_type") or "") == "medical_order" for row in order_rows))

        admission_rows = self.db.list_patient_timeline(self.patient_id, admission_id=self.admission_id, limit=400)
        self.assertGreaterEqual(len(admission_rows), 1)
        self.assertTrue(any(int(row.get("admission_id") or 0) == int(self.admission_id) for row in admission_rows))

    def test_timeline_sorted_descending(self) -> None:
        rows = self.db.list_patient_timeline(self.patient_id, limit=500)
        stamps = [str(row.get("occurred_at") or "") for row in rows]
        self.assertEqual(stamps, sorted(stamps, reverse=True))


if __name__ == "__main__":
    unittest.main()
