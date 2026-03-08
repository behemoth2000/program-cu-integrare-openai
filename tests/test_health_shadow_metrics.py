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
class HealthShadowMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_health_shadow_{uuid4().hex}.db"
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

    def test_health_contains_shadow_metrics(self) -> None:
        self.db.set_setting("API_INTERNAL_POSTGRES_SHADOW_ENABLED", "1")
        _ = self.db.enqueue_shadow_write_event(
            action_key="POST /api/v1/patients",
            source="unit_test",
            payload_json='{"x":1}',
        )

        res = self.client.get("/api/v1/health", headers=self.admin_headers)
        self.assertEqual(200, res.status_code)
        body = res.json()
        checks = body.get("checks") or {}
        self.assertIn("shadow_mode_enabled", checks)
        self.assertIn("shadow_backlog_pending", checks)
        self.assertIn("shadow_last_sync_at", checks)
        self.assertIn("shadow_error_rate_24h", checks)
        self.assertTrue(bool(checks.get("shadow_mode_enabled")))
        self.assertGreaterEqual(int(checks.get("shadow_backlog_pending") or 0), 1)


if __name__ == "__main__":
    unittest.main()
