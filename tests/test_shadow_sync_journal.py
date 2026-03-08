import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class ShadowSyncJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_shadow_journal_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_enqueue_and_sync_success(self) -> None:
        _ = self.db.enqueue_shadow_write_event(
            action_key="POST /api/v1/patients",
            source="unit_test",
            payload_json='{"k":"v"}',
        )

        def _processor(_row):  # type: ignore[no-untyped-def]
            return True, ""

        summary = self.db.process_shadow_sync_jobs(
            max_jobs=10,
            max_retries=3,
            stop_on_error_rate=0.9,
            processor=_processor,
        )
        self.assertEqual(1, int(summary.get("processed") or 0))
        self.assertEqual(1, int(summary.get("synced") or 0))
        status = self.db.get_shadow_sync_status(lookback_hours=24)
        self.assertEqual(0, int(status.get("backlog_pending") or 0))

    def test_retry_then_fail_after_max_retries(self) -> None:
        journal_id = self.db.enqueue_shadow_write_event(
            action_key="PATCH /api/v1/patients/1",
            source="unit_test",
            payload_json='{"field":"value"}',
        )

        def _fail(_row):  # type: ignore[no-untyped-def]
            return False, "shadow unavailable"

        first = self.db.process_shadow_sync_jobs(
            max_jobs=10,
            max_retries=1,
            stop_on_error_rate=1.0,
            processor=_fail,
        )
        self.assertEqual(1, int(first.get("processed") or 0))
        self.assertEqual(1, int(first.get("retried") or 0))

        with self.db._connect() as conn:
            conn.execute(
                "UPDATE shadow_write_journal SET next_retry_at = ? WHERE id = ?",
                (now_ts(), int(journal_id)),
            )
            conn.commit()

        second = self.db.process_shadow_sync_jobs(
            max_jobs=10,
            max_retries=1,
            stop_on_error_rate=1.0,
            processor=_fail,
        )
        self.assertEqual(1, int(second.get("processed") or 0))
        self.assertEqual(1, int(second.get("failed") or 0))
        rows = self.db.list_shadow_sync_errors(limit=10)
        self.assertEqual(1, len(rows))
        self.assertEqual("failed", str(rows[0]["status"]))

    def test_auto_stop_when_error_rate_threshold_exceeded(self) -> None:
        for idx in range(3):
            _ = self.db.enqueue_shadow_write_event(
                action_key=f"DELETE /api/v1/visits/{idx+1}",
                source="unit_test",
                payload_json='{"visit_id":1}',
            )

        def _always_fail(_row):  # type: ignore[no-untyped-def]
            return False, "permanent shadow failure"

        summary = self.db.process_shadow_sync_jobs(
            max_jobs=3,
            max_retries=0,
            stop_on_error_rate=0.1,
            processor=_always_fail,
        )
        self.assertTrue(bool(summary.get("auto_stopped", False)))
        self.assertEqual(1, int(summary.get("processed") or 0))


if __name__ == "__main__":
    unittest.main()
