import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import (
    Database,
    _estimate_drg_icm,
    _normalize_icd10_code,
    _parse_icd10_codes_csv,
    _rule_based_diagnosis_suggestions,
    _serialize_icd10_codes_csv,
)


class PatientDiagnosisIcmDrgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_diag_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except Exception:
            pass

    @staticmethod
    def _patient_payload() -> dict:
        return {
            "first_name": "Ana",
            "last_name": "Popescu",
            "cnp": "",
            "phone": "0712345678",
            "email": "",
            "birth_date": "1975-01-10",
            "address": "",
            "medical_history": "HTA veche",
            "allergies": "",
            "chronic_conditions": "Hipertensiune arteriala, diabet zaharat tip 2",
            "current_medication": "metformin",
            "primary_diagnosis_icd10": "I10",
            "secondary_diagnoses_icd10": "E11,N18",
            "free_diagnosis_text": "boala cronica renala stadiu 3",
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

    def test_icd10_parse_and_serialize(self) -> None:
        self.assertEqual("I10", _normalize_icd10_code("i10"))
        parsed = _parse_icd10_codes_csv("E11, n18 ; I10\nI10")
        self.assertEqual(["E11", "N18", "I10"], parsed)
        self.assertEqual("E11,N18,I10", _serialize_icd10_codes_csv(parsed))

    def test_estimate_drg_icm_requires_primary(self) -> None:
        result = _estimate_drg_icm(primary_code="", secondary_codes=[], birth_date="1980-01-01")
        self.assertFalse(result["ok"])
        self.assertEqual(0.0, float(result["icm_estimated"]))

    def test_estimate_drg_icm_with_complications(self) -> None:
        result = _estimate_drg_icm(
            primary_code="J18",
            secondary_codes=["A41", "N18", "I10"],
            birth_date="1940-03-01",
            free_diagnosis_text="insuficienta respiratorie acuta",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(str(result["drg_code"]).startswith("MDC"))
        self.assertGreater(float(result["icm_estimated"]), 1.2)
        self.assertIn(str(result["severity"]), {"MCC", "CC"})

    def test_rule_based_suggestions(self) -> None:
        rows = _rule_based_diagnosis_suggestions(
            context_sections={
                "history": "Hipertensiune arteriala cunoscuta",
                "chronic": "Diabet zaharat tip 2",
                "medication": "",
                "visits": "dispnee de efort",
                "orders": "",
                "investigations": "creatinina crescuta, egfr scazut",
                "free_diag": "",
            },
            icd10_catalog={"I10": "Hipertensiune", "E11": "Diabet zaharat tip 2", "N18": "Boala cronica renala"},
            existing_codes=[],
            limit=10,
        )
        codes = {str(item.get("code")) for item in rows}
        self.assertIn("I10", codes)
        self.assertIn("E11", codes)
        self.assertIn("N18", codes)

    def test_patient_roundtrip_diagnosis_columns(self) -> None:
        patient_id = self.db.create_patient(self._patient_payload())
        row = self.db.get_patient(patient_id)
        self.assertIsNotNone(row)
        self.assertEqual("I10", str(row["primary_diagnosis_icd10"]))
        self.assertEqual("E11,N18", str(row["secondary_diagnoses_icd10"]))
        self.assertIn("renala", str(row["free_diagnosis_text"]))


if __name__ == "__main__":
    unittest.main()
