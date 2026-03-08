import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.api import create_api_app
from pacienti_ai_independent.pacienti_ai_app import Database

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]


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


class SnapshotRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_restore_{uuid4().hex}.db"
        self.db = Database(self.db_path)
        self.patient_id = self.db.create_patient(_patient_payload("Ana", "Popescu"))
        self.sid_initial = self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="create_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        updated = _patient_payload("Maria", "Ionescu")
        updated["phone"] = "0700111222"
        updated["address"] = "Bucuresti, jud. Bucuresti"
        self.db.update_patient(self.patient_id, updated)
        self.sid_updated = self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="update_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except Exception:
            pass

    def test_restore_full_creates_backup_and_post_snapshot_and_audit(self) -> None:
        result = self.db.restore_patient_from_snapshot(
            patient_id=self.patient_id,
            snapshot_id=self.sid_initial,
            restored_by_user_id=1,
            reason="corectie date",
        )
        self.assertTrue(bool(result.get("ok")))
        self.assertEqual(self.patient_id, int(result.get("patient_id") or 0))
        self.assertGreater(int(result.get("backup_snapshot_id") or 0), 0)
        self.assertGreater(int(result.get("post_snapshot_id") or 0), 0)

        row = self.db.get_patient(self.patient_id)
        self.assertIsNotNone(row)
        self.assertEqual("Ana", str(row["first_name"] or ""))
        self.assertEqual("Popescu", str(row["last_name"] or ""))
        self.assertEqual("0712345678", str(row["phone"] or ""))
        self.assertIn("Craiova", str(row["address"] or ""))

        snapshots = self.db.list_patient_snapshots(self.patient_id, limit=20)
        snapshot_ids = {int(r["id"] or 0) for r in snapshots}
        self.assertIn(int(result.get("backup_snapshot_id") or 0), snapshot_ids)
        self.assertIn(int(result.get("post_snapshot_id") or 0), snapshot_ids)

        audits = self.db.list_recent_audit(limit=200)
        restore_entries = [r for r in audits if str(r["action"] or "") == "restore_patient_snapshot"]
        self.assertGreaterEqual(len(restore_entries), 1)
        latest = restore_entries[0]
        details = str(latest["details"] or "")
        self.assertIn("backup_snapshot_id", details)
        self.assertIn("post_snapshot_id", details)
        self.assertIn("reason=", details)

    def test_restore_invalid_snapshot_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.restore_patient_from_snapshot(
                patient_id=self.patient_id,
                snapshot_id=999999,
                restored_by_user_id=1,
                reason="invalid",
            )

    def test_restore_requires_non_empty_reason(self) -> None:
        with self.assertRaises(ValueError):
            self.db.restore_patient_from_snapshot(
                patient_id=self.patient_id,
                snapshot_id=self.sid_initial,
                restored_by_user_id=1,
                reason="   ",
            )

    def test_restore_conflict_when_expected_updated_at_stale(self) -> None:
        row = self.db.get_patient(self.patient_id)
        self.assertIsNotNone(row)
        stale_updated_at = str(row["updated_at"] or "")
        self.assertTrue(stale_updated_at)

        with self.db._connect() as conn:
            conn.execute(
                "UPDATE patients SET updated_at = ? WHERE id = ?",
                ("2099-12-31 23:59:59", self.patient_id),
            )
            conn.commit()

        with self.assertRaises(ValueError) as ctx:
            self.db.restore_patient_from_snapshot(
                patient_id=self.patient_id,
                snapshot_id=self.sid_initial,
                restored_by_user_id=1,
                reason="test conflict",
                expected_updated_at=stale_updated_at,
            )
        self.assertIn("Conflict de concurenta", str(ctx.exception))


@unittest.skipIf(TestClient is None, "fastapi/starlette nu sunt instalate")
class SnapshotRestoreRbacTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_restore_api_{uuid4().hex}.db"
        self.db = Database(self.db_path)
        self.patient_id = self.db.create_patient(_patient_payload("Ana", "Popescu"))
        self.snapshot_id = self.db.create_patient_snapshot(
            patient_id=self.patient_id,
            trigger_action="create_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        self.app = create_api_app(db_path=self.db_path)
        self.client = TestClient(self.app)
        self.admin_headers = {"X-Role": "admin", "X-User-Id": "1"}
        self.medic_headers = {"X-Role": "medic", "X-User-Id": "2"}

    def tearDown(self) -> None:
        self.client.close()
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except Exception:
            pass

    def test_restore_endpoint_admin_only(self) -> None:
        forbidden = self.client.post(
            f"/api/v1/patients/{self.patient_id}/snapshots/{self.snapshot_id}/restore",
            json={"reason": "test"},
            headers=self.medic_headers,
        )
        self.assertEqual(403, forbidden.status_code)

        allowed = self.client.post(
            f"/api/v1/patients/{self.patient_id}/snapshots/{self.snapshot_id}/restore",
            json={"reason": "test admin restore"},
            headers=self.admin_headers,
        )
        self.assertEqual(200, allowed.status_code)
        body = allowed.json()
        self.assertTrue(bool(body.get("ok")))
        self.assertEqual(self.patient_id, int(body.get("patient_id") or 0))

    def test_restore_endpoint_requires_reason(self) -> None:
        bad = self.client.post(
            f"/api/v1/patients/{self.patient_id}/snapshots/{self.snapshot_id}/restore",
            json={"reason": "   "},
            headers=self.admin_headers,
        )
        self.assertEqual(400, bad.status_code)
        self.assertIn("Motiv restore", str(bad.json().get("detail") or ""))

    def test_restore_endpoint_conflict_when_expected_updated_at_stale(self) -> None:
        first_get = self.client.get(f"/api/v1/patients/{self.patient_id}", headers=self.admin_headers)
        self.assertEqual(200, first_get.status_code)
        stale_updated_at = str(first_get.json().get("updated_at") or "")
        self.assertTrue(stale_updated_at)

        with self.db._connect() as conn:
            conn.execute(
                "UPDATE patients SET updated_at = ? WHERE id = ?",
                ("2099-12-31 23:59:59", self.patient_id),
            )
            conn.commit()

        conflict = self.client.post(
            f"/api/v1/patients/{self.patient_id}/snapshots/{self.snapshot_id}/restore",
            json={"reason": "restore stale", "expected_updated_at": stale_updated_at},
            headers=self.admin_headers,
        )
        self.assertEqual(409, conflict.status_code)
        self.assertIn("Conflict de concurenta", str(conflict.json().get("detail") or ""))


if __name__ == "__main__":
    unittest.main()
