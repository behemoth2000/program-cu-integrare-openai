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
class IntegrationDryRunOpsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_dry_run_ops_{uuid4().hex}.db"
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

    def test_integration_dry_run_logs_endpoint_returns_normalized_payload(self) -> None:
        _ = self.db.log_integration_dry_run(
            provider="siui_drg",
            operation="submit_siui",
            endpoint="https://sandbox/siui",
            request_payload='{"demo":1}',
            response_payload='{"ok":true}',
            http_code=200,
            latency_ms=11,
            ok=True,
            error_text="",
            correlation_id="corr-siui-1",
            user_id=1,
        )
        _ = self.db.log_integration_dry_run(
            provider="medis",
            operation="submit_order",
            endpoint="https://sandbox/medis",
            request_payload='{"demo":2}',
            response_payload='{"ok":true}',
            http_code=202,
            latency_ms=19,
            ok=True,
            error_text="",
            correlation_id="corr-medis-2",
            user_id=1,
        )

        res = self.client.get(
            "/api/v1/ops/integration-dry-run-logs?limit=10&provider=medis&operation=submit_order",
            headers=self.admin_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        items = body.get("items") or []
        self.assertEqual(1, len(items))
        item = dict(items[0])
        self.assertEqual("medis", str(item.get("provider") or ""))
        self.assertEqual("submit_order", str(item.get("operation") or ""))
        self.assertTrue(bool(item.get("dry_run")))
        self.assertIn("http_code", item)
        self.assertIn("latency_ms", item)
        self.assertIn("error", item)
        self.assertIn("created_at", item)
        self.assertIn("correlation_id", item)

    def test_integration_dry_run_logs_endpoint_is_admin_only(self) -> None:
        res = self.client.get("/api/v1/ops/integration-dry-run-logs", headers=self.medic_headers)
        self.assertEqual(403, res.status_code)


if __name__ == "__main__":
    unittest.main()
