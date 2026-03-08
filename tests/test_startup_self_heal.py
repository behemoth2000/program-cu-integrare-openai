import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import _attempt_missing_column_self_heal


class StartupSelfHealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_self_heal_{uuid4().hex}.db"

    def tearDown(self) -> None:
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_adds_missing_external_result_id_column(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE medis_investigations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()
        applied = _attempt_missing_column_self_heal(
            self.db_path,
            sqlite3.OperationalError("no such column: external_result_id"),
        )
        self.assertTrue(applied)
        with sqlite3.connect(self.db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(medis_investigations)").fetchall()}
        self.assertIn("external_result_id", cols)

    def test_ignores_unknown_column(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            conn.commit()
        applied = _attempt_missing_column_self_heal(
            self.db_path,
            sqlite3.OperationalError("no such column: made_up_column"),
        )
        self.assertFalse(applied)


if __name__ == "__main__":
    unittest.main()
