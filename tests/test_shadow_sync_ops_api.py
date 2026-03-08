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
class ShadowSyncOpsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_shadow_ops_{uuid4().hex}.db"
        self.app = create_api_app(db_path=self.db_path)
        self.client = TestClient(self.app)
        self.db = Database(self.db_path)
        self.admin_headers = {"X-Role": "admin", "X-User-Id": "1"}
        self.medic_headers = {"X-Role": "medic", "X-User-Id": "2"}

    def tearDown(self) -> None:
        self.client.close()
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_shadow_sync_status_process_and_errors_endpoints(self) -> None:
        self.db.set_settings(
            {
                "API_INTERNAL_POSTGRES_SHADOW_ENABLED": "1",
                "API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES": "0",
                "API_INTERNAL_POSTGRES_SHADOW_BATCH_SIZE": "10",
                "API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE": "1",
            }
        )
        _ = self.db.enqueue_shadow_write_event(
            action_key="POST /api/v1/patients",
            source="unit_test",
            payload_json='{"demo":1}',
        )

        status_res = self.client.get("/api/v1/ops/shadow-sync/status", headers=self.admin_headers)
        self.assertEqual(200, status_res.status_code)
        status_body = status_res.json()
        self.assertIn("shadow_mode_enabled", status_body)
        self.assertIn("shadow_backlog_pending", status_body)

        process_res = self.client.post("/api/v1/ops/shadow-sync/process?max_jobs=5", headers=self.admin_headers)
        self.assertEqual(200, process_res.status_code)
        process_body = process_res.json()
        self.assertIn("processed", process_body)
        self.assertGreaterEqual(int(process_body.get("processed") or 0), 1)

        errors_res = self.client.get("/api/v1/ops/shadow-sync/errors?limit=20", headers=self.admin_headers)
        self.assertEqual(200, errors_res.status_code)
        errors_body = errors_res.json()
        self.assertIn("items", errors_body)
        self.assertGreaterEqual(len(errors_body.get("items") or []), 1)

    def test_shadow_sync_ops_are_admin_only(self) -> None:
        status_res = self.client.get("/api/v1/ops/shadow-sync/status", headers=self.medic_headers)
        self.assertEqual(403, status_res.status_code)
        process_res = self.client.post("/api/v1/ops/shadow-sync/process", headers=self.medic_headers)
        self.assertEqual(403, process_res.status_code)
        errors_res = self.client.get("/api/v1/ops/shadow-sync/errors", headers=self.medic_headers)
        self.assertEqual(403, errors_res.status_code)


if __name__ == "__main__":
    unittest.main()
