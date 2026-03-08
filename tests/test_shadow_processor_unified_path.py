import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
    from pacienti_ai_independent.api import create_api_app
    from pacienti_ai_independent.pacienti_ai_app import App, Database
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]
    create_api_app = None  # type: ignore[assignment]
    App = None  # type: ignore[assignment]
    Database = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None or create_api_app is None or App is None, "dependinte indisponibile")
class ShadowProcessorUnifiedPathTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_shadow_unified_{uuid4().hex}.db"
        self.db = Database(self.db_path)
        self.app = create_api_app(db_path=self.db_path)
        self.client = TestClient(self.app)
        self.admin_headers = {"X-Role": "admin", "X-User-Id": "1"}

    def tearDown(self) -> None:
        self.client.close()
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_api_shadow_process_uses_shared_backend_helper(self) -> None:
        self.db.set_setting("API_INTERNAL_POSTGRES_SHADOW_ENABLED", "1")
        fake_summary = {
            "processed": 1,
            "synced": 1,
            "retried": 0,
            "failed": 0,
            "auto_stopped": False,
            "pending_after": 0,
            "error_rate_24h": 0.0,
            "last_error": "",
        }
        with patch("pacienti_ai_independent.api.app.process_shadow_sync_with_backend", return_value=dict(fake_summary)) as mocked:
            res = self.client.post("/api/v1/ops/shadow-sync/process?max_jobs=3", headers=self.admin_headers)
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertEqual(1, int(body.get("processed") or 0))
        self.assertTrue(bool(body.get("shadow_mode_enabled")))
        self.assertEqual(1, mocked.call_count)

    def test_desktop_shadow_process_uses_shared_backend_helper(self) -> None:
        class _Logger:
            def warning(self, *_args, **_kwargs) -> None:
                return

        fake_self = SimpleNamespace(
            _require_role=lambda *_args, **_kwargs: True,
            _api_internal_ready_for_ops_read=lambda: False,
            _build_shadow_backend=lambda: object(),
            db=self.db,
            api_internal_postgres_shadow_enabled=True,
            api_internal_postgres_shadow_batch_size=10,
            api_internal_postgres_shadow_max_retries=3,
            api_internal_postgres_shadow_stop_on_error_rate=0.5,
            api_internal_postgres_connect_timeout_seconds=2,
            enterprise_logger=_Logger(),
            _audit=lambda *_args, **_kwargs: None,
            _audit_details_from_pairs=lambda *_pairs: {},
        )

        fake_summary = {
            "processed": 2,
            "synced": 1,
            "retried": 1,
            "failed": 0,
            "auto_stopped": False,
            "pending_after": 0,
            "error_rate_24h": 0.0,
            "last_error": "",
        }
        with patch(
            "pacienti_ai_independent.pacienti_ai_app.process_shadow_sync_with_backend",
            return_value=dict(fake_summary),
        ) as mocked:
            summary = App.process_shadow_sync_now(
                fake_self,
                show_feedback=False,
                source="auto_tick",
                enforce_role=False,
            )
        self.assertEqual(2, int(summary.get("processed") or 0))
        self.assertEqual(1, mocked.call_count)


if __name__ == "__main__":
    unittest.main()
