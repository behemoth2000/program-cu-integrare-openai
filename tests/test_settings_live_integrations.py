import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, PacientiAIApp


class SettingsLiveIntegrationsTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_live_settings_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_non_secret_live_settings_roundtrip(self) -> None:
        payload = {
            "SIUI_DRG_LIVE_ENABLED": "1",
            "SIUI_DRG_BASE_URL": "https://sandbox.siui",
            "SIUI_DRG_ENDPOINT_SIUI_SUBMIT": "/siui/submit",
            "SIUI_DRG_ENDPOINT_DRG_SUBMIT": "/drg/submit",
            "SIUI_DRG_AUTH_TYPE": "api_key",
            "SIUI_DRG_CLIENT_ID": "siui-client",
            "SIUI_DRG_TIMEOUT_SECONDS": "15",
            "SIUI_DRG_MAX_RETRIES": "2",
            "SIUI_DRG_RETRY_BASE_SECONDS": "1.2",
            "SIUI_DRG_DRY_RUN": "1",
            "MEDIS_LIVE_ENABLED": "1",
            "MEDIS_BASE_URL": "https://sandbox.medis",
            "MEDIS_ENDPOINT_ORDER_SUBMIT": "/orders/submit",
            "MEDIS_ENDPOINT_RESULTS_PULL": "/results/pull",
            "MEDIS_AUTH_TYPE": "bearer",
            "MEDIS_CLIENT_ID": "medis-client",
            "MEDIS_TIMEOUT_SECONDS": "20",
            "MEDIS_MAX_RETRIES": "3",
            "MEDIS_RETRY_BASE_SECONDS": "1.5",
            "MEDIS_PULL_INTERVAL_SECONDS": "120",
            "MEDIS_DRY_RUN": "1",
            "API_INTERNAL_ENABLED": "1",
            "API_INTERNAL_BASE_URL": "http://127.0.0.1:8000",
            "API_INTERNAL_TIMEOUT_SECONDS": "8",
            "API_INTERNAL_DB_BACKEND": "postgres",
            "API_INTERNAL_POSTGRES_CONNECT_TIMEOUT_SECONDS": "3",
            "API_INTERNAL_POSTGRES_SHADOW_ENABLED": "1",
            "API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES": "4",
            "API_INTERNAL_POSTGRES_SHADOW_BATCH_SIZE": "80",
            "API_INTERNAL_POSTGRES_SHADOW_INTERVAL_SECONDS": "45",
            "API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE": "0.4",
            "API_INTERNAL_USE_FOR_PATIENT_READ": "1",
            "API_INTERNAL_USE_FOR_DIAGNOSIS": "1",
            "API_INTERNAL_USE_FOR_PATIENT_WRITE": "0",
        }
        self.db.set_settings(payload)
        saved = self.db.get_settings(list(payload.keys()))
        self.assertEqual(payload, saved)

    def test_setting_raw_prefers_db_over_env_for_non_secret(self) -> None:
        app = PacientiAIApp.__new__(PacientiAIApp)
        app.db = self.db
        os.environ["SIUI_DRG_BASE_URL"] = "https://env.example"
        self.db.set_setting("SIUI_DRG_BASE_URL", "https://db.example")
        value = app._setting_raw("SIUI_DRG_BASE_URL", "SIUI_DRG_BASE_URL", "")
        self.assertEqual("https://db.example", value)

    def test_secret_env_keys_not_required_in_db(self) -> None:
        os.environ["SIUI_DRG_API_KEY"] = "secret-siui"
        os.environ["MEDIS_BEARER_TOKEN"] = "secret-medis"
        settings = self.db.get_all_settings()
        self.assertNotIn("SIUI_DRG_API_KEY", settings)
        self.assertNotIn("MEDIS_BEARER_TOKEN", settings)


if __name__ == "__main__":
    unittest.main()
