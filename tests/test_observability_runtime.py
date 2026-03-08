import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.observability.logging import _mask_pii
from pacienti_ai_independent.pacienti_ai_app import Database


class ObservabilityRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_obs_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_record_and_list_job_executions(self) -> None:
        first_id = self.db.record_job_execution(
            job_name="integration_queue_tick",
            status="ok",
            duration_ms=125,
            details_json='{"processed":3}',
            correlation_id="corr-1",
        )
        second_id = self.db.record_job_execution(
            job_name="medis_pull_tick",
            status="warning",
            duration_ms=330,
            details_json='{"pulled":10,"applied":7}',
            correlation_id="corr-2",
        )
        self.assertGreater(first_id, 0)
        self.assertGreater(second_id, first_id)

        rows = self.db.list_job_executions(limit=10)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(second_id, int(rows[0]["id"]))

        filtered = self.db.list_job_executions(limit=10, job_name="integration_queue_tick")
        self.assertEqual(1, len(filtered))
        self.assertEqual("integration_queue_tick", filtered[0]["job_name"])

    def test_startup_self_check_includes_enterprise_tables(self) -> None:
        checks = self.db.run_startup_self_check()
        self.assertTrue(bool(checks.get("db_access", False)))
        self.assertTrue(bool(checks.get("required_tables_ok", False)))
        self.assertEqual([], checks.get("missing_tables"))

    def test_mask_pii_filters_sensitive_values(self) -> None:
        text = "Pacient CNP 1980101223344, email test@example.com, telefon 0712345678"
        masked = _mask_pii(text)
        self.assertIn("[CNP_MASKED]", masked)
        self.assertIn("[EMAIL_MASKED]", masked)
        self.assertIn("[PHONE_MASKED]", masked)
        self.assertNotIn("1980101223344", masked)
        self.assertNotIn("test@example.com", masked)
        self.assertNotIn("0712345678", masked)


if __name__ == "__main__":
    unittest.main()
