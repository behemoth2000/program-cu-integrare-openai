import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
    from pacienti_ai_independent.api import create_api_app
    from pacienti_ai_independent.pacienti_ai_app import Database
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]
    create_api_app = None  # type: ignore[assignment]
    Database = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None or create_api_app is None, "fastapi/starlette nu sunt instalate")
class PostgresShadowNonBlockingTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        os.environ.pop("PACIENTI_POSTGRES_DSN", None)
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_shadow_non_blocking_{uuid4().hex}.db"
        self.app = create_api_app(db_path=self.db_path)
        self.client = TestClient(self.app)
        self.db = Database(self.db_path)
        self.admin_headers = {"X-Role": "admin", "X-User-Id": "1"}

    def tearDown(self) -> None:
        self.client.close()
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_sqlite_write_stays_successful_when_shadow_fails(self) -> None:
        self.db.set_settings(
            {
                "API_INTERNAL_POSTGRES_SHADOW_ENABLED": "1",
                "API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES": "0",
                "API_INTERNAL_POSTGRES_SHADOW_BATCH_SIZE": "10",
            }
        )

        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Shadow", "last_name": "Safe"},
            headers={**self.admin_headers, "Idempotency-Key": "shadow-non-blocking-001"},
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json().get("id") or 0)
        self.assertGreater(patient_id, 0)

        patient_row = self.db.get_patient(patient_id)
        self.assertIsNotNone(patient_row)
        self.assertEqual("Shadow", str(patient_row["first_name"]))

        process_res = self.client.post("/api/v1/ops/shadow-sync/process?max_jobs=20", headers=self.admin_headers)
        self.assertEqual(200, process_res.status_code)
        process_body = process_res.json()
        self.assertGreaterEqual(int(process_body.get("processed") or 0), 1)

        # Write-ul principal trebuie sa ramana valid indiferent de esecul shadow.
        patient_row_after = self.db.get_patient(patient_id)
        self.assertIsNotNone(patient_row_after)
        self.assertEqual("Shadow", str(patient_row_after["first_name"]))


if __name__ == "__main__":
    unittest.main()
