from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import sys
import hashlib
import hmac
import secrets
import traceback
import textwrap
import csv
import json
import smtplib
import zipfile
from datetime import date, datetime, timedelta
import importlib
from pathlib import Path

STATUS_HISTORY_LIMIT = 5
STATUS_SECTION_SEPARATOR = "---"
STATUS_HEADER_STATIC_LINES: Tuple[str, ...] = (
    "Format: Status Handoff FO v1",
    "StatusSchema: handoff_status_v1",
    "StatusFieldsVersion: 1",
    "StatusPayloadType: text/plain",
    "StatusEncoding: utf-8",
    "StatusDelimiter: \\n",
    "StatusEOL: LF",
    "StatusLinePrefix: none",
    "StatusLineNumbering: mixed",
    "StatusHistoryNumbering: decimal_1_based",
    "StatusSectionSeparator: ---",
    "StatusFooterFields: StatusLineCount,StatusChecksum",
    "StatusLegacyCompatible: 1",
    "StatusContractComplete: 1",
    "App: PacientiAIIndependent",
    "Environment: desktop",
    "BuildChannel: recovered",
    "Locale: ro-RO",
    f"Timezone: {APP_TIMEZONE}",
    "Sursa: Handoff FO",
)
HANDOFF_STATUS_AUDIT_BASE_ACTIONS: Tuple[str, ...] = (
    "copy_handoff_status_to_clipboard",
    "copy_handoff_status_as_json",
    "export_handoff_status_json_file",
    "show_and_copy_handoff_status_json",
    "show_and_copy_handoff_status",
)
HANDOFF_STATUS_AUDIT_MODE_SUFFIX: Dict[str, str] = {
    "all": "",
    "minimal": "_minimal",
    "all_in": "_all_in",
}
HANDOFF_STATUS_EXPORT_SOURCES: Tuple[str, ...] = (
    "audit_tab_csv",
    "audit_tab_json",
)
HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT = 5000


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_iso_date(value: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def normalize_role(role: str) -> str:
    allowed = {"admin", "medic", "asistent", "receptie"}
    value = (role or "").strip().lower()
    return value if value in allowed else "receptie"


def hash_password(plain_text: str) -> str:
    iterations = 210_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain_text.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(plain_text: str, stored_hash: str) -> bool:
    raw = (stored_hash or "").strip()
    if raw and "$" not in raw:
        legacy = hashlib.sha256(plain_text.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, raw)

    try:
        algo, iters_s, salt_hex, digest_hex = raw.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", plain_text.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


class CompatRow(dict):
    def __init__(self, columns: List[str], values: Tuple[Any, ...]) -> None:
        super().__init__(zip(columns, values))
        self._values = tuple(values)
        self._casefold_map = {str(col).lower(): str(col) for col in columns}

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        if isinstance(key, str):
            actual = self._casefold_map.get(key.lower(), key)
            return dict.__getitem__(self, actual)
        return dict.__getitem__(self, key)

    def get(self, key: Any, default: Any = None) -> Any:
        if isinstance(key, int):
            try:
                return self._values[key]
            except Exception:
                return default
        if isinstance(key, str):
            actual = self._casefold_map.get(key.lower())
            if actual is None:
                return default
            return dict.get(self, actual, default)
        return dict.get(self, key, default)


def _compat_row_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> CompatRow:
    columns = [str(col[0]) for col in (cursor.description or [])]
    return CompatRow(columns, row)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = _compat_row_factory
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    cnp TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    birth_date TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL DEFAULT '',
                    medical_history TEXT NOT NULL DEFAULT '',
                    allergies TEXT NOT NULL DEFAULT '',
                    chronic_conditions TEXT NOT NULL DEFAULT '',
                    current_medication TEXT NOT NULL DEFAULT '',
                    gender TEXT NOT NULL DEFAULT '',
                    occupation TEXT NOT NULL DEFAULT '',
                    insurance_provider TEXT NOT NULL DEFAULT '',
                    insurance_id TEXT NOT NULL DEFAULT '',
                    emergency_contact_name TEXT NOT NULL DEFAULT '',
                    emergency_contact_phone TEXT NOT NULL DEFAULT '',
                    blood_type TEXT NOT NULL DEFAULT '',
                    height_cm TEXT NOT NULL DEFAULT '',
                    weight_kg TEXT NOT NULL DEFAULT '',
                    surgeries TEXT NOT NULL DEFAULT '',
                    family_history TEXT NOT NULL DEFAULT '',
                    lifestyle_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    visit_date TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    diagnosis TEXT NOT NULL DEFAULT '',
                    treatment TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    mrn TEXT NOT NULL UNIQUE,
                    admission_type TEXT NOT NULL DEFAULT 'inpatient',
                    triage_level INTEGER NOT NULL DEFAULT 3,
                    department TEXT NOT NULL DEFAULT '',
                    ward TEXT NOT NULL DEFAULT '',
                    bed TEXT NOT NULL DEFAULT '',
                    attending_clinician TEXT NOT NULL DEFAULT '',
                    chief_complaint TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    admitted_at TEXT NOT NULL,
                    discharged_at TEXT NOT NULL DEFAULT '',
                    discharge_summary TEXT NOT NULL DEFAULT '',
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS orders_medical (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    admission_id INTEGER REFERENCES admissions(id) ON DELETE SET NULL,
                    order_type TEXT NOT NULL DEFAULT 'lab',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    order_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ordered',
                    ordered_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT '',
                    ordered_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS vitals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    admission_id INTEGER REFERENCES admissions(id) ON DELETE SET NULL,
                    recorded_at TEXT NOT NULL,
                    temperature_c TEXT NOT NULL DEFAULT '',
                    systolic_bp TEXT NOT NULL DEFAULT '',
                    diastolic_bp TEXT NOT NULL DEFAULT '',
                    pulse TEXT NOT NULL DEFAULT '',
                    respiratory_rate TEXT NOT NULL DEFAULT '',
                    spo2 TEXT NOT NULL DEFAULT '',
                    pain_score TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    recorded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    patient_id INTEGER REFERENCES patients(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS login_security (
                    username TEXT PRIMARY KEY,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vital_alert_ack (
                    vital_id INTEGER PRIMARY KEY REFERENCES vitals(id) ON DELETE CASCADE,
                    acknowledged_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    acknowledged_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS care_bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    booking_type TEXT NOT NULL DEFAULT 'admission',
                    department TEXT NOT NULL DEFAULT '',
                    ward TEXT NOT NULL DEFAULT '',
                    bed TEXT NOT NULL DEFAULT '',
                    operating_room TEXT NOT NULL DEFAULT '',
                    attending_clinician TEXT NOT NULL DEFAULT '',
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admission_transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE,
                    action_type TEXT NOT NULL DEFAULT 'transfer',
                    from_department TEXT NOT NULL DEFAULT '',
                    from_ward TEXT NOT NULL DEFAULT '',
                    from_bed TEXT NOT NULL DEFAULT '',
                    to_department TEXT NOT NULL DEFAULT '',
                    to_ward TEXT NOT NULL DEFAULT '',
                    to_bed TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    transferred_at TEXT NOT NULL,
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS billing_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admission_id INTEGER NOT NULL REFERENCES admissions(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    record_type TEXT NOT NULL DEFAULT 'partial',
                    amount REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'RON',
                    issued_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'issued',
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admission_case_closure (
                    admission_id INTEGER PRIMARY KEY REFERENCES admissions(id) ON DELETE CASCADE,
                    finalized_at TEXT NOT NULL,
                    finalized_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    validation_report TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS admission_diagnoses (
                    admission_id INTEGER PRIMARY KEY REFERENCES admissions(id) ON DELETE CASCADE,
                    referral_diagnosis TEXT NOT NULL DEFAULT '',
                    admission_diagnosis TEXT NOT NULL DEFAULT '',
                    discharge_diagnosis TEXT NOT NULL DEFAULT '',
                    secondary_diagnoses TEXT NOT NULL DEFAULT '',
                    dietary_regimen TEXT NOT NULL DEFAULT '',
                    admission_criteria TEXT NOT NULL DEFAULT '',
                    discharge_criteria TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS watchlist_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_ts TEXT NOT NULL,
                    department TEXT NOT NULL DEFAULT '',
                    admission_id INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL,
                    mrn TEXT NOT NULL DEFAULT '',
                    score INTEGER NOT NULL DEFAULT 0,
                    score_breakdown TEXT NOT NULL DEFAULT '',
                    signals TEXT NOT NULL DEFAULT '',
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_patients_last_first
                    ON patients(last_name, first_name);
                CREATE INDEX IF NOT EXISTS idx_visits_patient_date
                    ON visits(patient_id, visit_date DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_messages_patient_created
                    ON ai_messages(patient_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_admissions_patient_status
                    ON admissions(patient_id, status, admitted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_orders_patient_status
                    ON orders_medical(patient_id, status, ordered_at DESC);
                CREATE INDEX IF NOT EXISTS idx_vitals_patient_recorded
                    ON vitals(patient_id, recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_vital_alert_ack_time
                    ON vital_alert_ack(acknowledged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_care_bookings_type_window
                    ON care_bookings(booking_type, status, starts_at, ends_at);
                CREATE INDEX IF NOT EXISTS idx_admission_transfers_admission_time
                    ON admission_transfers(admission_id, transferred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_billing_records_admission_type
                    ON billing_records(admission_id, record_type, issued_at DESC);
                CREATE INDEX IF NOT EXISTS idx_admission_case_closure_time
                    ON admission_case_closure(finalized_at DESC);
                CREATE INDEX IF NOT EXISTS idx_admission_diagnoses_update
                    ON admission_diagnoses(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_watchlist_snapshots_dept_time
                    ON watchlist_snapshots(department, snapshot_ts DESC);
                CREATE INDEX IF NOT EXISTS idx_watchlist_snapshots_admission_time
                    ON watchlist_snapshots(admission_id, snapshot_ts DESC);
                """
            )
            self._ensure_patient_columns(conn)
            self._ensure_admission_diagnoses_columns(conn)
            self._ensure_default_users(conn)
            conn.commit()

    def _ensure_patient_columns(self, conn: sqlite3.Connection) -> None:
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(patients)").fetchall()}
        for col_name, col_def in PATIENT_EXTRA_COLUMNS.items():
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE patients ADD COLUMN {col_name} {col_def}")

    def _ensure_admission_diagnoses_columns(self, conn: sqlite3.Connection) -> None:
        existing_tables = {
            str(row[0]).strip().lower()
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "admission_diagnoses" not in existing_tables:
            return
        existing_cols = {str(row[1]).strip().lower() for row in conn.execute("PRAGMA table_info(admission_diagnoses)").fetchall()}
        if "dietary_regimen" not in existing_cols:
            conn.execute("ALTER TABLE admission_diagnoses ADD COLUMN dietary_regimen TEXT NOT NULL DEFAULT ''")
        if "admission_criteria" not in existing_cols:
            conn.execute("ALTER TABLE admission_diagnoses ADD COLUMN admission_criteria TEXT NOT NULL DEFAULT ''")
        if "discharge_criteria" not in existing_cols:
            conn.execute("ALTER TABLE admission_diagnoses ADD COLUMN discharge_criteria TEXT NOT NULL DEFAULT ''")

    def _ensure_default_users(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(1) FROM users").fetchone()[0]
        if count > 0:
            return
        created = now_ts()
        seed_defs = [
            ("admin", "admin", "Administrator"),
            ("medic", "medic", "Medic"),
            ("asistent", "asistent", "Asistent"),
            ("receptie", "receptie", "Receptie"),
        ]
        generated_lines: List[str] = []
        seed_users = []
        for username, role, display_name in seed_defs:
            env_key = f"PACIENTI_SEED_PASS_{username.upper()}"
            password = (os.getenv(env_key) or "").strip()
            if not password:
                password = secrets.token_urlsafe(10)
                generated_lines.append(f"{username}:{password}")
            seed_users.append((username, hash_password(password), role, display_name))
        conn.executemany(
            """
            INSERT INTO users (username, password_hash, role, display_name, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            [(u, p, r, d, created) for (u, p, r, d) in seed_users],
        )
        if generated_lines:
            cred_path = APP_DIR / "initial_credentials.txt"
            try:
                cred_path.write_text(
                    "Credentiale initiale generate automat (schimba parolele dupa primul login):\n"
                    + "\n".join(generated_lines)
                    + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

    def authenticate_user(self, username: str, password: str) -> Optional[sqlite3.Row]:
        uname = username.strip().lower()
        if not uname or not password:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, role, display_name, password_hash
                FROM users
                WHERE lower(username) = lower(?)
                  AND active = 1
                """,
                (uname,),
            ).fetchone()
            if not row:
                return None
            if not verify_password(password, row["password_hash"]):
                return None

            if "$" not in (row["password_hash"] or ""):
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), row["id"]),
                )
                conn.commit()
            return row

    def get_login_lock_remaining_seconds(self, username: str) -> int:
        uname = (username or "").strip().lower()
        if not uname:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT locked_until FROM login_security WHERE username = ?",
                (uname,),
            ).fetchone()
            if not row:
                return 0
            locked_until = (row["locked_until"] or "").strip()
            if not locked_until:
                return 0
            try:
                lock_dt = datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                conn.execute(
                    "UPDATE login_security SET failed_count = 0, locked_until = '', updated_at = ? WHERE username = ?",
                    (now_ts(), uname),
                )
                conn.commit()
                return 0
            now_dt = datetime.now()
            if lock_dt <= now_dt:
                conn.execute(
                    "UPDATE login_security SET failed_count = 0, locked_until = '', updated_at = ? WHERE username = ?",
                    (now_ts(), uname),
                )
                conn.commit()
                return 0
            return max(1, int((lock_dt - now_dt).total_seconds()))

    def get_login_failed_count(self, username: str) -> int:
        uname = (username or "").strip().lower()
        if not uname:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT failed_count FROM login_security WHERE username = ?",
                (uname,),
            ).fetchone()
            if not row:
                return 0
            return int(row["failed_count"] or 0)

    def register_login_failure(self, username: str, max_attempts: int = 5, lock_minutes: int = 10) -> None:
        uname = (username or "").strip().lower()
        if not uname:
            return
        max_attempts = max(1, int(max_attempts))
        lock_minutes = max(1, int(lock_minutes))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT failed_count FROM login_security WHERE username = ?",
                (uname,),
            ).fetchone()
            failed = int(row["failed_count"] or 0) + 1 if row else 1
            locked_until = ""
            if failed >= max_attempts:
                locked_until = (datetime.now() + timedelta(minutes=lock_minutes)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO login_security (username, failed_count, locked_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    failed_count = excluded.failed_count,
                    locked_until = excluded.locked_until,
                    updated_at = excluded.updated_at
                """,
                (uname, failed, locked_until, now_ts()),
            )
            conn.commit()

    def clear_login_failures(self, username: str) -> None:
        uname = (username or "").strip().lower()
        if not uname:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM login_security WHERE username = ?", (uname,))
            conn.commit()

    def create_backup_file(self, backup_path: Path) -> Path:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        source_conn = self._connect()
        target_conn = sqlite3.connect(str(backup_path))
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()
        return backup_path

    def restore_from_backup_file(self, backup_path: Path) -> None:
        if not backup_path.exists():
            raise FileNotFoundError(f"Fisier backup inexistent: {backup_path}")
        source_conn = sqlite3.connect(str(backup_path))
        target_conn = self._connect()
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
            source_conn.close()

    def acknowledge_vital_alert(self, vital_id: int, user_id: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vital_alert_ack (vital_id, acknowledged_by_user_id, acknowledged_at)
                VALUES (?, ?, ?)
                ON CONFLICT(vital_id) DO UPDATE SET
                    acknowledged_by_user_id = excluded.acknowledged_by_user_id,
                    acknowledged_at = excluded.acknowledged_at
                """,
                (int(vital_id), user_id, now_ts()),
            )
            conn.commit()

    def is_vital_alert_acknowledged(self, vital_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM vital_alert_ack WHERE vital_id = ?",
                (int(vital_id),),
            ).fetchone()
            return row is not None

    def get_acknowledged_vital_ids(self, vital_ids: List[int]) -> set[int]:
        ids = [int(v) for v in vital_ids if int(v) > 0]
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT vital_id FROM vital_alert_ack WHERE vital_id IN ({placeholders})",
                ids,
            ).fetchall()
        return {int(r["vital_id"]) for r in rows}

    def save_watchlist_snapshot(
        self,
        *,
        department: str,
        snapshot_ts: str,
        rows: List[Dict[str, Any]],
        user_id: Optional[int],
    ) -> int:
        dept = (department or "").strip()
        when = (snapshot_ts or "").strip() or now_ts()
        self._parse_dt_text(when)
        payload: List[Tuple[Any, ...]] = []
        for row in rows:
            admission_id = int(row.get("admission_id") or 0)
            patient_id = int(row.get("patient_id") or 0)
            if admission_id <= 0 or patient_id <= 0:
                continue
            payload.append(
                (
                    when,
                    dept,
                    admission_id,
                    patient_id,
                    str(row.get("mrn") or ""),
                    int(row.get("score") or 0),
                    str(row.get("score_breakdown") or ""),
                    str(row.get("signals") or ""),
                    user_id,
                )
            )
        if not payload:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO watchlist_snapshots (
                    snapshot_ts, department, admission_id, patient_id, mrn,
                    score, score_breakdown, signals, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            conn.commit()
        return len(payload)

    def get_previous_watchlist_scores(self, *, department: str, before_ts: str) -> Dict[int, int]:
        dept = (department or "").strip()
        when = (before_ts or "").strip() or now_ts()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ws.admission_id, ws.score
                FROM watchlist_snapshots ws
                JOIN (
                    SELECT admission_id, MAX(snapshot_ts) AS max_ts
                    FROM watchlist_snapshots
                    WHERE department = ?
                      AND snapshot_ts < ?
                    GROUP BY admission_id
                ) latest
                  ON latest.admission_id = ws.admission_id
                 AND latest.max_ts = ws.snapshot_ts
                WHERE ws.department = ?
                """,
                (dept, when, dept),
            ).fetchall()
        return {int(row["admission_id"]): int(row["score"] or 0) for row in rows}

    def list_watchlist_snapshot_runs(self, *, department: str, limit: int = 20) -> List[sqlite3.Row]:
        dept = (department or "").strip()
        lim = max(1, int(limit))
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT
                    snapshot_ts,
                    COUNT(*) AS rows_count,
                    MAX(score) AS max_score,
                    ROUND(AVG(score), 1) AS avg_score
                FROM watchlist_snapshots
                WHERE department = ?
                GROUP BY snapshot_ts
                ORDER BY snapshot_ts DESC
                LIMIT ?
                """,
                (dept, lim),
            ).fetchall()

    def get_watchlist_trend_top(self, *, department: str, hours: int = 24, limit: int = 10) -> List[sqlite3.Row]:
        dept = (department or "").strip()
        hrs = max(1, min(24 * 30, int(hours)))
        lim = max(1, int(limit))
        to_ts = now_ts()
        from_ts = (datetime.now() - timedelta(hours=hrs)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            return conn.execute(
                """
                WITH interval_data AS (
                    SELECT snapshot_ts, admission_id, patient_id, mrn, score
                    FROM watchlist_snapshots
                    WHERE department = ?
                      AND snapshot_ts >= ?
                      AND snapshot_ts <= ?
                ),
                first_last AS (
                    SELECT
                        admission_id,
                        MIN(snapshot_ts) AS first_ts,
                        MAX(snapshot_ts) AS last_ts
                    FROM interval_data
                    GROUP BY admission_id
                    HAVING MIN(snapshot_ts) <> MAX(snapshot_ts)
                )
                SELECT
                    fl.admission_id,
                    latest.patient_id,
                    latest.mrn,
                    COALESCE(p.last_name, '') AS last_name,
                    COALESCE(p.first_name, '') AS first_name,
                    earliest.score AS score_then,
                    latest.score AS score_now,
                    (latest.score - earliest.score) AS delta,
                    fl.first_ts,
                    fl.last_ts
                FROM first_last fl
                JOIN interval_data earliest
                  ON earliest.admission_id = fl.admission_id
                 AND earliest.snapshot_ts = fl.first_ts
                JOIN interval_data latest
                  ON latest.admission_id = fl.admission_id
                 AND latest.snapshot_ts = fl.last_ts
                LEFT JOIN patients p ON p.id = latest.patient_id
                ORDER BY delta DESC, score_now DESC, latest.mrn COLLATE NOCASE
                LIMIT ?
                """,
                (dept, from_ts, to_ts, lim),
            ).fetchall()

    def list_users(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, username, role, display_name, active, created_at
                FROM users
                ORDER BY username COLLATE NOCASE
                """
            ).fetchall()

    def create_user(self, username: str, password: str, role: str, display_name: str, active: bool) -> int:
        uname = username.strip().lower()
        if not uname:
            raise ValueError("Utilizator gol.")
        if len(password) < 6:
            raise ValueError("Parola trebuie sa aiba cel putin 6 caractere.")
        role_norm = normalize_role(role)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, role, display_name, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uname,
                    hash_password(password),
                    role_norm,
                    display_name.strip(),
                    1 if active else 0,
                    now_ts(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_setting(self, key: str, default: str = "") -> str:
        clean_key = (key or "").strip()
        if not clean_key:
            return default
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (clean_key,)).fetchone()
            if not row:
                return default
            value = row["value"]
            return str(value) if value is not None else default

    def get_settings(self, keys: List[str]) -> Dict[str, str]:
        key_list = [k.strip() for k in keys if (k or "").strip()]
        if not key_list:
            return {}
        placeholders = ",".join("?" for _ in key_list)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                key_list,
            ).fetchall()
        out: Dict[str, str] = {}
        for row in rows:
            out[str(row["key"])] = str(row["value"] or "")
        return out

    def set_setting(self, key: str, value: Any) -> None:
        clean_key = (key or "").strip()
        if not clean_key:
            return
        text_value = "" if value is None else str(value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (clean_key, text_value, now_ts()),
            )
            conn.commit()

    def set_settings(self, payload: Dict[str, Any]) -> None:
        items = [((k or "").strip(), "" if v is None else str(v)) for k, v in payload.items() if (k or "").strip()]
        if not items:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [(k, v, now_ts()) for (k, v) in items],
            )
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings ORDER BY key COLLATE NOCASE").fetchall()
        out: Dict[str, str] = {}
        for row in rows:
            out[str(row["key"])] = str(row["value"] or "")
        return out

    def update_user(self, user_id: int, role: str, display_name: str, active: bool) -> None:
        role_norm = normalize_role(role)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET role = ?, display_name = ?, active = ?
                WHERE id = ?
                """,
                (role_norm, display_name.strip(), 1 if active else 0, user_id),
            )
            conn.commit()

    def set_user_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < 6:
            raise ValueError("Parola trebuie sa aiba cel putin 6 caractere.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), user_id),
            )
            conn.commit()

    def get_user_by_id(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, username, role, display_name, active, created_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()

    def add_audit_log(self, user_id: Optional[int], patient_id: Optional[int], action: str, details: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (user_id, patient_id, action, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, patient_id, action.strip(), details.strip(), now_ts()),
            )
            conn.commit()

    def list_recent_audit(
        self,
        limit: int = 200,
        *,
        username: str = "",
        action: str = "",
        patient_id: Optional[int] = None,
        date_from: str = "",
        date_to: str = "",
    ) -> List[sqlite3.Row]:
        query = """
            SELECT a.id, a.user_id, a.patient_id, a.action, a.details, a.created_at,
                   COALESCE(u.username, '-') AS username,
                   COALESCE(p.last_name || ' ' || p.first_name, '-') AS patient_name
            FROM audit_log a
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN patients p ON p.id = a.patient_id
            WHERE 1=1
        """
        params: List[Any] = []
        if username.strip():
            query += " AND lower(COALESCE(u.username, '')) LIKE lower(?)"
            params.append(f"%{username.strip()}%")
        if action.strip():
            query += " AND lower(a.action) LIKE lower(?)"
            params.append(f"%{action.strip()}%")
        if patient_id is not None and patient_id > 0:
            query += " AND a.patient_id = ?"
            params.append(patient_id)
        if date_from.strip():
            query += " AND a.created_at >= ?"
            params.append(date_from.strip())
        if date_to.strip():
            query += " AND a.created_at <= ?"
            params.append(date_to.strip())
        query += " ORDER BY a.id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def list_patients(self, search: str = "", status_filter: str = "all", status_date: str = "") -> List[sqlite3.Row]:
        day_text = (status_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(day_text, "%Y-%m-%d")
        except Exception:
            day_text = datetime.now().strftime("%Y-%m-%d")

        query = """
            SELECT
                id,
                first_name,
                last_name,
                phone,
                email,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM care_bookings b
                        WHERE b.patient_id = patients.id
                          AND b.booking_type = 'discharge'
                          AND b.status = 'scheduled'
                          AND date(b.starts_at) = date(?)
                    ) THEN 'Programat externare'
                    WHEN EXISTS (
                        SELECT 1
                        FROM admissions a
                        WHERE a.patient_id = patients.id
                          AND a.status = 'active'
                    ) THEN 'Internat'
                    WHEN EXISTS (
                        SELECT 1
                        FROM care_bookings b
                        WHERE b.patient_id = patients.id
                          AND b.booking_type = 'admission'
                          AND b.status = 'scheduled'
                          AND date(b.starts_at) = date(?)
                    ) THEN 'Programat internare'
                    WHEN EXISTS (
                        SELECT 1
                        FROM admissions a
                        WHERE a.patient_id = patients.id
                          AND a.status = 'discharged'
                          AND date(COALESCE(a.discharged_at, '')) = date(?)
                          AND NOT EXISTS (
                              SELECT 1
                              FROM billing_records br
                              WHERE br.admission_id = a.id
                                AND br.record_type = 'final'
                                AND br.status = 'issued'
                          )
                    ) THEN 'Externat fara decont'
                    WHEN EXISTS (
                        SELECT 1
                        FROM admissions a
                        WHERE a.patient_id = patients.id
                          AND a.status = 'discharged'
                          AND date(COALESCE(a.discharged_at, '')) = date(?)
                    ) THEN 'Externat'
                    ELSE '-'
                END AS reception_flag
            FROM patients
            WHERE 1=1
        """
        params: List[Any] = [day_text, day_text, day_text, day_text]
        if search:
            query += """
                AND lower(first_name || ' ' || last_name || ' ' || cnp || ' ' || phone || ' ' || email)
                      LIKE lower(?)
            """
            params.append(f"%{search.strip()}%")
        filter_key = (status_filter or "all").strip().lower()
        if filter_key == "scheduled_admission":
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM care_bookings b
                    WHERE b.patient_id = patients.id
                      AND b.booking_type = 'admission'
                      AND b.status = 'scheduled'
                      AND date(b.starts_at) = date(?)
                )
            """
            params.append(day_text)
        elif filter_key == "active_admission":
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM admissions a
                    WHERE a.patient_id = patients.id
                      AND a.status = 'active'
                )
            """
        elif filter_key == "scheduled_discharge":
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM care_bookings b
                    WHERE b.patient_id = patients.id
                      AND b.booking_type = 'discharge'
                      AND b.status = 'scheduled'
                      AND date(b.starts_at) = date(?)
                )
            """
            params.append(day_text)
        elif filter_key == "discharged_no_debrief":
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM admissions a
                    WHERE a.patient_id = patients.id
                      AND a.status = 'discharged'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM billing_records br
                          WHERE br.admission_id = a.id
                            AND br.record_type = 'final'
                            AND br.status = 'issued'
                      )
                )
            """
        elif filter_key == "discharged_on_date":
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM admissions a
                    WHERE a.patient_id = patients.id
                      AND a.status = 'discharged'
                      AND date(COALESCE(a.discharged_at, '')) = date(?)
                )
            """
            params.append(day_text)
        query += " ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, id DESC"
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    @staticmethod
    def _parse_dt_text(value: str) -> datetime:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S")

    def has_active_bed_conflict(self, department: str, ward: str, bed: str, exclude_admission_id: Optional[int] = None) -> bool:
        dept = (department or "").strip()
        wrd = (ward or "").strip()
        bd = (bed or "").strip()
        if not (dept and wrd and bd):
            return False
        with self._connect() as conn:
            if exclude_admission_id:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM admissions
                    WHERE status = 'active'
                      AND lower(department) = lower(?)
                      AND lower(ward) = lower(?)
                      AND lower(bed) = lower(?)
                      AND id <> ?
                    LIMIT 1
                    """,
                    (dept, wrd, bd, int(exclude_admission_id)),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM admissions
                    WHERE status = 'active'
                      AND lower(department) = lower(?)
                      AND lower(ward) = lower(?)
                      AND lower(bed) = lower(?)
                    LIMIT 1
                    """,
                    (dept, wrd, bd),
                ).fetchone()
        return row is not None

    def has_care_booking_conflict(
        self,
        *,
        booking_type: str,
        starts_at: str,
        ends_at: str,
        department: str = "",
        ward: str = "",
        bed: str = "",
        operating_room: str = "",
        attending_clinician: str = "",
        exclude_booking_id: Optional[int] = None,
    ) -> Optional[str]:
        btype = (booking_type or "").strip().lower()
        start_dt = self._parse_dt_text(starts_at)
        end_dt = self._parse_dt_text(ends_at)
        if end_dt <= start_dt:
            raise ValueError("Interval invalid: sfarsitul trebuie sa fie dupa inceput.")

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, booking_type, department, ward, bed, operating_room, attending_clinician, starts_at, ends_at
                FROM care_bookings
                WHERE status = 'scheduled'
                  AND starts_at < ?
                  AND ends_at > ?
                ORDER BY starts_at ASC, id ASC
                """,
                (end_dt.strftime("%Y-%m-%d %H:%M:%S"), start_dt.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchall()

        dept = (department or "").strip().lower()
        wrd = (ward or "").strip().lower()
        bd = (bed or "").strip().lower()
        room = (operating_room or "").strip().lower()
        clinician = (attending_clinician or "").strip().lower()

        for row in rows:
            if exclude_booking_id and int(row["id"]) == int(exclude_booking_id):
                continue
            same_bed = (
                btype == "admission"
                and dept
                and wrd
                and bd
                and dept == str(row["department"] or "").strip().lower()
                and wrd == str(row["ward"] or "").strip().lower()
                and bd == str(row["bed"] or "").strip().lower()
            )
            same_room = (
                btype == "operation"
                and room
                and room == str(row["operating_room"] or "").strip().lower()
            )
            same_clinician = clinician and clinician == str(row["attending_clinician"] or "").strip().lower()

            if same_bed:
                return "Conflict rezervare: patul este deja ocupat in intervalul ales."
            if same_room:
                return "Conflict rezervare: sala de operatie este ocupata in intervalul ales."
            if same_clinician:
                return "Conflict rezervare: medicul are deja alta programare in intervalul ales."
        return None

    def list_operation_booking_overlaps(
        self,
        *,
        starts_at: str,
        ends_at: str,
        operating_room: str = "",
        attending_clinician: str = "",
        exclude_booking_id: Optional[int] = None,
        limit: int = 5,
    ) -> List[sqlite3.Row]:
        start_dt = self._parse_dt_text(starts_at)
        end_dt = self._parse_dt_text(ends_at)
        if end_dt <= start_dt:
            raise ValueError("Interval invalid: sfarsitul trebuie sa fie dupa inceput.")

        room = (operating_room or "").strip()
        clinician = (attending_clinician or "").strip()
        if not room and not clinician:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.id, b.starts_at, b.ends_at, b.operating_room, b.attending_clinician,
                       p.first_name, p.last_name
                FROM care_bookings b
                JOIN patients p ON p.id = b.patient_id
                WHERE b.booking_type = 'operation'
                  AND b.status = 'scheduled'
                  AND b.starts_at < ?
                  AND b.ends_at > ?
                  AND (
                    (? <> '' AND lower(b.operating_room) = lower(?))
                    OR (? <> '' AND lower(b.attending_clinician) = lower(?))
                  )
                ORDER BY b.starts_at ASC, b.id ASC
                LIMIT ?
                """,
                (
                    end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    room,
                    room,
                    clinician,
                    clinician,
                    max(1, int(limit)),
                ),
            ).fetchall()

        if exclude_booking_id is None:
            return rows
        filtered: List[sqlite3.Row] = []
        for row in rows:
            if int(row["id"]) == int(exclude_booking_id):
                continue
            filtered.append(row)
        return filtered

    def _ward_capacity_limit(self, department: str, ward: str) -> int:
        default_limit = 4
        try:
            default_limit = max(1, int(self.get_setting("CARE_WARD_CAPACITY_DEFAULT", "4")))
        except Exception:
            default_limit = 4

        dept_norm = (department or "").strip().lower()
        ward_norm = (ward or "").strip().lower()
        overrides_raw = (self.get_setting("CARE_WARD_CAPACITY_OVERRIDES", "") or "").strip()
        if overrides_raw and dept_norm and ward_norm:
            chunks = [c.strip() for c in re.split(r"[;\n]+", overrides_raw) if c.strip()]
            for chunk in chunks:
                if "=" not in chunk:
                    continue
                left, right = chunk.split("=", 1)
                left = left.strip()
                right = right.strip()
                if "/" not in left:
                    continue
                d_name, w_name = left.split("/", 1)
                if d_name.strip().lower() != dept_norm or w_name.strip().lower() != ward_norm:
                    continue
                try:
                    return max(1, int(right))
                except Exception:
                    continue

        dept_key = re.sub(r"[^a-z0-9]+", "_", dept_norm).strip("_")
        ward_key = re.sub(r"[^a-z0-9]+", "_", ward_norm).strip("_")
        if dept_key and ward_key:
            legacy_key = f"WARD_CAPACITY__{dept_key}__{ward_key}"
            raw = (self.get_setting(legacy_key, "") or "").strip()
            if raw:
                try:
                    return max(1, int(raw))
                except Exception:
                    pass
        return default_limit

    def _ward_overlap_occupancy(self, department: str, ward: str, starts_at: str, ends_at: str) -> int:
        dept = (department or "").strip()
        wrd = (ward or "").strip()
        if not (dept and wrd):
            return 0

        start_dt = self._parse_dt_text(starts_at)
        end_dt = self._parse_dt_text(ends_at)
        if end_dt <= start_dt:
            return 0

        with self._connect() as conn:
            active_now = conn.execute(
                """
                SELECT COUNT(1)
                FROM admissions
                WHERE status = 'active'
                  AND lower(department) = lower(?)
                  AND lower(ward) = lower(?)
                """,
                (dept, wrd),
            ).fetchone()[0]

            overlap_bookings = conn.execute(
                """
                SELECT COUNT(1)
                FROM care_bookings
                WHERE booking_type = 'admission'
                  AND status = 'scheduled'
                  AND lower(department) = lower(?)
                  AND lower(ward) = lower(?)
                  AND starts_at < ?
                  AND ends_at > ?
                """,
                (dept, wrd, end_dt.strftime("%Y-%m-%d %H:%M:%S"), start_dt.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()[0]
        return int(active_now or 0) + int(overlap_bookings or 0)

    def _has_same_day_discharge_booking(self, patient_id: int, starts_at: str) -> bool:
        if patient_id <= 0:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM care_bookings
                WHERE patient_id = ?
                  AND booking_type = 'discharge'
                  AND status = 'scheduled'
                  AND date(starts_at) = date(?)
                LIMIT 1
                """,
                (int(patient_id), starts_at),
            ).fetchone()
        return row is not None

    def create_care_booking(self, payload: Dict[str, str], user_id: Optional[int]) -> int:
        booking_type = (payload.get("booking_type") or "admission").strip().lower()
        if booking_type not in {"admission", "operation", "discharge"}:
            raise ValueError("Tip programare invalid.")

        starts_at = (payload.get("starts_at") or "").strip()
        ends_at = (payload.get("ends_at") or "").strip()
        department = (payload.get("department") or "").strip()
        ward = (payload.get("ward") or "").strip()
        bed = (payload.get("bed") or "").strip()
        operating_room = (payload.get("operating_room") or "").strip()
        attending_clinician = (payload.get("attending_clinician") or "").strip()

        if booking_type == "admission":
            if not department:
                raise ValueError("Pentru programare de internare, campul Sectie este obligatoriu.")
            if not ward:
                raise ValueError("Pentru programare de internare, campul Salon este obligatoriu.")
        elif booking_type == "operation":
            if not operating_room:
                raise ValueError("Pentru programare de operatie, campul Sala operatie este obligatoriu.")
            if not attending_clinician:
                raise ValueError("Pentru programare de operatie, campul Medic este obligatoriu.")
        elif booking_type == "discharge":
            if not attending_clinician:
                raise ValueError("Pentru programare de externare, campul Medic este obligatoriu.")

        conflict = self.has_care_booking_conflict(
            booking_type=booking_type,
            starts_at=starts_at,
            ends_at=ends_at,
            department=department,
            ward=ward,
            bed=bed,
            operating_room=operating_room,
            attending_clinician=attending_clinician,
        )
        if conflict:
            raise ValueError(conflict)

        patient_id = int(payload["patient_id"])
        if booking_type == "discharge" and self._has_same_day_discharge_booking(patient_id, starts_at):
            raise ValueError("Pacientul are deja o programare de externare in aceeasi zi.")

        if booking_type == "admission":
            if department and ward:
                capacity_limit = self._ward_capacity_limit(department, ward)
                occupancy = self._ward_overlap_occupancy(department, ward, starts_at, ends_at)
                if occupancy >= capacity_limit:
                    raise ValueError(
                        f"Capacitate depasita pentru {department}/{ward}: {occupancy}/{capacity_limit}."
                    )

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO care_bookings (
                    patient_id, booking_type, department, ward, bed, operating_room,
                    attending_clinician, starts_at, ends_at, notes, status,
                    created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
                """,
                (
                    patient_id,
                    booking_type,
                    department,
                    ward,
                    bed,
                    operating_room,
                    attending_clinician,
                    starts_at,
                    ends_at,
                    (payload.get("notes") or "").strip(),
                    user_id,
                    now_ts(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_care_bookings(self, patient_id: Optional[int] = None, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect() as conn:
            if patient_id and patient_id > 0:
                return conn.execute(
                    """
                    SELECT id, patient_id, booking_type, department, ward, bed, operating_room,
                           attending_clinician, starts_at, ends_at, notes, status
                    FROM care_bookings
                    WHERE patient_id = ?
                    ORDER BY starts_at DESC, id DESC
                    LIMIT ?
                    """,
                    (patient_id, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT id, patient_id, booking_type, department, ward, bed, operating_room,
                       attending_clinician, starts_at, ends_at, notes, status
                FROM care_bookings
                ORDER BY starts_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def update_care_booking_status(self, booking_id: int, new_status: str) -> None:
        status = (new_status or "").strip().lower()
        if status not in {"scheduled", "cancelled", "completed"}:
            raise ValueError("Status programare invalid.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE care_bookings SET status = ? WHERE id = ?",
                (status, int(booking_id)),
            )
            conn.commit()

    def get_patient(self, patient_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()

    def create_patient(self, payload: Dict[str, str]) -> int:
        ts = now_ts()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO patients (
                    first_name, last_name, cnp, phone, email, birth_date, address,
                    medical_history, allergies, chronic_conditions, current_medication,
                    gender, occupation, insurance_provider, insurance_id,
                    emergency_contact_name, emergency_contact_phone, blood_type,
                    height_cm, weight_kg, surgeries, family_history, lifestyle_notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["first_name"],
                    payload["last_name"],
                    payload["cnp"],
                    payload["phone"],
                    payload["email"],
                    payload["birth_date"],
                    payload["address"],
                    payload["medical_history"],
                    payload["allergies"],
                    payload["chronic_conditions"],
                    payload["current_medication"],
                    payload["gender"],
                    payload["occupation"],
                    payload["insurance_provider"],
                    payload["insurance_id"],
                    payload["emergency_contact_name"],
                    payload["emergency_contact_phone"],
                    payload["blood_type"],
                    payload["height_cm"],
                    payload["weight_kg"],
                    payload["surgeries"],
                    payload["family_history"],
                    payload["lifestyle_notes"],
                    ts,
                    ts,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_patient(self, patient_id: int, payload: Dict[str, str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE patients
                SET first_name = ?,
                    last_name = ?,
                    cnp = ?,
                    phone = ?,
                    email = ?,
                    birth_date = ?,
                    address = ?,
                    medical_history = ?,
                    allergies = ?,
                    chronic_conditions = ?,
                    current_medication = ?,
                    gender = ?,
                    occupation = ?,
                    insurance_provider = ?,
                    insurance_id = ?,
                    emergency_contact_name = ?,
                    emergency_contact_phone = ?,
                    blood_type = ?,
                    height_cm = ?,
                    weight_kg = ?,
                    surgeries = ?,
                    family_history = ?,
                    lifestyle_notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["first_name"],
                    payload["last_name"],
                    payload["cnp"],
                    payload["phone"],
                    payload["email"],
                    payload["birth_date"],
                    payload["address"],
                    payload["medical_history"],
                    payload["allergies"],
                    payload["chronic_conditions"],
                    payload["current_medication"],
                    payload["gender"],
                    payload["occupation"],
                    payload["insurance_provider"],
                    payload["insurance_id"],
                    payload["emergency_contact_name"],
                    payload["emergency_contact_phone"],
                    payload["blood_type"],
                    payload["height_cm"],
                    payload["weight_kg"],
                    payload["surgeries"],
                    payload["family_history"],
                    payload["lifestyle_notes"],
                    now_ts(),
                    patient_id,
                ),
            )
            conn.commit()

    def delete_patient(self, patient_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
            conn.commit()

    def add_visit(
        self,
        patient_id: int,
        visit_date: str,
        reason: str,
        diagnosis: str,
        treatment: str,
        notes: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO visits (patient_id, visit_date, reason, diagnosis, treatment, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (patient_id, visit_date, reason, diagnosis, treatment, notes, now_ts()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_visits(self, patient_id: int, limit: int = 200) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, visit_date, reason, diagnosis, treatment, notes, created_at
                FROM visits
                WHERE patient_id = ?
                ORDER BY visit_date DESC, id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()

    def delete_visit(self, visit_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))
            conn.commit()

    def _next_mrn(self, conn: sqlite3.Connection) -> str:
        year = datetime.now().strftime("%Y")
        prefix = f"MRN-{year}-"
        current_max = conn.execute(
            """
            SELECT mrn
            FROM admissions
            WHERE mrn LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (f"{prefix}%",),
        ).fetchone()
        seq = 1
        if current_max and current_max["mrn"]:
            mrn_text = str(current_max["mrn"])
            parts = mrn_text.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                seq = int(parts[1]) + 1
        return f"{prefix}{seq:06d}"

    def create_admission(self, payload: Dict[str, str], user_id: Optional[int]) -> Tuple[int, Optional[int]]:
        with self._connect() as conn:
            mrn = self._next_mrn(conn)
            planned_booking = conn.execute(
                """
                SELECT id
                FROM care_bookings
                WHERE patient_id = ?
                  AND booking_type = 'admission'
                  AND status = 'scheduled'
                  AND date(starts_at) = date(?)
                ORDER BY ABS(julianday(starts_at) - julianday(?)) ASC, id DESC
                LIMIT 1
                """,
                (int(payload["patient_id"]), payload["admitted_at"], payload["admitted_at"]),
            ).fetchone()
            cur = conn.execute(
                """
                INSERT INTO admissions (
                    patient_id, mrn, admission_type, triage_level, department, ward, bed,
                    attending_clinician, chief_complaint, status, admitted_at, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    int(payload["patient_id"]),
                    mrn,
                    payload["admission_type"],
                    int(payload["triage_level"]),
                    payload["department"],
                    payload["ward"],
                    payload["bed"],
                    payload["attending_clinician"],
                    payload["chief_complaint"],
                    payload["admitted_at"],
                    user_id,
                ),
            )
            admission_id = int(cur.lastrowid)
            completed_booking_id: Optional[int] = None
            if planned_booking:
                completed_booking_id = int(planned_booking["id"])
                conn.execute(
                    """
                    UPDATE care_bookings
                    SET status = 'completed'
                    WHERE id = ?
                    """,
                    (completed_booking_id,),
                )
            conn.execute(
                """
                INSERT INTO admission_transfers (
                    admission_id, action_type,
                    from_department, from_ward, from_bed,
                    to_department, to_ward, to_bed,
                    notes, transferred_at, created_by_user_id, created_at
                ) VALUES (?, 'admit', '', '', '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admission_id,
                    payload["department"],
                    payload["ward"],
                    payload["bed"],
                    "Internare initiala",
                    payload["admitted_at"],
                    user_id,
                    now_ts(),
                ),
            )
            conn.commit()
            return admission_id, completed_booking_id

    def list_admissions(self, patient_id: int, include_closed: bool = True, limit: int = 200) -> List[sqlite3.Row]:
        with self._connect() as conn:
            if include_closed:
                return conn.execute(
                    """
                    SELECT id, mrn, admission_type, triage_level, department, ward, bed,
                           attending_clinician, chief_complaint, status, admitted_at, discharged_at, discharge_summary,
                           (SELECT c.finalized_at FROM admission_case_closure c WHERE c.admission_id = admissions.id) AS case_finalized_at
                    FROM admissions
                    WHERE patient_id = ?
                    ORDER BY admitted_at DESC, id DESC
                    LIMIT ?
                    """,
                    (patient_id, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT id, mrn, admission_type, triage_level, department, ward, bed,
                      attending_clinician, chief_complaint, status, admitted_at, discharged_at, discharge_summary,
                      (SELECT c.finalized_at FROM admission_case_closure c WHERE c.admission_id = admissions.id) AS case_finalized_at
                FROM admissions
                WHERE patient_id = ? AND status = 'active'
                ORDER BY admitted_at DESC, id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()

    def get_active_admission(self, patient_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, mrn, admission_type, triage_level, department, ward, bed,
                       attending_clinician, chief_complaint, status, admitted_at
                FROM admissions
                WHERE patient_id = ? AND status = 'active'
                ORDER BY admitted_at DESC, id DESC
                LIMIT 1
                """,
                (patient_id,),
            ).fetchone()

    def discharge_admission(self, admission_id: int, discharge_summary: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT patient_id, department, ward, bed, status
                FROM admissions
                WHERE id = ?
                """,
                (admission_id,),
            ).fetchone()
            if not row or row["status"] != "active":
                raise ValueError("Internarea selectata nu este activa.")
            when = now_ts()
            discharge_booking = conn.execute(
                """
                SELECT id
                FROM care_bookings
                WHERE patient_id = ?
                  AND booking_type = 'discharge'
                  AND status = 'scheduled'
                  AND date(starts_at) = date(?)
                ORDER BY ABS(julianday(starts_at) - julianday(?)) ASC, id DESC
                LIMIT 1
                """,
                (int(row["patient_id"]), when, when),
            ).fetchone()
            if not discharge_booking:
                raise ValueError(
                    "Tranzitie invalida: pacientul trebuie sa aiba programare de externare in ziua curenta. "
                    "Programeaza externarea inainte de finalizare."
                )
            conn.execute(
                """
                UPDATE admissions
                SET status = 'discharged',
                    discharged_at = ?,
                    discharge_summary = ?
                WHERE id = ? AND status = 'active'
                """,
                (when, discharge_summary.strip(), admission_id),
            )
            conn.execute(
                """
                UPDATE care_bookings
                SET status = 'completed'
                WHERE id = ?
                """,
                (int(discharge_booking["id"]),),
            )
            conn.execute(
                """
                INSERT INTO admission_transfers (
                    admission_id, action_type,
                    from_department, from_ward, from_bed,
                    to_department, to_ward, to_bed,
                    notes, transferred_at, created_by_user_id, created_at
                ) VALUES (?, 'discharge', ?, ?, ?, '', '', '', ?, ?, NULL, ?)
                """,
                (
                    admission_id,
                    row["department"] or "",
                    row["ward"] or "",
                    row["bed"] or "",
                    "Externare internare",
                    when,
                    now_ts(),
                ),
            )
            conn.commit()
            return int(discharge_booking["id"])

    def list_admission_transfers(self, admission_id: int, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, admission_id, action_type,
                       from_department, from_ward, from_bed,
                       to_department, to_ward, to_bed,
                       notes, transferred_at
                FROM admission_transfers
                WHERE admission_id = ?
                ORDER BY transferred_at ASC, id ASC
                LIMIT ?
                """,
                (admission_id, limit),
            ).fetchall()

    def transfer_admission(
        self,
        admission_id: int,
        *,
        to_department: str,
        to_ward: str,
        to_bed: str,
        transferred_at: str,
        notes: str,
        user_id: Optional[int],
    ) -> None:
        when = (transferred_at or "").strip() or now_ts()
        self._parse_dt_text(when)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, status, department, ward, bed, admitted_at
                FROM admissions
                WHERE id = ?
                """,
                (admission_id,),
            ).fetchone()
            if not row or row["status"] != "active":
                raise ValueError("Internarea selectata nu este activa.")

            dept_new = (to_department or "").strip()
            ward_new = (to_ward or "").strip()
            bed_new = (to_bed or "").strip()
            if not (dept_new and ward_new and bed_new):
                raise ValueError("Sectia, salonul si patul tinta sunt obligatorii pentru transfer.")
            if (
                dept_new.lower() == str(row["department"] or "").strip().lower()
                and ward_new.lower() == str(row["ward"] or "").strip().lower()
                and bed_new.lower() == str(row["bed"] or "").strip().lower()
            ):
                raise ValueError("Transfer invalid: destinatia este identica cu locatia curenta.")

            admitted_at_text = str(row["admitted_at"] or "").strip()
            if admitted_at_text:
                admitted_dt = self._parse_dt_text(admitted_at_text)
                when_dt = self._parse_dt_text(when)
                if when_dt < admitted_dt:
                    raise ValueError("Moment transfer invalid: este anterior datei internarii.")

            if self.has_active_bed_conflict(dept_new, ward_new, bed_new, exclude_admission_id=admission_id):
                raise ValueError("Patul tinta este ocupat de o alta internare activa.")

            conn.execute(
                """
                UPDATE admissions
                SET department = ?, ward = ?, bed = ?
                WHERE id = ?
                """,
                (dept_new, ward_new, bed_new, admission_id),
            )
            conn.execute(
                """
                INSERT INTO admission_transfers (
                    admission_id, action_type,
                    from_department, from_ward, from_bed,
                    to_department, to_ward, to_bed,
                    notes, transferred_at, created_by_user_id, created_at
                ) VALUES (?, 'transfer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admission_id,
                    row["department"] or "",
                    row["ward"] or "",
                    row["bed"] or "",
                    dept_new,
                    ward_new,
                    bed_new,
                    (notes or "").strip(),
                    when,
                    user_id,
                    now_ts(),
                ),
            )
            conn.commit()

    def has_final_decont(self, admission_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM billing_records
                WHERE admission_id = ?
                  AND record_type = 'final'
                  AND status = 'issued'
                LIMIT 1
                """,
                (admission_id,),
            ).fetchone()
        return row is not None

    def get_admission_case_closure(self, admission_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT admission_id, finalized_at, finalized_by_user_id, validation_report
                FROM admission_case_closure
                WHERE admission_id = ?
                """,
                (admission_id,),
            ).fetchone()

    def get_admission_diagnoses(self, admission_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT admission_id, referral_diagnosis, admission_diagnosis, discharge_diagnosis,
                       secondary_diagnoses, dietary_regimen, admission_criteria, discharge_criteria,
                       updated_at, updated_by_user_id
                FROM admission_diagnoses
                WHERE admission_id = ?
                """,
                (admission_id,),
            ).fetchone()

    def upsert_admission_diagnoses(self, admission_id: int, payload: Dict[str, str], user_id: Optional[int]) -> None:
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM admissions WHERE id = ? LIMIT 1", (admission_id,)).fetchone()
            if not exists:
                raise ValueError("Internare inexistenta pentru diagnostice.")
            now = now_ts()
            conn.execute(
                """
                INSERT INTO admission_diagnoses (
                    admission_id, referral_diagnosis, admission_diagnosis,
                    discharge_diagnosis, secondary_diagnoses, dietary_regimen,
                    admission_criteria, discharge_criteria, updated_at, updated_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(admission_id) DO UPDATE SET
                    referral_diagnosis = excluded.referral_diagnosis,
                    admission_diagnosis = excluded.admission_diagnosis,
                    discharge_diagnosis = excluded.discharge_diagnosis,
                    secondary_diagnoses = excluded.secondary_diagnoses,
                    dietary_regimen = excluded.dietary_regimen,
                    admission_criteria = excluded.admission_criteria,
                    discharge_criteria = excluded.discharge_criteria,
                    updated_at = excluded.updated_at,
                    updated_by_user_id = excluded.updated_by_user_id
                """,
                (
                    admission_id,
                    (payload.get("referral_diagnosis") or "").strip(),
                    (payload.get("admission_diagnosis") or "").strip(),
                    (payload.get("discharge_diagnosis") or "").strip(),
                    (payload.get("secondary_diagnoses") or "").strip(),
                    (payload.get("dietary_regimen") or "").strip(),
                    (payload.get("admission_criteria") or "").strip(),
                    (payload.get("discharge_criteria") or "").strip(),
                    now,
                    user_id,
                ),
            )
            conn.commit()

    def validate_admission_case(self, admission_id: int) -> List[str]:
        errors: List[str] = []
        with self._connect() as conn:
            adm = conn.execute(
                """
                SELECT id, status, admitted_at, discharged_at, discharge_summary
                FROM admissions
                WHERE id = ?
                """,
                (admission_id,),
            ).fetchone()
            if not adm:
                return ["Internare inexistenta."]

            transfer_rows = conn.execute(
                """
                SELECT action_type, from_department, from_ward, from_bed,
                       to_department, to_ward, to_bed, transferred_at
                FROM admission_transfers
                WHERE admission_id = ?
                ORDER BY transferred_at ASC, id ASC
                """,
                (admission_id,),
            ).fetchall()
            diag = conn.execute(
                """
                SELECT referral_diagnosis, admission_diagnosis, discharge_diagnosis,
                       secondary_diagnoses, dietary_regimen, admission_criteria, discharge_criteria
                FROM admission_diagnoses
                WHERE admission_id = ?
                """,
                (admission_id,),
            ).fetchone()

        if (adm["status"] or "") != "discharged":
            errors.append("Cazul nu este externat.")
        if not (adm["admitted_at"] or "").strip():
            errors.append("Lipseste data/ora internarii.")
        if not (adm["discharged_at"] or "").strip():
            errors.append("Lipseste data/ora externarii.")
        if not (adm["discharge_summary"] or "").strip():
            errors.append("Lipseste rezumatul externarii.")
        if not self.has_final_decont(admission_id):
            errors.append("Lipseste decontul final.")

        if not diag:
            errors.append("Lipsesc diagnosticele tipizate FO (trimitere/internare/externare).")
        else:
            if not (diag["admission_diagnosis"] or "").strip():
                errors.append("Lipseste diagnosticul de internare.")
            if not (diag["discharge_diagnosis"] or "").strip():
                errors.append("Lipseste diagnosticul de externare.")
            if not (diag["dietary_regimen"] or "").strip():
                errors.append("Lipseste regimul alimentar.")
            if not (diag["admission_criteria"] or "").strip():
                errors.append("Lipsesc criteriile de internare.")
            if not (diag["discharge_criteria"] or "").strip():
                errors.append("Lipsesc criteriile de externare.")

        has_admit = any((row["action_type"] or "") == "admit" for row in transfer_rows)
        has_discharge = any((row["action_type"] or "") == "discharge" for row in transfer_rows)
        if not has_admit:
            errors.append("Jurnal transferuri incomplet: lipseste evenimentul de internare (admit).")
        if not has_discharge:
            errors.append("Jurnal transferuri incomplet: lipseste evenimentul de externare (discharge).")

        admitted_at_text = str(adm["admitted_at"] or "").strip()
        discharged_at_text = str(adm["discharged_at"] or "").strip()
        admitted_dt = self._parse_dt_text(admitted_at_text) if admitted_at_text else None
        discharged_dt = self._parse_dt_text(discharged_at_text) if discharged_at_text else None
        previous_dt: Optional[datetime] = None
        for row in transfer_rows:
            moved_at_text = str(row["transferred_at"] or "").strip()
            if not moved_at_text:
                errors.append("Jurnal transferuri invalid: exista transfer fara timestamp.")
                continue
            moved_at = self._parse_dt_text(moved_at_text)
            if admitted_dt and moved_at < admitted_dt:
                errors.append("Jurnal transferuri invalid: exista transfer inainte de internare.")
                break
            if discharged_dt and moved_at > discharged_dt:
                errors.append("Jurnal transferuri invalid: exista transfer dupa externare.")
                break
            if previous_dt and moved_at < previous_dt:
                errors.append("Jurnal transferuri invalid: ordinea cronologica este inconsistente.")
                break
            previous_dt = moved_at

        return errors

    def finalize_admission_case(self, admission_id: int, user_id: Optional[int]) -> None:
        errors = self.validate_admission_case(admission_id)
        if errors:
            raise ValueError("\n".join(errors))
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM admission_case_closure WHERE admission_id = ? LIMIT 1",
                (admission_id,),
            ).fetchone()
            if existing:
                raise ValueError("Cazul este deja finalizat.")
            conn.execute(
                """
                INSERT INTO admission_case_closure (admission_id, finalized_at, finalized_by_user_id, validation_report)
                VALUES (?, ?, ?, ?)
                """,
                (admission_id, now_ts(), user_id, "Validat automat: externare + decont final."),
            )
            conn.commit()

    def create_billing_record(
        self,
        *,
        admission_id: int,
        record_type: str,
        amount: float,
        issued_at: str,
        notes: str,
        user_id: Optional[int],
    ) -> int:
        kind = (record_type or "").strip().lower()
        if kind not in {"partial", "final"}:
            raise ValueError("Tip decont invalid.")
        when = (issued_at or "").strip() or now_ts()
        self._parse_dt_text(when)
        value = float(amount)
        if value < 0:
            raise ValueError("Valoarea decontului trebuie sa fie >= 0.")

        with self._connect() as conn:
            adm = conn.execute(
                """
                SELECT id, patient_id, status
                FROM admissions
                WHERE id = ?
                """,
                (admission_id,),
            ).fetchone()
            if not adm:
                raise ValueError("Internare inexistenta pentru decont.")
            if kind == "final":
                if adm["status"] != "discharged":
                    raise ValueError("Decontul final se poate emite doar dupa externare.")
                existing = conn.execute(
                    """
                    SELECT 1
                    FROM billing_records
                    WHERE admission_id = ?
                      AND record_type = 'final'
                      AND status = 'issued'
                    LIMIT 1
                    """,
                    (admission_id,),
                ).fetchone()
                if existing:
                    raise ValueError("Exista deja decont final pentru aceasta internare.")

            cur = conn.execute(
                """
                INSERT INTO billing_records (
                    admission_id, patient_id, record_type, amount, currency,
                    issued_at, notes, status, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, 'RON', ?, ?, 'issued', ?, ?)
                """,
                (
                    admission_id,
                    int(adm["patient_id"]),
                    kind,
                    value,
                    when,
                    (notes or "").strip(),
                    user_id,
                    now_ts(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_billing_records(self, admission_id: int, limit: int = 200) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, admission_id, patient_id, record_type, amount, currency, issued_at, notes, status
                FROM billing_records
                WHERE admission_id = ?
                ORDER BY issued_at DESC, id DESC
                LIMIT ?
                """,
                (admission_id, limit),
            ).fetchall()

    def add_order(
        self,
        patient_id: int,
        admission_id: Optional[int],
        order_type: str,
        priority: str,
        order_text: str,
        user_id: Optional[int],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders_medical (
                    patient_id, admission_id, order_type, priority, order_text,
                    status, ordered_at, ordered_by_user_id
                ) VALUES (?, ?, ?, ?, ?, 'ordered', ?, ?)
                """,
                (
                    patient_id,
                    admission_id,
                    order_type.strip(),
                    priority.strip(),
                    order_text.strip(),
                    now_ts(),
                    user_id,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_orders(self, patient_id: int, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, admission_id, order_type, priority, order_text, status, ordered_at, completed_at
                FROM orders_medical
                WHERE patient_id = ?
                ORDER BY ordered_at DESC, id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()

    def update_order_status(self, order_id: int, new_status: str) -> None:
        status = (new_status or "").strip().lower()
        if status not in {"ordered", "in_progress", "done", "cancelled"}:
            raise ValueError("Status invalid pentru ordin medical.")
        completed_at = now_ts() if status == "done" else ""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders_medical
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, completed_at, order_id),
            )
            conn.commit()

    def add_vital(self, patient_id: int, admission_id: Optional[int], payload: Dict[str, str], user_id: Optional[int]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO vitals (
                    patient_id, admission_id, recorded_at, temperature_c, systolic_bp, diastolic_bp,
                    pulse, respiratory_rate, spo2, pain_score, notes, recorded_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient_id,
                    admission_id,
                    payload["recorded_at"],
                    payload["temperature_c"],
                    payload["systolic_bp"],
                    payload["diastolic_bp"],
                    payload["pulse"],
                    payload["respiratory_rate"],
                    payload["spo2"],
                    payload["pain_score"],
                    payload["notes"],
                    user_id,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_vitals(self, patient_id: int, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, admission_id, recorded_at, temperature_c, systolic_bp, diastolic_bp,
                       pulse, respiratory_rate, spo2, pain_score, notes
                FROM vitals
                WHERE patient_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()

    def list_active_admissions_dashboard(self, department: str = "", limit: int = 500) -> List[sqlite3.Row]:
        department = department.strip()
        with self._connect() as conn:
            if department:
                return conn.execute(
                    """
                    SELECT a.id, a.patient_id, a.mrn, a.admission_type, a.triage_level, a.department, a.ward, a.bed,
                           a.attending_clinician, a.chief_complaint, a.admitted_at,
                           p.first_name, p.last_name, p.cnp
                    FROM admissions a
                    JOIN patients p ON p.id = a.patient_id
                    WHERE a.status = 'active' AND lower(a.department) = lower(?)
                    ORDER BY a.triage_level ASC, a.admitted_at ASC, a.id ASC
                    LIMIT ?
                    """,
                    (department, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT a.id, a.patient_id, a.mrn, a.admission_type, a.triage_level, a.department, a.ward, a.bed,
                       a.attending_clinician, a.chief_complaint, a.admitted_at,
                       p.first_name, p.last_name, p.cnp
                FROM admissions a
                JOIN patients p ON p.id = a.patient_id
                WHERE a.status = 'active'
                ORDER BY a.triage_level ASC, a.admitted_at ASC, a.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def list_urgent_orders_dashboard(self, department: str = "", limit: int = 500) -> List[sqlite3.Row]:
        department = department.strip()
        with self._connect() as conn:
            if department:
                return conn.execute(
                    """
                    SELECT o.id, o.patient_id, o.admission_id, o.order_type, o.priority, o.status, o.ordered_at, o.order_text,
                           a.mrn, a.department,
                           p.first_name, p.last_name
                    FROM orders_medical o
                    LEFT JOIN admissions a ON a.id = o.admission_id
                    JOIN patients p ON p.id = o.patient_id
                    WHERE o.status IN ('ordered', 'in_progress')
                      AND o.priority IN ('stat', 'urgent')
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    ORDER BY o.priority = 'stat' DESC, o.ordered_at ASC, o.id ASC
                    LIMIT ?
                    """,
                    (department, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT o.id, o.patient_id, o.admission_id, o.order_type, o.priority, o.status, o.ordered_at, o.order_text,
                       a.mrn, a.department,
                       p.first_name, p.last_name
                FROM orders_medical o
                LEFT JOIN admissions a ON a.id = o.admission_id
                JOIN patients p ON p.id = o.patient_id
                WHERE o.status IN ('ordered', 'in_progress')
                  AND o.priority IN ('stat', 'urgent')
                ORDER BY o.priority = 'stat' DESC, o.ordered_at ASC, o.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def list_vital_alerts_dashboard(self, department: str = "", hours: int = 24, limit: int = 500) -> List[Dict[str, Any]]:
        threshold = (datetime.now() - timedelta(hours=max(1, hours))).strftime("%Y-%m-%d %H:%M:%S")
        department = department.strip()
        with self._connect() as conn:
            if department:
                rows = conn.execute(
                    """
                    SELECT v.id, v.patient_id, v.admission_id, v.recorded_at, v.temperature_c, v.systolic_bp, v.diastolic_bp,
                           v.pulse, v.respiratory_rate, v.spo2, v.pain_score, v.notes,
                           a.mrn, a.department,
                           p.first_name, p.last_name
                    FROM vitals v
                    LEFT JOIN admissions a ON a.id = v.admission_id
                    JOIN patients p ON p.id = v.patient_id
                    WHERE v.recorded_at >= ?
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    ORDER BY v.recorded_at DESC, v.id DESC
                    LIMIT ?
                    """,
                    (threshold, department, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT v.id, v.patient_id, v.admission_id, v.recorded_at, v.temperature_c, v.systolic_bp, v.diastolic_bp,
                           v.pulse, v.respiratory_rate, v.spo2, v.pain_score, v.notes,
                           a.mrn, a.department,
                           p.first_name, p.last_name
                    FROM vitals v
                    LEFT JOIN admissions a ON a.id = v.admission_id
                    JOIN patients p ON p.id = v.patient_id
                    WHERE v.recorded_at >= ?
                    ORDER BY v.recorded_at DESC, v.id DESC
                    LIMIT ?
                    """,
                    (threshold, limit),
                ).fetchall()

        def _to_float(value: str) -> Optional[float]:
            value = (value or "").strip().replace(",", ".")
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        alerts: List[Dict[str, Any]] = []
        for row in rows:
            reasons: List[str] = []
            temp = _to_float(row["temperature_c"])
            s_bp = _to_float(row["systolic_bp"])
            d_bp = _to_float(row["diastolic_bp"])
            pulse = _to_float(row["pulse"])
            rr = _to_float(row["respiratory_rate"])
            spo2 = _to_float(row["spo2"])
            pain = _to_float(row["pain_score"])

            if temp is not None and (temp >= 38.0 or temp <= 35.0):
                reasons.append(f"temp={temp}")
            if s_bp is not None and (s_bp >= 180 or s_bp <= 90):
                reasons.append(f"TAs={int(s_bp)}")
            if d_bp is not None and (d_bp >= 120 or d_bp <= 50):
                reasons.append(f"TAd={int(d_bp)}")
            if pulse is not None and (pulse >= 120 or pulse <= 40):
                reasons.append(f"puls={int(pulse)}")
            if rr is not None and (rr >= 28 or rr <= 8):
                reasons.append(f"resp={int(rr)}")
            if spo2 is not None and spo2 < 92:
                reasons.append(f"SpO2={int(spo2)}")
            if pain is not None and pain >= 8:
                reasons.append(f"durere={int(pain)}")

            if reasons:
                payload = dict(row)
                payload["reasons"] = ", ".join(reasons)
                alerts.append(payload)
        return alerts

    def get_dashboard_kpis(self, department: str = "") -> Dict[str, int]:
        department = department.strip()
        with self._connect() as conn:
            if department:
                active = conn.execute(
                    "SELECT COUNT(1) FROM admissions WHERE status='active' AND lower(department)=lower(?)",
                    (department,),
                ).fetchone()[0]
                triage12 = conn.execute(
                    "SELECT COUNT(1) FROM admissions WHERE status='active' AND triage_level IN (1,2) AND lower(department)=lower(?)",
                    (department,),
                ).fetchone()[0]
                urgent_orders = conn.execute(
                    """
                    SELECT COUNT(1)
                    FROM orders_medical o
                    LEFT JOIN admissions a ON a.id = o.admission_id
                    WHERE o.status IN ('ordered','in_progress')
                      AND o.priority IN ('stat','urgent')
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    """,
                    (department,),
                ).fetchone()[0]
            else:
                active = conn.execute("SELECT COUNT(1) FROM admissions WHERE status='active'").fetchone()[0]
                triage12 = conn.execute(
                    "SELECT COUNT(1) FROM admissions WHERE status='active' AND triage_level IN (1,2)"
                ).fetchone()[0]
                urgent_orders = conn.execute(
                    "SELECT COUNT(1) FROM orders_medical WHERE status IN ('ordered','in_progress') AND priority IN ('stat','urgent')"
                ).fetchone()[0]
            alerts_24h = len(self.list_vital_alerts_dashboard(department=department, hours=24, limit=1000))
        return {
            "active_admissions": int(active),
            "triage_1_2": int(triage12),
            "urgent_orders": int(urgent_orders),
            "vital_alerts_24h": int(alerts_24h),
        }

    def get_statistics_summary(self, date_from: str, date_to: str, department: str = "") -> Dict[str, float]:
        department = department.strip()
        start = date_from.strip()
        end = date_to.strip()
        if not start or not end:
            return {
                "admissions": 0,
                "discharges": 0,
                "orders": 0,
                "vitals": 0,
                "avg_los_days": 0.0,
            }
        with self._connect() as conn:
            if department:
                admissions = conn.execute(
                    """
                    SELECT COUNT(1)
                    FROM admissions
                    WHERE date(admitted_at) BETWEEN ? AND ?
                      AND lower(department) = lower(?)
                    """,
                    (start, end, department),
                ).fetchone()[0]
                discharges = conn.execute(
                    """
                    SELECT COUNT(1)
                    FROM admissions
                    WHERE status='discharged'
                      AND date(discharged_at) BETWEEN ? AND ?
                      AND lower(department) = lower(?)
                    """,
                    (start, end, department),
                ).fetchone()[0]
                los_avg = conn.execute(
                    """
                    SELECT AVG(julianday(discharged_at) - julianday(admitted_at))
                    FROM admissions
                    WHERE status='discharged'
                      AND date(discharged_at) BETWEEN ? AND ?
                      AND lower(department) = lower(?)
                    """,
                    (start, end, department),
                ).fetchone()[0]
                orders = conn.execute(
                    """
                    SELECT COUNT(1)
                    FROM orders_medical o
                    LEFT JOIN admissions a ON a.id = o.admission_id
                    WHERE date(o.ordered_at) BETWEEN ? AND ?
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    """,
                    (start, end, department),
                ).fetchone()[0]
                vitals = conn.execute(
                    """
                    SELECT COUNT(1)
                    FROM vitals v
                    LEFT JOIN admissions a ON a.id = v.admission_id
                    WHERE date(v.recorded_at) BETWEEN ? AND ?
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    """,
                    (start, end, department),
                ).fetchone()[0]
            else:
                admissions = conn.execute(
                    "SELECT COUNT(1) FROM admissions WHERE date(admitted_at) BETWEEN ? AND ?",
                    (start, end),
                ).fetchone()[0]
                discharges = conn.execute(
                    "SELECT COUNT(1) FROM admissions WHERE status='discharged' AND date(discharged_at) BETWEEN ? AND ?",
                    (start, end),
                ).fetchone()[0]
                los_avg = conn.execute(
                    """
                    SELECT AVG(julianday(discharged_at) - julianday(admitted_at))
                    FROM admissions
                    WHERE status='discharged' AND date(discharged_at) BETWEEN ? AND ?
                    """,
                    (start, end),
                ).fetchone()[0]
                orders = conn.execute(
                    "SELECT COUNT(1) FROM orders_medical WHERE date(ordered_at) BETWEEN ? AND ?",
                    (start, end),
                ).fetchone()[0]
                vitals = conn.execute(
                    "SELECT COUNT(1) FROM vitals WHERE date(recorded_at) BETWEEN ? AND ?",
                    (start, end),
                ).fetchone()[0]
        return {
            "admissions": float(admissions or 0),
            "discharges": float(discharges or 0),
            "orders": float(orders or 0),
            "vitals": float(vitals or 0),
            "avg_los_days": float(los_avg or 0.0),
        }

    def get_daily_activity(self, date_from: str, date_to: str, department: str = "") -> List[Dict[str, Any]]:
        start = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
        if end < start:
            start, end = end, start
        day_count = (end - start).days + 1
        if day_count > 366:
            end = start + timedelta(days=365)
            day_count = 366
        department = department.strip()

        data: Dict[str, Dict[str, int]] = {}
        cursor = start
        while cursor <= end:
            key = cursor.strftime("%Y-%m-%d")
            data[key] = {"admissions": 0, "discharges": 0, "orders": 0, "vitals": 0}
            cursor += timedelta(days=1)

        with self._connect() as conn:
            if department:
                admissions_rows = conn.execute(
                    """
                    SELECT date(admitted_at) AS d, COUNT(1) AS c
                    FROM admissions
                    WHERE date(admitted_at) BETWEEN ? AND ?
                      AND lower(department) = lower(?)
                    GROUP BY date(admitted_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), department),
                ).fetchall()
                discharges_rows = conn.execute(
                    """
                    SELECT date(discharged_at) AS d, COUNT(1) AS c
                    FROM admissions
                    WHERE status='discharged'
                      AND date(discharged_at) BETWEEN ? AND ?
                      AND lower(department) = lower(?)
                    GROUP BY date(discharged_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), department),
                ).fetchall()
                orders_rows = conn.execute(
                    """
                    SELECT date(o.ordered_at) AS d, COUNT(1) AS c
                    FROM orders_medical o
                    LEFT JOIN admissions a ON a.id = o.admission_id
                    WHERE date(o.ordered_at) BETWEEN ? AND ?
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    GROUP BY date(o.ordered_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), department),
                ).fetchall()
                vitals_rows = conn.execute(
                    """
                    SELECT date(v.recorded_at) AS d, COUNT(1) AS c
                    FROM vitals v
                    LEFT JOIN admissions a ON a.id = v.admission_id
                    WHERE date(v.recorded_at) BETWEEN ? AND ?
                      AND lower(COALESCE(a.department, '')) = lower(?)
                    GROUP BY date(v.recorded_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), department),
                ).fetchall()
            else:
                admissions_rows = conn.execute(
                    """
                    SELECT date(admitted_at) AS d, COUNT(1) AS c
                    FROM admissions
                    WHERE date(admitted_at) BETWEEN ? AND ?
                    GROUP BY date(admitted_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
                ).fetchall()
                discharges_rows = conn.execute(
                    """
                    SELECT date(discharged_at) AS d, COUNT(1) AS c
                    FROM admissions
                    WHERE status='discharged' AND date(discharged_at) BETWEEN ? AND ?
                    GROUP BY date(discharged_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
                ).fetchall()
                orders_rows = conn.execute(
                    """
                    SELECT date(ordered_at) AS d, COUNT(1) AS c
                    FROM orders_medical
                    WHERE date(ordered_at) BETWEEN ? AND ?
                    GROUP BY date(ordered_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
                ).fetchall()
                vitals_rows = conn.execute(
                    """
                    SELECT date(recorded_at) AS d, COUNT(1) AS c
                    FROM vitals
                    WHERE date(recorded_at) BETWEEN ? AND ?
                    GROUP BY date(recorded_at)
                    """,
                    (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
                ).fetchall()

        for row in admissions_rows:
            d = row["d"]
            if d in data:
                data[d]["admissions"] = int(row["c"])
        for row in discharges_rows:
            d = row["d"]
            if d in data:
                data[d]["discharges"] = int(row["c"])
        for row in orders_rows:
            d = row["d"]
            if d in data:
                data[d]["orders"] = int(row["c"])
        for row in vitals_rows:
            d = row["d"]
            if d in data:
                data[d]["vitals"] = int(row["c"])

        out: List[Dict[str, Any]] = []
        for day_key in sorted(data.keys()):
            payload = {"day": day_key}
            payload.update(data[day_key])
            out.append(payload)
        return out

    def get_daily_operational_activity(self, date_from: str, date_to: str, department: str = "") -> List[Dict[str, Any]]:
        start = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
        if end < start:
            start, end = end, start
        day_count = (end - start).days + 1
        if day_count > 366:
            end = start + timedelta(days=365)
        department = department.strip()

        data: Dict[str, Dict[str, int]] = {}
        cursor = start
        while cursor <= end:
            key = cursor.strftime("%Y-%m-%d")
            data[key] = {
                "scheduled_admissions": 0,
                "scheduled_discharges": 0,
                "discharged_without_final_decont": 0,
            }
            cursor += timedelta(days=1)

        with self._connect() as conn:
            params_base: List[Any] = [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]
            dept_clause_booking = ""
            dept_clause_adm = ""
            if department:
                dept_clause_booking = "AND lower(b.department) = lower(?)"
                dept_clause_adm = "AND lower(a.department) = lower(?)"

            adm_sql = f"""
                SELECT date(b.starts_at) AS d, COUNT(1) AS c
                FROM care_bookings b
                WHERE b.booking_type = 'admission'
                  AND b.status = 'scheduled'
                  AND date(b.starts_at) BETWEEN ? AND ?
                  {dept_clause_booking}
                GROUP BY date(b.starts_at)
            """
            dis_sql = f"""
                SELECT date(b.starts_at) AS d, COUNT(1) AS c
                FROM care_bookings b
                WHERE b.booking_type = 'discharge'
                  AND b.status = 'scheduled'
                  AND date(b.starts_at) BETWEEN ? AND ?
                  {dept_clause_booking}
                GROUP BY date(b.starts_at)
            """
            no_final_sql = f"""
                SELECT date(a.discharged_at) AS d, COUNT(1) AS c
                FROM admissions a
                WHERE a.status = 'discharged'
                  AND date(a.discharged_at) BETWEEN ? AND ?
                  {dept_clause_adm}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM billing_records br
                      WHERE br.admission_id = a.id
                        AND br.record_type = 'final'
                        AND br.status = 'issued'
                  )
                GROUP BY date(a.discharged_at)
            """

            if department:
                params = tuple(params_base + [department])
                adm_rows = conn.execute(adm_sql, params).fetchall()
                dis_rows = conn.execute(dis_sql, params).fetchall()
                no_final_rows = conn.execute(no_final_sql, params).fetchall()
            else:
                params = tuple(params_base)
                adm_rows = conn.execute(adm_sql, params).fetchall()
                dis_rows = conn.execute(dis_sql, params).fetchall()
                no_final_rows = conn.execute(no_final_sql, params).fetchall()

        for row in adm_rows:
            d = row["d"]
            if d in data:
                data[d]["scheduled_admissions"] = int(row["c"])
        for row in dis_rows:
            d = row["d"]
            if d in data:
                data[d]["scheduled_discharges"] = int(row["c"])
        for row in no_final_rows:
            d = row["d"]
            if d in data:
                data[d]["discharged_without_final_decont"] = int(row["c"])

        out: List[Dict[str, Any]] = []
        for day_key in sorted(data.keys()):
            payload = {"day": day_key}
            payload.update(data[day_key])
            out.append(payload)
        return out

    def get_operational_by_department(self, date_from: str, date_to: str, department: str = "") -> List[Dict[str, Any]]:
        start = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
        if end < start:
            start, end = end, start
        department = department.strip()

        data: Dict[str, Dict[str, int]] = {}

        def ensure_bucket(name: str) -> Dict[str, int]:
            key = (name or "").strip() or "(Nespecificat)"
            return data.setdefault(
                key,
                {
                    "scheduled_admissions": 0,
                    "scheduled_discharges": 0,
                    "discharged_without_final_decont": 0,
                },
            )

        with self._connect() as conn:
            params_base: List[Any] = [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]
            dept_clause_booking = ""
            dept_clause_adm = ""
            if department:
                dept_clause_booking = "AND lower(b.department) = lower(?)"
                dept_clause_adm = "AND lower(a.department) = lower(?)"

            adm_sql = f"""
                SELECT COALESCE(NULLIF(TRIM(b.department), ''), '(Nespecificat)') AS department_name,
                       COUNT(1) AS c
                FROM care_bookings b
                WHERE b.booking_type = 'admission'
                  AND b.status = 'scheduled'
                  AND date(b.starts_at) BETWEEN ? AND ?
                  {dept_clause_booking}
                GROUP BY COALESCE(NULLIF(TRIM(b.department), ''), '(Nespecificat)')
            """
            dis_sql = f"""
                SELECT COALESCE(NULLIF(TRIM(b.department), ''), '(Nespecificat)') AS department_name,
                       COUNT(1) AS c
                FROM care_bookings b
                WHERE b.booking_type = 'discharge'
                  AND b.status = 'scheduled'
                  AND date(b.starts_at) BETWEEN ? AND ?
                  {dept_clause_booking}
                GROUP BY COALESCE(NULLIF(TRIM(b.department), ''), '(Nespecificat)')
            """
            no_final_sql = f"""
                SELECT COALESCE(NULLIF(TRIM(a.department), ''), '(Nespecificat)') AS department_name,
                       COUNT(1) AS c
                FROM admissions a
                WHERE a.status = 'discharged'
                  AND date(a.discharged_at) BETWEEN ? AND ?
                  {dept_clause_adm}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM billing_records br
                      WHERE br.admission_id = a.id
                        AND br.record_type = 'final'
                        AND br.status = 'issued'
                  )
                GROUP BY COALESCE(NULLIF(TRIM(a.department), ''), '(Nespecificat)')
            """

            if department:
                params = tuple(params_base + [department])
                adm_rows = conn.execute(adm_sql, params).fetchall()
                dis_rows = conn.execute(dis_sql, params).fetchall()
                no_final_rows = conn.execute(no_final_sql, params).fetchall()
            else:
                params = tuple(params_base)
                adm_rows = conn.execute(adm_sql, params).fetchall()
                dis_rows = conn.execute(dis_sql, params).fetchall()
                no_final_rows = conn.execute(no_final_sql, params).fetchall()

        for row in adm_rows:
            ensure_bucket(str(row["department_name"]))["scheduled_admissions"] = int(row["c"])
        for row in dis_rows:
            ensure_bucket(str(row["department_name"]))["scheduled_discharges"] = int(row["c"])
        for row in no_final_rows:
            ensure_bucket(str(row["department_name"]))["discharged_without_final_decont"] = int(row["c"])

        out: List[Dict[str, Any]] = []
        for dept_key in sorted(data.keys()):
            payload = {"department": dept_key}
            payload.update(data[dept_key])
            payload["total"] = (
                int(payload["scheduled_admissions"])
                + int(payload["scheduled_discharges"])
                + int(payload["discharged_without_final_decont"])
            )
            out.append(payload)
        return out

    def get_admission_for_export(self, admission_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT a.id, a.patient_id, a.mrn, a.admission_type, a.triage_level, a.department, a.ward, a.bed,
                       a.attending_clinician, a.chief_complaint, a.status, a.admitted_at, a.discharged_at, a.discharge_summary,
                       p.first_name, p.last_name, p.cnp, p.birth_date, p.gender, p.phone, p.address, p.insurance_provider, p.insurance_id,
                       c.finalized_at AS case_finalized_at, c.validation_report AS case_validation_report,
                      d.referral_diagnosis, d.admission_diagnosis, d.discharge_diagnosis,
                      d.secondary_diagnoses, d.dietary_regimen, d.admission_criteria, d.discharge_criteria
                FROM admissions a
                JOIN patients p ON p.id = a.patient_id
                LEFT JOIN admission_case_closure c ON c.admission_id = a.id
                LEFT JOIN admission_diagnoses d ON d.admission_id = a.id
                WHERE a.id = ?
                """,
                (admission_id,),
            ).fetchone()

    def list_orders_for_admission(self, admission_id: int, limit: int = 200) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, order_type, priority, status, ordered_at, completed_at, order_text
                FROM orders_medical
                WHERE admission_id = ?
                ORDER BY ordered_at DESC, id DESC
                LIMIT ?
                """,
                (admission_id, limit),
            ).fetchall()

    def list_vitals_for_admission(self, admission_id: int, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, recorded_at, temperature_c, systolic_bp, diastolic_bp, pulse, respiratory_rate, spo2, pain_score, notes
                FROM vitals
                WHERE admission_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (admission_id, limit),
            ).fetchall()

    def list_operational_scheduled_bookings(
        self,
        *,
        booking_type: str,
        on_date: str,
        department: str = "",
        limit: int = 1000,
    ) -> List[sqlite3.Row]:
        btype = (booking_type or "").strip().lower()
        if btype not in {"admission", "discharge"}:
            raise ValueError("Tip booking invalid pentru raport operational.")
        day = (on_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
        dept = (department or "").strip()
        with self._connect() as conn:
            if dept:
                return conn.execute(
                    """
                    SELECT b.id, b.booking_type, b.starts_at, b.ends_at, b.department, b.ward, b.bed,
                           b.attending_clinician, b.notes,
                           p.id AS patient_id, p.first_name, p.last_name, p.cnp, p.phone
                    FROM care_bookings b
                    JOIN patients p ON p.id = b.patient_id
                    WHERE b.booking_type = ?
                      AND b.status = 'scheduled'
                      AND date(b.starts_at) = date(?)
                      AND lower(b.department) = lower(?)
                    ORDER BY b.starts_at ASC, b.id ASC
                    LIMIT ?
                    """,
                    (btype, day, dept, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT b.id, b.booking_type, b.starts_at, b.ends_at, b.department, b.ward, b.bed,
                       b.attending_clinician, b.notes,
                       p.id AS patient_id, p.first_name, p.last_name, p.cnp, p.phone
                FROM care_bookings b
                JOIN patients p ON p.id = b.patient_id
                WHERE b.booking_type = ?
                  AND b.status = 'scheduled'
                  AND date(b.starts_at) = date(?)
                ORDER BY b.starts_at ASC, b.id ASC
                LIMIT ?
                """,
                (btype, day, limit),
            ).fetchall()

    def list_discharged_without_final_decont(
        self,
        *,
        on_date: str,
        department: str = "",
        limit: int = 1000,
    ) -> List[sqlite3.Row]:
        day = (on_date or "").strip() or datetime.now().strftime("%Y-%m-%d")
        dept = (department or "").strip()
        with self._connect() as conn:
            if dept:
                return conn.execute(
                    """
                    SELECT a.id AS admission_id, a.mrn, a.department, a.ward, a.bed,
                           a.attending_clinician, a.admitted_at, a.discharged_at,
                           p.id AS patient_id, p.first_name, p.last_name, p.cnp, p.phone
                    FROM admissions a
                    JOIN patients p ON p.id = a.patient_id
                    WHERE a.status = 'discharged'
                      AND date(a.discharged_at) = date(?)
                      AND lower(a.department) = lower(?)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM billing_records br
                          WHERE br.admission_id = a.id
                            AND br.record_type = 'final'
                            AND br.status = 'issued'
                      )
                    ORDER BY a.discharged_at DESC, a.id DESC
                    LIMIT ?
                    """,
                    (day, dept, limit),
                ).fetchall()
            return conn.execute(
                """
                SELECT a.id AS admission_id, a.mrn, a.department, a.ward, a.bed,
                       a.attending_clinician, a.admitted_at, a.discharged_at,
                       p.id AS patient_id, p.first_name, p.last_name, p.cnp, p.phone
                FROM admissions a
                JOIN patients p ON p.id = a.patient_id
                WHERE a.status = 'discharged'
                  AND date(a.discharged_at) = date(?)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM billing_records br
                      WHERE br.admission_id = a.id
                        AND br.record_type = 'final'
                        AND br.status = 'issued'
                  )
                ORDER BY a.discharged_at DESC, a.id DESC
                LIMIT ?
                """,
                (day, limit),
            ).fetchall()

    def add_ai_message(self, patient_id: int, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_messages (patient_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (patient_id, role, content, now_ts()),
            )
            conn.commit()

    def list_ai_messages(self, patient_id: int, limit: int = 120) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT role, content, created_at
                FROM ai_messages
                WHERE patient_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            ).fetchall()[::-1]


class AIService:
    SYSTEM_PROMPT = (
        "Esti un asistent medical informational pentru fluxuri de spital. "
        "Raspunde concis, clar, in limba romana. Nu inventa date lipsa. "
        "Daca exista incertitudine clinica, spune explicit ce informatii lipsesc. "
        "Nu inlocuieste decizia medicului si nu da diagnostice definitive. "
        "Structura preferata: situatie, risc, recomandare, monitorizare."
    )

    def __init__(self) -> None:
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = DEFAULT_MODEL
        self.temperature = 0.2
        self.max_output_tokens = 900
        self.timeout_seconds = 45
        self.system_prompt = self.SYSTEM_PROMPT
        self.client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds) if (OpenAI and self.api_key) else None

    def configure(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: int,
        system_prompt: str,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.temperature = max(0.0, min(1.0, float(temperature)))
        self.max_output_tokens = max(200, int(max_output_tokens))
        self.timeout_seconds = max(10, int(timeout_seconds))
        self.system_prompt = (system_prompt or self.SYSTEM_PROMPT).strip() or self.SYSTEM_PROMPT
        self.client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds) if (OpenAI and self.api_key) else None

    def is_available(self) -> bool:
        return self.client is not None

    def unavailable_reason(self) -> str:
        if OpenAI is None:
            return "Lipseste pachetul 'openai'. Ruleaza: pip install -r requirements.txt"
        if not self.api_key:
            return "Lipseste OPENAI_API_KEY in mediu."
        return "Serviciul AI nu este disponibil."

    def generate_reply(
        self,
        patient_context: str,
        history: List[sqlite3.Row],
        user_message: str,
    ) -> str:
        structured = self.generate_structured_reply(patient_context, history, user_message)
        parts = [
            f"Situatie: {structured.get('situatie', '-')}",
            f"Risc: {structured.get('risc', '-')}",
            f"Recomandare: {structured.get('recomandare', '-')}",
            f"Monitorizare: {structured.get('monitorizare', '-')}",
        ]
        missing = structured.get("informatii_lipsa", "")
        if missing:
            parts.append(f"Informatii lipsa: {missing}")
        disclaimer = structured.get("disclaimer", "")
        if disclaimer:
            parts.append(disclaimer)
        return "\n".join(parts).strip()

    def generate_structured_reply(
        self,
        patient_context: str,
        history: List[sqlite3.Row],
        user_message: str,
    ) -> Dict[str, str]:
        if not self.client:
            raise RuntimeError(self.unavailable_reason())

        input_messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": f"Context pacient:\n{patient_context}"},
            {
                "role": "system",
                "content": (
                    "Raspunde EXCLUSIV in JSON valid, fara markdown. "
                    "Chei obligatorii: situatie, risc, recomandare, monitorizare, informatii_lipsa, disclaimer."
                ),
            },
        ]
        for row in history[-12:]:
            role = row["role"]
            content = row["content"]
            input_messages.append({"role": role, "content": content})
        input_messages.append({"role": "user", "content": user_message})

        try:
            response = self.client.responses.create(
                model=self.model,
                input=input_messages,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        except TypeError:
            response = self.client.responses.create(
                model=self.model,
                input=input_messages,
            )
        text = (getattr(response, "output_text", "") or "").strip()
        if text:
            parsed = self._parse_structured_json(text)
            if parsed:
                return parsed
            return self._fallback_structured(text)

        fallback = self._extract_output_text(response)
        if fallback:
            parsed = self._parse_structured_json(fallback)
            if parsed:
                return parsed
            return self._fallback_structured(fallback)
        return self._fallback_structured("Nu am putut genera un raspuns text.")

    @staticmethod
    def _parse_structured_json(text: str) -> Optional[Dict[str, str]]:
        raw = (text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()

        candidates = [raw]
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(raw[start : end + 1])

        required = ["situatie", "risc", "recomandare", "monitorizare", "informatii_lipsa", "disclaimer"]
        for cand in candidates:
            try:
                payload = json.loads(cand)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            out = {k: str(payload.get(k, "")).strip() for k in required}
            if out["situatie"] and out["recomandare"]:
                return out
        return None

    @staticmethod
    def _fallback_structured(text: str) -> Dict[str, str]:
        return {
            "situatie": (text or "").strip() or "Nu exista output AI.",
            "risc": "Nespecificat",
            "recomandare": "Revizuieste datele clinice si completeaza informatiile lipsa.",
            "monitorizare": "Monitorizare conform protocolului intern.",
            "informatii_lipsa": "Detalii clinice insuficiente pentru recomandari mai precise.",
            "disclaimer": "Acest output este informativ si nu inlocuieste decizia medicala.",
        }

    @staticmethod
    def _extract_output_text(response: Any) -> str:
        chunks: List[str] = []

        output = None
        if isinstance(response, dict):
            output = response.get("output")
        else:
            output = getattr(response, "output", None)

        if not output:
            return ""

        for item in output:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            content_blocks = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", [])
            for block in content_blocks:
                block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if block_type not in {"output_text", "text"}:
                    continue
                text = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()


class LoginDialog:
    def __init__(self, root: tk.Tk, db: Database) -> None:
        self.root = root
        self.db = db
        self.result: Optional[Dict[str, Any]] = None

        def _safe_int(value: str, fallback: int) -> int:
            try:
                return int((value or "").strip() or fallback)
            except Exception:
                return fallback

        env_lock_attempts = _safe_int(os.getenv("LOGIN_LOCK_MAX_ATTEMPTS") or "5", 5)
        env_lock_minutes = _safe_int(os.getenv("LOGIN_LOCK_MINUTES") or "10", 10)
        self.lock_max_attempts = max(
            3,
            _safe_int(self.db.get_setting("LOGIN_LOCK_MAX_ATTEMPTS", str(env_lock_attempts)), env_lock_attempts),
        )
        self.lock_minutes = max(
            1,
            _safe_int(self.db.get_setting("LOGIN_LOCK_MINUTES", str(env_lock_minutes)), env_lock_minutes),
        )

        self.win = tk.Toplevel(root)
        self.win.title("Autentificare - Sistem Spital")
        self.win.geometry("460x280")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.on_cancel)
        if root.winfo_viewable():
            self.win.transient(root)
        self.win.grab_set()

        self._center_and_focus()

        wrap = ttk.Frame(self.win, padding=14)
        wrap.pack(fill=BOTH, expand=True)

        ttk.Label(wrap, text=DEFAULT_HOSPITAL_NAME, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(wrap, text="Autentificare utilizator").pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(wrap)
        form.pack(fill="x")
        ttk.Label(form, text="Utilizator").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(form, text="Parola").grid(row=1, column=0, sticky="w", pady=4)
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.username_entry = ttk.Entry(form, textvariable=self.username_var, width=28)
        self.password_entry = ttk.Entry(form, textvariable=self.password_var, show="*", width=28)
        self.username_entry.grid(row=0, column=1, sticky="ew", pady=4)
        self.password_entry.grid(row=1, column=1, sticky="ew", pady=4)
        form.grid_columnconfigure(1, weight=1)

        hint = (
            "La prima rulare, credentialele initiale se pot genera automat in "
            f"{APP_DIR / 'initial_credentials.txt'}. "
            "Optional: seteaza PACIENTI_SEED_PASS_ADMIN / MEDIC / ASISTENT / RECEPTIE."
        )
        ttk.Label(wrap, text=hint, foreground="#475569", wraplength=420).pack(anchor="w", pady=(10, 10))

        self.error_var = tk.StringVar()
        ttk.Label(wrap, textvariable=self.error_var, foreground="#b91c1c").pack(anchor="w")

        actions = ttk.Frame(wrap)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Iesire", command=self.on_cancel).pack(side=LEFT)
        ttk.Button(actions, text="Login", command=self.on_login).pack(side=RIGHT)

        self.win.bind("<Return>", lambda _e: self.on_login())
        self.username_entry.focus_set()

    def _center_and_focus(self) -> None:
        self.win.update_idletasks()
        width = self.win.winfo_width() or 460
        height = self.win.winfo_height() or 280
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.attributes("-topmost", True)
            self.win.after(200, lambda: self.win.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self.win.focus_force()
        except Exception:
            pass

    def on_login(self) -> None:
        username = self.username_var.get().strip()
        remaining_lock = self.db.get_login_lock_remaining_seconds(username)
        if remaining_lock > 0:
            mins = max(1, remaining_lock // 60)
            self.error_var.set(f"Cont blocat temporar. Reincearca in ~{mins} min.")
            return

        row = self.db.authenticate_user(username, self.password_var.get())
        if not row:
            self.db.register_login_failure(username, max_attempts=self.lock_max_attempts, lock_minutes=self.lock_minutes)
            remaining_lock = self.db.get_login_lock_remaining_seconds(username)
            if remaining_lock > 0:
                mins = max(1, remaining_lock // 60)
                self.error_var.set(f"Prea multe incercari. Cont blocat ~{mins} min.")
            else:
                failed = self.db.get_login_failed_count(username)
                left = max(0, self.lock_max_attempts - failed)
                self.error_var.set(f"Credentiale invalide. Incercari ramase: {left}")
            return
        self.db.clear_login_failures(username)
        self.result = {
            "id": int(row["id"]),
            "username": row["username"],
            "role": normalize_role(row["role"]),
            "display_name": row["display_name"] or row["username"],
        }
        self.win.destroy()

    def on_cancel(self) -> None:
        self.result = None
        self.win.destroy()

    def show(self) -> Optional[Dict[str, Any]]:
        self.root.wait_window(self.win)
        return self.result


class PacientiAIApp:
    def __init__(self, root: tk.Tk, current_user: Dict[str, Any], db: Optional[Database] = None) -> None:
        self.root = root
        self.db = db or Database(DB_PATH)
        self.ai = AIService()
        self.current_user = current_user
        self.alert_poll_seconds = 45
        self.alert_last_seen_id = 0
        self.alert_poll_job: Optional[str] = None
        self.alert_muted_until: Optional[datetime] = None
        self.alert_escalation_minutes = 10
        self.alert_escalation_cooldown_seconds = 600
        self.alert_escalation_last_sent_at: Optional[datetime] = None
        self.notify_enabled = True
        self.notify_cooldown_seconds = 120
        self.notify_last_sent_at: Optional[datetime] = None
        self.notify_busy = False
        self.notify_telegram_token = ""
        self.notify_telegram_chat_id = ""
        self.notify_webhook_url = ""
        self.notify_email_from = ""
        self.notify_email_to: List[str] = []
        self.notify_smtp_host = ""
        self.notify_smtp_port = 587
        self.notify_smtp_user = ""
        self.notify_smtp_pass = ""
        self.backup_enabled = True
        self.backup_interval_minutes = 360
        self.backup_retention_days = 14
        self.discharge_require_final_decont = False
        self.discharge_require_summary = False
        self.operational_backlog_alert_threshold = 5
        self.watchlist_score_high_threshold = 90
        self.watchlist_score_medium_threshold = 60
        self.watchlist_weight_triage_1 = 60
        self.watchlist_weight_triage_2 = 40
        self.watchlist_weight_triage_3 = 20
        self.watchlist_weight_triage_4_plus = 5
        self.watchlist_weight_alert_unack = 25
        self.watchlist_weight_alert_critical = 15
        self.watchlist_weight_order_stat = 20
        self.watchlist_weight_order_urgent = 10
        self.watchlist_weight_order_in_progress = 5
        self.dashboard_filter_department_default = ""
        self.dashboard_operational_date_default = datetime.now().strftime("%Y-%m-%d")
        self.patient_filter_status_default = "all"
        self.patient_filter_date_default = datetime.now().strftime("%Y-%m-%d")
        self.stats_filter_department_default = ""
        self.stats_filter_date_from_default = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        self.stats_filter_date_to_default = datetime.now().strftime("%Y-%m-%d")
        self.watchlist_history_hours_default = 24
        self.watchlist_history_mode_default = "Toate"
        self.watchlist_history_sort_column = "delta"
        self.watchlist_history_sort_desc = True
        self.dashboard_refresh_debounce_seconds = 0.8
        self.export_debounce_seconds = 0.9
        self.quick_export_debounce_seconds = 1.2
        self._dashboard_refresh_last_click_ts = 0.0
        self._action_last_run_ts: Dict[str, float] = {}
        self._debounce_feedback_job: Optional[str] = None
        self._debounce_feedback_restore: Optional[Tuple[Any, str]] = None
        self.backup_job: Optional[str] = None
        self.last_settings_import_report = (self.db.get_setting("LAST_SETTINGS_IMPORT_REPORT", "") or "").strip()
        self._load_runtime_settings()

        self.current_patient_id: Optional[int] = None
        self.ai_busy = False
        self.visit_map: Dict[str, Dict[str, Any]] = {}
        self.admission_map: Dict[str, Dict[str, Any]] = {}
        self.order_map: Dict[str, Dict[str, Any]] = {}
        self.vitals_map: Dict[str, Dict[str, Any]] = {}
        self.booking_map: Dict[str, Dict[str, Any]] = {}
        self.transfer_map: Dict[str, Dict[str, Any]] = {}
        self.billing_map: Dict[str, Dict[str, Any]] = {}
        self.dashboard_admission_map: Dict[str, Dict[str, Any]] = {}
        self.dashboard_order_map: Dict[str, Dict[str, Any]] = {}
        self.dashboard_alert_map: Dict[str, Dict[str, Any]] = {}
        self.dashboard_watchlist_map: Dict[str, Dict[str, Any]] = {}
        self.dashboard_watchlist_snapshot_ts: Optional[str] = None
        self.dashboard_watchlist_trend_rows: List[Dict[str, Any]] = []
        self.watchlist_history_sort_column = str(getattr(self, "watchlist_history_sort_column", "delta"))
        self.watchlist_history_sort_desc = bool(getattr(self, "watchlist_history_sort_desc", True))
        self.users_map: Dict[str, Dict[str, Any]] = {}
        self.audit_map: Dict[str, Dict[str, Any]] = {}
        self.stats_daily_data: List[Dict[str, Any]] = []
        self.stats_weekly_data: List[Dict[str, Any]] = []
        self.stats_operational_data: List[Dict[str, Any]] = []
        self.stats_operational_by_department_data: List[Dict[str, Any]] = []
        self.stats_watchlist_export_perf_data: List[Dict[str, Any]] = []

        self.root.title(f"{DEFAULT_HOSPITAL_NAME} - Sistem Clinic")
        self.root.geometry("1320x820")
        self.root.minsize(1120, 700)

        self._build_ui()
        self.refresh_ai_status()
        self.refresh_patients()
        self.refresh_dashboard()
        if self._has_role("admin", "medic", "receptie"):
            self.refresh_statistics()
        if self._has_role("admin", "medic"):
            self.refresh_audit()
        if self._has_role("admin"):
            self.refresh_users()
        self.new_patient()
        self._init_alert_monitoring()
        self._init_backup_scheduler()

    def _setting_raw(self, key: str, env_name: str, default: str) -> str:
        env_value = (os.getenv(env_name) or default)

    @staticmethod
    def _to_int(value: str, default: int, min_value: Optional[int] = None) -> int:
        try:
            parsed = int((value or "").strip() or default)
        except Exception:
            parsed = default
        if min_value is not None:
            parsed = max(min_value, parsed)

    @staticmethod
    def _to_float(value: str, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
        try:
            parsed = float((value or "").strip() or default)
        except Exception:
            parsed = default
        if min_value is not None:
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    @staticmethod
    def _parse_csv_options(value: str, fallback_csv: str = "") -> List[str]:
        raw = (value or "").strip() or (fallback_csv or "")
        items = [p.strip() for p in raw.split(",") if p.strip()]
        out: List[str] = []
        seen = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @staticmethod
    def _normalize_capacity_overrides(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        chunks = [c.strip() for c in re.split(r"[;\n]+", text) if c.strip()]
        out: List[str] = []
        seen = set()
        for chunk in chunks:
            if "=" not in chunk or "/" not in chunk:
                raise ValueError("Format invalid pentru override. Foloseste: Sectie/Salon=Numar")
            left, right = chunk.split("=", 1)
            left = left.strip()
            right = right.strip()
            if "/" not in left:
                raise ValueError("Format invalid pentru override. Foloseste: Sectie/Salon=Numar")
            dep, ward = [p.strip() for p in left.split("/", 1)]
            if not dep or not ward:
                raise ValueError("Sectia si salonul sunt obligatorii in override.")
            try:
                cap = max(1, int(right))
            except Exception:
                raise ValueError("Capacitatea trebuie sa fie numar intreg >= 1.")
            key = f"{dep.lower()}|{ward.lower()}"
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{dep}/{ward}={cap}")
        return ";".join(out)

    def _refresh_ai_model_combobox_values(self) -> None:
        if not hasattr(self, "settings_text_vars"):
            return
        model = (self.settings_text_vars.get("OPENAI_MODEL").get() or "").strip()
        csv_options = (self.settings_text_vars.get("AI_MODEL_OPTIONS").get() or "").strip()
        options = self._parse_csv_options(csv_options, DEFAULT_AI_MODEL_OPTIONS)
        if model and model not in options:
            options.insert(0, model)
        if not options:
            options = [DEFAULT_MODEL]
        if hasattr(self, "ai_model_combobox") and self.ai_model_combobox is not None:
            self.ai_model_combobox.configure(values=tuple(options))

    @staticmethod
    def _parse_ai_profile_presets(value: str, fallback: str = "") -> List[Dict[str, str]]:
        raw = (value or "").strip() or (fallback or "")
        out: List[Dict[str, str]] = []
        seen = set()
        for chunk in [p.strip() for p in raw.split(";") if p.strip()]:
            parts = [p.strip() for p in chunk.split("|")]
            if len(parts) < 2:
                continue
            name = parts[0] or "Profil"
            model = parts[1] or DEFAULT_MODEL
            temp_raw = parts[2] if len(parts) > 2 else "0.2"
            try:
                temp = max(0.0, min(1.0, float(temp_raw or "0.2")))
            except Exception:
                temp = 0.2
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "model": model, "temperature": str(temp)})
        if not out:
            out = [
                {"name": "Balanced", "model": DEFAULT_MODEL, "temperature": "0.2"},
            ]
        return out

    @staticmethod
    def _serialize_ai_profile_presets(profiles: List[Dict[str, str]]) -> str:
        chunks: List[str] = []
        for profile in profiles:
            name = (profile.get("name") or "").strip()
            model = (profile.get("model") or "").strip()
            temp = (profile.get("temperature") or "").strip() or "0.2"
            if not name or not model:
                continue
            chunks.append(f"{name}|{model}|{temp}")
        return ";".join(chunks)

    def _render_ai_profile_buttons(self) -> None:
        if not hasattr(self, "ai_profiles_frame"):
            return
        for child in self.ai_profiles_frame.winfo_children():
            child.destroy()

        ttk.Label(self.ai_profiles_frame, text="Profil rapid:").pack(side=LEFT, padx=(0, 6))
        if hasattr(self, "settings_text_vars") and "AI_PROFILE_PRESETS" in self.settings_text_vars:
            profiles = self._parse_ai_profile_presets(
                self.settings_text_vars["AI_PROFILE_PRESETS"].get(),
                DEFAULT_AI_PROFILE_PRESETS,
            )
        else:
            profiles = list(getattr(self, "ai_profile_presets", [])) or self._parse_ai_profile_presets(
                DEFAULT_AI_PROFILE_PRESETS,
                DEFAULT_AI_PROFILE_PRESETS,
            )

        for idx, profile in enumerate(profiles):
            name = profile.get("name", "Profil")
            ttk.Button(
                self.ai_profiles_frame,
                text=name,
                command=lambda n=name: self.apply_ai_profile(n),
            ).pack(side=LEFT, padx=(0 if idx == 0 else 6, 0))

    def copy_ai_profile_presets_example(self) -> None:
        example = "Rapid|gpt-5-nano|0.1;Balanced|gpt-5-mini|0.2;Reasoning|gpt-5|0.1;Strict|gpt-5|0.0"
        try:
            self._set_clipboard_text(example)
            self.settings_hint_var.set("Exemplul pentru profiluri AI a fost copiat in clipboard.")
            messagebox.showinfo("Setari", "Exemplul pentru AI_PROFILE_PRESETS a fost copiat.")
        except Exception:
            self.settings_hint_var.set("Nu am putut copia in clipboard. Poti copia manual exemplul afisat.")

    def reset_ai_profile_presets_default(self) -> None:
        if "AI_PROFILE_PRESETS" not in self.settings_text_vars:
            return
        self.settings_text_vars["AI_PROFILE_PRESETS"].set(DEFAULT_AI_PROFILE_PRESETS)
        self._render_ai_profile_buttons()
        self.settings_hint_var.set("Profilurile AI au fost resetate la valorile implicite. Salveaza pentru persistare.")

    def apply_ai_profile(self, profile_name: str) -> None:
        profiles = self._parse_ai_profile_presets(
            self.settings_text_vars.get("AI_PROFILE_PRESETS").get() if hasattr(self, "settings_text_vars") else "",
            DEFAULT_AI_PROFILE_PRESETS,
        )
        preset = next((p for p in profiles if (p.get("name", "").lower() == profile_name.lower())), None)
        if not preset:
            return
        model = (preset.get("model") or "").strip() or DEFAULT_MODEL
        temperature = (preset.get("temperature") or "0.2").strip() or "0.2"
        self.settings_text_vars["OPENAI_MODEL"].set(model)
        self.settings_text_vars["AI_TEMPERATURE"].set(temperature)
        options = self._parse_csv_options(self.settings_text_vars["AI_MODEL_OPTIONS"].get(), DEFAULT_AI_MODEL_OPTIONS)
        if model not in options:
            options.insert(0, model)
            self.settings_text_vars["AI_MODEL_OPTIONS"].set(",".join(options))
        self._refresh_ai_model_combobox_values()
        self.settings_hint_var.set(f"Profil AI selectat: {profile_name}. Salveaza pentru aplicare persistenta.")

    def apply_debounce_preset(self, preset_name: str) -> None:
        if not hasattr(self, "settings_text_vars"):
            return
        key = (preset_name or "").strip().lower()
        selected_name = ""
        values: Optional[Tuple[float, float, float]] = None
        for name, preset_values in DEBOUNCE_PRESETS.items():
            if name.lower() == key:
                selected_name = name
                values = preset_values
                break
        if values is None:
            return
        refresh_s, export_s, quick_s = values

        self.settings_text_vars["DASHBOARD_REFRESH_DEBOUNCE_SECONDS"].set(self._format_debounce_seconds(refresh_s))
        self.settings_text_vars["EXPORT_DEBOUNCE_SECONDS"].set(self._format_debounce_seconds(export_s))
        self.settings_text_vars["QUICK_EXPORT_DEBOUNCE_SECONDS"].set(self._format_debounce_seconds(quick_s))
        self._refresh_debounce_preset_status()
        if hasattr(self, "settings_hint_var"):
            self.settings_hint_var.set(
                "Preset debounce aplicat: "
                f"{selected_name} (refresh={self._format_debounce_seconds(refresh_s)}s, "
                f"export={self._format_debounce_seconds(export_s)}s, rapid={self._format_debounce_seconds(quick_s)}s). "
                "Apasa Salveaza setari pentru persistare."
            )

    @staticmethod
    def _format_debounce_seconds(value: float) -> str:
        return (f"{float(value):.2f}").rstrip("0").rstrip(".")

    def _current_debounce_preset_name(self) -> str:
        if not hasattr(self, "settings_text_vars"):
            return "-"
        refresh_s = self._to_float(
            self.settings_text_vars.get("DASHBOARD_REFRESH_DEBOUNCE_SECONDS").get() if "DASHBOARD_REFRESH_DEBOUNCE_SECONDS" in self.settings_text_vars else "0.8",
            0.8,
            0.1,
            10.0,
        )
        export_s = self._to_float(
            self.settings_text_vars.get("EXPORT_DEBOUNCE_SECONDS").get() if "EXPORT_DEBOUNCE_SECONDS" in self.settings_text_vars else "0.9",
            0.9,
            0.1,
            10.0,
        )
        quick_s = self._to_float(
            self.settings_text_vars.get("QUICK_EXPORT_DEBOUNCE_SECONDS").get() if "QUICK_EXPORT_DEBOUNCE_SECONDS" in self.settings_text_vars else "1.2",
            1.2,
            0.1,
            15.0,
        )
        for name, (r, e, q) in DEBOUNCE_PRESETS.items():
            if (
                abs(refresh_s - r) <= DEBOUNCE_PRESET_TOLERANCE
                and abs(export_s - e) <= DEBOUNCE_PRESET_TOLERANCE
                and abs(quick_s - q) <= DEBOUNCE_PRESET_TOLERANCE
            ):
                return name
        return "Custom"

    def _refresh_debounce_preset_status(self) -> None:
        preset_name = self._current_debounce_preset_name()
        if hasattr(self, "debounce_preset_status_var"):
            self.debounce_preset_status_var.set(f"Preset activ: {preset_name}")
        if hasattr(self, "debounce_preset_status_label"):
            try:
                color = "#b45309" if preset_name == "Custom" else "#166534"
                self.debounce_preset_status_label.configure(foreground=color)
            except Exception:
                pass

    def _on_debounce_status_hover_enter(self, _event: Any) -> None:
        if not hasattr(self, "settings_hint_var"):
            return
        self._settings_hint_before_hover = str(self.settings_hint_var.get() or "")
        self.settings_hint_var.set(
            f"Preset debounce: potrivire la Â±{DEBOUNCE_PRESET_TOLERANCE:.2f}s fata de profilurile Conservator/Echilibrat/Rapid; altfel apare Custom."
        )

    def _on_debounce_status_hover_leave(self, _event: Any) -> None:
        if not hasattr(self, "settings_hint_var"):
            return
        previous = str(getattr(self, "_settings_hint_before_hover", "") or "")
        if previous:
            self.settings_hint_var.set(previous)

    @staticmethod
    def _to_bool(value: str, default: bool = False) -> bool:
        text = (value or "").strip().lower()
        if not text:
            return default
        return text not in {"0", "false", "no", "off"}

    def _load_runtime_settings(self) -> None:
        self.alert_poll_seconds = self._to_int(
            self._setting_raw("ALERT_POLL_SECONDS", "ALERT_POLL_SECONDS", "45"),
            45,
            15,
        )
        self.alert_escalation_minutes = self._to_int(
            self._setting_raw("ALERT_ESCALATION_MINUTES", "ALERT_ESCALATION_MINUTES", "10"),
            10,
            1,
        )
        self.alert_escalation_cooldown_seconds = self._to_int(
            self._setting_raw("ALERT_ESCALATION_COOLDOWN_SECONDS", "ALERT_ESCALATION_COOLDOWN_SECONDS", "600"),
            600,
            60,
        )

        self.notify_enabled = self._to_bool(
            self._setting_raw("ALERT_NOTIFY_ENABLED", "ALERT_NOTIFY_ENABLED", "1"),
            True,
        )
        self.notify_cooldown_seconds = self._to_int(
            self._setting_raw("ALERT_NOTIFY_COOLDOWN_SECONDS", "ALERT_NOTIFY_COOLDOWN_SECONDS", "120"),
            120,
            0,
        )
        self.notify_telegram_token = self._setting_raw("ALERT_TELEGRAM_BOT_TOKEN", "ALERT_TELEGRAM_BOT_TOKEN", "")
        self.notify_telegram_chat_id = self._setting_raw("ALERT_TELEGRAM_CHAT_ID", "ALERT_TELEGRAM_CHAT_ID", "")
        self.notify_webhook_url = self._setting_raw("ALERT_WEBHOOK_URL", "ALERT_WEBHOOK_URL", "")
        self.notify_email_from = self._setting_raw("ALERT_EMAIL_FROM", "ALERT_EMAIL_FROM", "")
        self.notify_email_to = [
            p.strip()
            for p in self._setting_raw("ALERT_EMAIL_TO", "ALERT_EMAIL_TO", "").split(",")
            if p.strip()
        ]
        self.notify_smtp_host = self._setting_raw("ALERT_SMTP_HOST", "ALERT_SMTP_HOST", "")
        self.notify_smtp_port = self._to_int(
            self._setting_raw("ALERT_SMTP_PORT", "ALERT_SMTP_PORT", "587"),
            587,
            1,
        )
        self.notify_smtp_user = self._setting_raw("ALERT_SMTP_USER", "ALERT_SMTP_USER", "")
        self.notify_smtp_pass = self._setting_raw("ALERT_SMTP_PASS", "ALERT_SMTP_PASS", "")
        self.dashboard_refresh_debounce_seconds = self._to_float(
            self._setting_raw(
                "DASHBOARD_REFRESH_DEBOUNCE_SECONDS",
                "DASHBOARD_REFRESH_DEBOUNCE_SECONDS",
                str(getattr(self, "dashboard_refresh_debounce_seconds", 0.8)),
            ),
            0.8,
            0.1,
            10.0,
        )
        self.export_debounce_seconds = self._to_float(
            self._setting_raw(
                "EXPORT_DEBOUNCE_SECONDS",
                "EXPORT_DEBOUNCE_SECONDS",
                str(getattr(self, "export_debounce_seconds", 0.9)),
            ),
            0.9,
            0.1,
            10.0,
        )
        self.quick_export_debounce_seconds = self._to_float(
            self._setting_raw(
                "QUICK_EXPORT_DEBOUNCE_SECONDS",
                "QUICK_EXPORT_DEBOUNCE_SECONDS",
                str(getattr(self, "quick_export_debounce_seconds", 1.2)),
            ),
            1.2,
            0.1,
            15.0,
        )
        self.handoff_last_action_key = self._setting_raw("HANDOFF_LAST_ACTION", "HANDOFF_LAST_ACTION", "")
        self.handoff_last_action_ts = self._setting_raw("HANDOFF_LAST_ACTION_TS", "HANDOFF_LAST_ACTION_TS", "")
        self.handoff_recent_actions = self._parse_handoff_recent_actions(
            self._setting_raw("HANDOFF_RECENT_ACTIONS", "HANDOFF_RECENT_ACTIONS", "[]")
        )
        self.handoff_status_filter_mode = self._normalize_handoff_status_filter_mode(
            self._setting_raw("HANDOFF_STATUS_FILTER_MODE", "HANDOFF_STATUS_FILTER_MODE", "all")
        )
        self.handoff_compact_mode_default = self._to_bool(
            self._setting_raw(
                "HANDOFF_COMPACT_MODE",
                "HANDOFF_COMPACT_MODE",
                "1" if getattr(self, "handoff_compact_mode_default", False) else "0",
            ),
            False,
        )

        self.backup_enabled = self._to_bool(
            self._setting_raw("AUTO_BACKUP_ENABLED", "AUTO_BACKUP_ENABLED", "1"),
            True,
        )
        self.backup_interval_minutes = self._to_int(
            self._setting_raw("AUTO_BACKUP_INTERVAL_MINUTES", "AUTO_BACKUP_INTERVAL_MINUTES", "360"),
            360,
            10,
        )
        self.backup_retention_days = self._to_int(
            self._setting_raw("AUTO_BACKUP_RETENTION_DAYS", "AUTO_BACKUP_RETENTION_DAYS", "14"),
            14,
            1,
        )
        self.discharge_require_final_decont = self._to_bool(
            self._setting_raw(
                "DISCHARGE_REQUIRE_FINAL_DECONT",
                "DISCHARGE_REQUIRE_FINAL_DECONT",
                "1" if getattr(self, "discharge_require_final_decont", False) else "0",
            ),
            False,
        )
        self.discharge_require_summary = self._to_bool(
            self._setting_raw(
                "DISCHARGE_REQUIRE_SUMMARY",
                "DISCHARGE_REQUIRE_SUMMARY",
                "1" if getattr(self, "discharge_require_summary", False) else "0",
            ),
            False,
        )
        self.care_ward_capacity_default = self._to_int(
            self._setting_raw("CARE_WARD_CAPACITY_DEFAULT", "CARE_WARD_CAPACITY_DEFAULT", "4"),
            4,
            1,
        )
        self.care_ward_capacity_overrides = self._setting_raw(
            "CARE_WARD_CAPACITY_OVERRIDES",
            "CARE_WARD_CAPACITY_OVERRIDES",
            "",
        )
        self.operational_backlog_alert_threshold = self._to_int(
            self._setting_raw("OPERATIONAL_BACKLOG_ALERT_THRESHOLD", "OPERATIONAL_BACKLOG_ALERT_THRESHOLD", "5"),
            5,
            1,
        )
        self.watchlist_score_high_threshold = self._to_int(
            self._setting_raw("WATCHLIST_SCORE_HIGH_THRESHOLD", "WATCHLIST_SCORE_HIGH_THRESHOLD", "90"),
            90,
            1,
        )
        self.watchlist_score_medium_threshold = self._to_int(
            self._setting_raw("WATCHLIST_SCORE_MEDIUM_THRESHOLD", "WATCHLIST_SCORE_MEDIUM_THRESHOLD", "60"),
            60,
            1,
        )
        max_medium = self.watchlist_score_high_threshold - 1 if self.watchlist_score_high_threshold > 1 else 1
        if self.watchlist_score_medium_threshold > max_medium:
            self.watchlist_score_medium_threshold = max_medium
        self.watchlist_weight_triage_1 = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_TRIAGE_1", "WATCHLIST_WEIGHT_TRIAGE_1", "60"),
            60,
            0,
        )
        self.watchlist_weight_triage_2 = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_TRIAGE_2", "WATCHLIST_WEIGHT_TRIAGE_2", "40"),
            40,
            0,
        )
        self.watchlist_weight_triage_3 = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_TRIAGE_3", "WATCHLIST_WEIGHT_TRIAGE_3", "20"),
            20,
            0,
        )
        self.watchlist_weight_triage_4_plus = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_TRIAGE_4_PLUS", "WATCHLIST_WEIGHT_TRIAGE_4_PLUS", "5"),
            5,
            0,
        )
        self.watchlist_weight_alert_unack = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_ALERT_UNACK", "WATCHLIST_WEIGHT_ALERT_UNACK", "25"),
            25,
            0,
        )
        self.watchlist_weight_alert_critical = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_ALERT_CRITICAL", "WATCHLIST_WEIGHT_ALERT_CRITICAL", "15"),
            15,
            0,
        )
        self.watchlist_weight_order_stat = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_ORDER_STAT", "WATCHLIST_WEIGHT_ORDER_STAT", "20"),
            20,
            0,
        )
        self.watchlist_weight_order_urgent = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_ORDER_URGENT", "WATCHLIST_WEIGHT_ORDER_URGENT", "10"),
            10,
            0,
        )
        self.watchlist_weight_order_in_progress = self._to_int(
            self._setting_raw("WATCHLIST_WEIGHT_ORDER_IN_PROGRESS", "WATCHLIST_WEIGHT_ORDER_IN_PROGRESS", "5"),
            5,
            0,
        )
        self.watchlist_history_hours_default = self._to_int(
            self._setting_raw("WATCHLIST_HISTORY_HOURS", "WATCHLIST_HISTORY_HOURS", "24"),
            24,
            1,
        )
        self.watchlist_history_hours_default = max(1, min(24 * 30, self.watchlist_history_hours_default))
        history_mode_raw = self._setting_raw("WATCHLIST_HISTORY_MODE", "WATCHLIST_HISTORY_MODE", "Toate").strip().lower()
        self.watchlist_history_mode_default = "Doar cresteri" if "crest" in history_mode_raw else "Toate"
        sort_column_raw = self._setting_raw("WATCHLIST_HISTORY_SORT_COLUMN", "WATCHLIST_HISTORY_SORT_COLUMN", "delta").strip().lower()
        self.watchlist_history_sort_column = (
            sort_column_raw if sort_column_raw in {"delta", "score_now", "patient", "mrn"} else "delta"
        )
        sort_desc_default = "1" if self.watchlist_history_sort_column in {"delta", "score_now"} else "0"
        self.watchlist_history_sort_desc = self._to_bool(
            self._setting_raw("WATCHLIST_HISTORY_SORT_DESC", "WATCHLIST_HISTORY_SORT_DESC", sort_desc_default),
            self.watchlist_history_sort_column in {"delta", "score_now"},
        )
        self.dashboard_filter_department_default = self._setting_raw(
            "DASHBOARD_FILTER_DEPARTMENT",
            "DASHBOARD_FILTER_DEPARTMENT",
            "",
        )
        dashboard_date_raw = self._setting_raw(
            "DASHBOARD_OPERATIONAL_DATE",
            "DASHBOARD_OPERATIONAL_DATE",
            self.dashboard_operational_date_default,
        )
        try:
            datetime.strptime(dashboard_date_raw, "%Y-%m-%d")
            self.dashboard_operational_date_default = dashboard_date_raw
        except Exception:
            self.dashboard_operational_date_default = datetime.now().strftime("%Y-%m-%d")
        patient_filter_status_raw = self._setting_raw(
            "PATIENT_STATUS_FILTER",
            "PATIENT_STATUS_FILTER",
            self.patient_filter_status_default,
        ).strip().lower()
        valid_patient_filters = {
            "all",
            "scheduled_admission",
            "active_admission",
            "scheduled_discharge",
            "discharged_no_debrief",
            "discharged_on_date",
        }
        self.patient_filter_status_default = (
            patient_filter_status_raw if patient_filter_status_raw in valid_patient_filters else "all"
        )
        patient_filter_date_raw = self._setting_raw(
            "PATIENT_STATUS_DATE",
            "PATIENT_STATUS_DATE",
            self.patient_filter_date_default,
        )
        try:
            datetime.strptime(patient_filter_date_raw, "%Y-%m-%d")
            self.patient_filter_date_default = patient_filter_date_raw
        except Exception:
            self.patient_filter_date_default = datetime.now().strftime("%Y-%m-%d")
        self.stats_filter_department_default = self._setting_raw(
            "STATS_FILTER_DEPARTMENT",
            "STATS_FILTER_DEPARTMENT",
            "",
        )
        stats_from_raw = self._setting_raw(
            "STATS_FILTER_DATE_FROM",
            "STATS_FILTER_DATE_FROM",
            self.stats_filter_date_from_default,
        )
        stats_to_raw = self._setting_raw(
            "STATS_FILTER_DATE_TO",
            "STATS_FILTER_DATE_TO",
            self.stats_filter_date_to_default,
        )
        try:
            datetime.strptime(stats_from_raw, "%Y-%m-%d")
            self.stats_filter_date_from_default = stats_from_raw
        except Exception:
            self.stats_filter_date_from_default = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        try:
            datetime.strptime(stats_to_raw, "%Y-%m-%d")
            self.stats_filter_date_to_default = stats_to_raw
        except Exception:
            self.stats_filter_date_to_default = datetime.now().strftime("%Y-%m-%d")

        self.ai_enabled = self._to_bool(
            self._setting_raw("AI_ENABLED", "AI_ENABLED", "1"),
            True,
        )
        self.ai_allowed_roles = [
            r.strip().lower()
            for r in self._setting_raw("AI_ALLOWED_ROLES", "AI_ALLOWED_ROLES", "admin,medic,asistent,receptie").split(",")
            if r.strip()
        ]
        self.ai_model = self._setting_raw("OPENAI_MODEL", "OPENAI_MODEL", DEFAULT_MODEL)
        ai_model_options_raw = self._setting_raw("AI_MODEL_OPTIONS", "AI_MODEL_OPTIONS", DEFAULT_AI_MODEL_OPTIONS)
        self.ai_model_options = self._parse_csv_options(ai_model_options_raw, DEFAULT_AI_MODEL_OPTIONS)
        if self.ai_model and self.ai_model not in self.ai_model_options:
            self.ai_model_options.insert(0, self.ai_model)
        ai_profile_presets_raw = self._setting_raw("AI_PROFILE_PRESETS", "AI_PROFILE_PRESETS", DEFAULT_AI_PROFILE_PRESETS)
        self.ai_profile_presets = self._parse_ai_profile_presets(ai_profile_presets_raw, DEFAULT_AI_PROFILE_PRESETS)
        self.ai_temperature = self._to_float(
            self._setting_raw("AI_TEMPERATURE", "AI_TEMPERATURE", "0.2"),
            0.2,
            0.0,
            1.0,
        )
        self.ai_max_output_tokens = self._to_int(
            self._setting_raw("AI_MAX_OUTPUT_TOKENS", "AI_MAX_OUTPUT_TOKENS", "900"),
            900,
            200,
        )
        self.ai_timeout_seconds = self._to_int(
            self._setting_raw("AI_TIMEOUT_SECONDS", "AI_TIMEOUT_SECONDS", "45"),
            45,
            10,
        )
        self.ai_system_prompt = self._setting_raw("AI_SYSTEM_PROMPT", "AI_SYSTEM_PROMPT", AIService.SYSTEM_PROMPT)
        self.ai_api_key = self._setting_raw("OPENAI_API_KEY", "OPENAI_API_KEY", "")
        self.ai_context_max_chars = self._to_int(
            self._setting_raw("AI_CONTEXT_MAX_CHARS", "AI_CONTEXT_MAX_CHARS", "12000"),
            12000,
            2000,
        )
        self.ai_history_messages = self._to_int(
            self._setting_raw("AI_HISTORY_MESSAGES", "AI_HISTORY_MESSAGES", "12"),
            12,
            2,
        )

        self.ai.configure(
            api_key=self.ai_api_key,
            model=self.ai_model,
            temperature=self.ai_temperature,
            max_output_tokens=self.ai_max_output_tokens,
            timeout_seconds=self.ai_timeout_seconds,
            system_prompt=self.ai_system_prompt,
        )

    def _ai_role_allowed(self) -> bool:
        role = normalize_role(self.current_user.get("role", ""))
        if role == "admin":
            return True
        if not self.ai_allowed_roles:
            return True
        return role in set(self.ai_allowed_roles)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=(8, 0))
        role_label = self.current_user.get("role", "")
        user_label = self.current_user.get("display_name", self.current_user.get("username", ""))
        ttk.Label(
            top,
            text=f"{DEFAULT_HOSPITAL_NAME} | Utilizator: {user_label} ({role_label})",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=LEFT)
        right_tools = ttk.Frame(top)
        right_tools.pack(side=RIGHT)
        self.guardrail_var = tk.StringVar(value="Mod spital activ: audit + fluxuri internare")
        ttk.Label(right_tools, textvariable=self.guardrail_var, foreground="#1d4ed8").pack(side=LEFT, padx=(0, 10))
        self.alert_status_var = tk.StringVar(value="Alerte critice: monitorizare activa")
        self.alert_status_label = tk.Label(right_tools, textvariable=self.alert_status_var, fg="#b91c1c")
        self.alert_status_label.pack(side=LEFT, padx=(0, 10))
        ttk.Button(right_tools, text="Muta alerte 5m", command=self.mute_alerts_5m).pack(side=LEFT, padx=(0, 10))
        ttk.Button(right_tools, text="Test notificari", command=self.test_external_notifications).pack(
            side=LEFT, padx=(0, 10)
        )
        ttk.Button(right_tools, text="Backup acum", command=self.create_manual_backup).pack(side=LEFT, padx=(0, 10))
        ttk.Button(right_tools, text="Restore backup", command=self.restore_backup_dialog).pack(side=LEFT, padx=(0, 10))
        ttk.Button(right_tools, text="Schimba parola", command=self.change_my_password).pack(side=LEFT)

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=350)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=3)

        self._build_patients_panel(left)
        self._build_right_panel(right)

    def _has_role(self, *allowed_roles: str) -> bool:
        role = normalize_role(self.current_user.get("role", ""))
        if role == "admin":
            return True
        allowed = {normalize_role(r) for r in allowed_roles}
        return role in allowed

    def _require_role(self, action_label: str, *allowed_roles: str) -> bool:
        if self._has_role(*allowed_roles):
            return True
        allowed = ", ".join(sorted({normalize_role(r) for r in allowed_roles}))
        messagebox.showerror("Acces restrictionat", f"Actiunea '{action_label}' necesita rol: {allowed}.")
        return False

    def _audit(self, action: str, details: str = "", patient_id: Optional[int] = None) -> None:
        try:
            self.db.add_audit_log(self.current_user.get("id"), patient_id, action, details)
            if self._has_role("admin", "medic") and hasattr(self, "audit_tree"):
                self.refresh_audit()
        except Exception:
            pass

    def _is_critical_alert_reasons(self, reason_text: str) -> bool:
        parts = [p.strip().lower() for p in (reason_text or "").split(",") if p.strip()]
        if len(parts) >= 2:
            return True
        for p in parts:
            if p.startswith(("spo2=", "resp=", "puls=")):
                return True
        return False

    def _init_alert_monitoring(self) -> None:
        try:
            initial = self.db.list_vital_alerts_dashboard(department="", hours=24, limit=1)
            self.alert_last_seen_id = int(initial[0]["id"]) if initial else 0
            self.alert_status_var.set(
                f"Alerte critice: monitorizare activa ({self.alert_poll_seconds}s)"
            )
            self.alert_status_label.config(fg="#b91c1c")
        except Exception:
            self.alert_last_seen_id = 0
            self.alert_status_var.set("Alerte critice: monitorizare indisponibila")
            self.alert_status_label.config(fg="#b91c1c")
        self._schedule_alert_poll()

    def _schedule_alert_poll(self) -> None:
        if self.alert_poll_job:
            try:
                self.root.after_cancel(self.alert_poll_job)
            except Exception:
                pass
            self.alert_poll_job = None
        self.alert_poll_job = self.root.after(self.alert_poll_seconds * 1000, self._poll_critical_alerts)

    def mute_alerts_5m(self) -> None:
        self.alert_muted_until = datetime.now() + timedelta(minutes=5)
        mute_text = self.alert_muted_until.strftime("%H:%M:%S")
        self.alert_status_var.set(f"Alerte critice: mutate pana la {mute_text}")
        self.alert_status_label.config(fg="#92400e")

    def _poll_critical_alerts(self) -> None:
        try:
            self.check_new_critical_alerts(show_popup=True)
            self.check_escalation_critical_alerts()
        finally:
            self._schedule_alert_poll()

    def check_new_critical_alerts(self, show_popup: bool = True) -> None:
        department = ""
        if hasattr(self, "dashboard_department_var"):
            department = self.dashboard_department_var.get().strip()
        alerts = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=200)
        if not alerts:
            if self.alert_muted_until and datetime.now() >= self.alert_muted_until:
                self.alert_muted_until = None
                self.alert_status_var.set(
                    f"Alerte critice: monitorizare activa ({self.alert_poll_seconds}s)"
                )
                self.alert_status_label.config(fg="#b91c1c")
            return

        max_id = max(int(a["id"]) for a in alerts)
        acked_ids = self.db.get_acknowledged_vital_ids([int(a["id"]) for a in alerts])
        new_alerts = [a for a in alerts if int(a["id"]) > self.alert_last_seen_id]
        self.alert_last_seen_id = max(self.alert_last_seen_id, max_id)
        critical_new = [
            a
            for a in new_alerts
            if self._is_critical_alert_reasons(a["reasons"]) and int(a["id"]) not in acked_ids
        ]

        if self.alert_muted_until:
            if datetime.now() < self.alert_muted_until:
                return
            self.alert_muted_until = None
            self.alert_status_var.set(f"Alerte critice: monitorizare activa ({self.alert_poll_seconds}s)")
            self.alert_status_label.config(fg="#b91c1c")

        if critical_new:
            self._dispatch_external_notifications(critical_new)

        if not critical_new or not show_popup:
            return

        preview_lines: List[str] = []
        for row in sorted(critical_new, key=lambda x: int(x["id"]))[:3]:
            preview_lines.append(
                f"- {row['last_name']} {row['first_name']} | {row.get('mrn') or '-'} | {row['reasons']}"
            )
        extra = len(critical_new) - len(preview_lines)
        body = "\n".join(preview_lines)
        if extra > 0:
            body += f"\n... si inca {extra} alerta(e)."
        message = "Alerte vitale critice noi:\n\n" + body
        self._audit(
            "critical_alert_popup",
            self._audit_details_from_pairs(("count", len(critical_new))),
        )
        self.alert_status_var.set(f"Alerte critice noi: {len(critical_new)}")
        self.alert_status_label.config(fg="#b91c1c")
        messagebox.showwarning("Alerte critice", message)

    def check_escalation_critical_alerts(self) -> None:
        if not self.notify_enabled or not self._notification_channels_configured():
            return
        if self.alert_muted_until and datetime.now() < self.alert_muted_until:
            return
        if self.alert_escalation_last_sent_at is not None:
            elapsed = (datetime.now() - self.alert_escalation_last_sent_at).total_seconds()
            if elapsed < self.alert_escalation_cooldown_seconds:
                return

        department = self.dashboard_department_var.get().strip() if hasattr(self, "dashboard_department_var") else ""
        alerts = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=1000)
        if not alerts:
            return

        acked_ids = self.db.get_acknowledged_vital_ids([int(a["id"]) for a in alerts])
        threshold = datetime.now() - timedelta(minutes=self.alert_escalation_minutes)
        escalation_alerts: List[Dict[str, Any]] = []
        for row in alerts:
            if int(row["id"]) in acked_ids:
                continue
            if not self._is_critical_alert_reasons(row.get("reasons", "")):
                continue
            try:
                rec_dt = datetime.strptime(str(row["recorded_at"]), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if rec_dt <= threshold:
                escalation_alerts.append(row)

        if not escalation_alerts:
            return

        self._dispatch_external_notifications(escalation_alerts, event_type="critical_vital_alert_escalation")
        self.alert_escalation_last_sent_at = datetime.now()
        self._audit(
            "critical_alert_escalation",
            self._audit_details_from_pairs(("count", len(escalation_alerts))),
        )
        self.alert_status_var.set(f"Escaladare alerte critice: {len(escalation_alerts)}")
        self.alert_status_label.config(fg="#b91c1c")

    def _notification_channels_configured(self) -> bool:
        has_telegram = bool(self.notify_telegram_token and self.notify_telegram_chat_id)
        has_webhook = bool(self.notify_webhook_url)
        has_email = bool(self.notify_smtp_host and self.notify_email_from and self.notify_email_to)
        return has_telegram or has_webhook or has_email

    def _build_external_alert_message(self, critical_alerts: List[Dict[str, Any]]) -> str:
        lines = [
            f"[{DEFAULT_HOSPITAL_NAME}] ALERTA VITALA CRITICA",
            f"Timp: {now_ts()}",
            f"Numar alerte: {len(critical_alerts)}",
            "",
        ]
        for row in critical_alerts[:5]:
            lines.append(
                f"- Pacient: {row['last_name']} {row['first_name']} | MRN: {row.get('mrn') or '-'} | "
                f"Timp: {row['recorded_at']} | Alerta: {row['reasons']}"
            )
        extra = len(critical_alerts) - min(5, len(critical_alerts))
        if extra > 0:
            lines.append(f"... si inca {extra} alerta(e).")
        return "\n".join(lines)

    def _dispatch_external_notifications(self, critical_alerts: List[Dict[str, Any]], event_type: str = "critical_vital_alert") -> None:
        if not self.notify_enabled:
            return
        if not self._notification_channels_configured():
            return
        if self.notify_busy:
            return
        if self.notify_last_sent_at is not None and self.notify_cooldown_seconds > 0:
            elapsed = (datetime.now() - self.notify_last_sent_at).total_seconds()
            if elapsed < self.notify_cooldown_seconds:
                return

        message = self._build_external_alert_message(critical_alerts)
        payload = {
            "event": event_type,
            "hospital": DEFAULT_HOSPITAL_NAME,
            "generated_at": now_ts(),
            "count": len(critical_alerts),
            "alerts": [
                {
                    "id": int(item["id"]),
                    "patient_id": int(item["patient_id"]),
                    "patient_name": f"{item['last_name']} {item['first_name']}",
                    "mrn": item.get("mrn") or "",
                    "recorded_at": item["recorded_at"],
                    "reasons": item["reasons"],
                    "notes": item.get("notes") or "",
                }
                for item in critical_alerts
            ],
            "message": message,
        }

        self.notify_busy = True
        thread = threading.Thread(
            target=self._send_external_notifications_worker,
            args=(message, payload),
            daemon=True,
        )
        thread.start()

    def _send_external_notifications_worker(self, message: str, payload: Dict[str, Any]) -> None:
        results: List[str] = []
        success_count = 0
        fail_count = 0

        if self.notify_telegram_token and self.notify_telegram_chat_id:
            ok, info = self._send_telegram_notification(message)
            results.append(self._format_notification_channel_result("telegram", ok, info))
            success_count += 1 if ok else 0
            fail_count += 0 if ok else 1

        if self.notify_webhook_url:
            ok, info = self._send_webhook_notification(payload)
            results.append(self._format_notification_channel_result("webhook", ok, info))
            success_count += 1 if ok else 0
            fail_count += 0 if ok else 1

        if self.notify_smtp_host and self.notify_email_from and self.notify_email_to:
            ok, info = self._send_email_notification(message)
            results.append(self._format_notification_channel_result("email", ok, info))
            success_count += 1 if ok else 0
            fail_count += 0 if ok else 1

        self.root.after(0, lambda: self._on_external_notifications_done(success_count, fail_count, results))

    def _init_backup_scheduler(self) -> None:
        if not self.backup_enabled:
            return
        self._schedule_backup_job(delay_seconds=30)

    def _schedule_backup_job(self, delay_seconds: Optional[int] = None) -> None:
        if self.backup_job:
            try:
                self.root.after_cancel(self.backup_job)
            except Exception:
                pass
            self.backup_job = None
        seconds = delay_seconds if delay_seconds is not None else self.backup_interval_minutes * 60
        self.backup_job = self.root.after(max(10, int(seconds)) * 1000, self._run_scheduled_backup)

    def _run_scheduled_backup(self) -> None:
        try:
            self._create_backup(trigger="auto")
        except Exception:
            pass
        finally:
            self._schedule_backup_job()

    def _prune_old_backups(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.backup_retention_days)
        for file_path in BACKUPS_DIR.glob("pacienti_ai_backup_*.db"):
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    file_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _create_backup(self, trigger: str = "manual") -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = BACKUPS_DIR / f"pacienti_ai_backup_{stamp}.db"
        self.db.create_backup_file(out_path)
        self._prune_old_backups()
        self._audit(
            "db_backup",
            self._audit_details_from_pairs(
                ("trigger", trigger),
                ("path", out_path),
            ),
        )
        return out_path

    def create_manual_backup(self) -> None:
        if not self._require_role("Backup baza date", "admin", "medic"):
            return
        try:
            out_path = self._create_backup(trigger="manual")
            messagebox.showinfo("Backup", f"Backup creat:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Backup", f"Nu am putut crea backup: {exc}")

    def restore_backup_dialog(self) -> None:
        if not self._require_role("Restore backup", "admin"):
            return
        backup_path = filedialog.askopenfilename(
            title="Selecteaza backup DB",
            initialdir=str(BACKUPS_DIR),
            filetypes=(("SQLite DB", "*.db"), ("Toate fisierele", "*.*")),
        )
        if not backup_path:
            return
        if not messagebox.askyesno(
            "Confirmare restore",
            "Restore va inlocui datele curente din aplicatie. Continui?",
        ):
            return
        try:
            self.db.restore_from_backup_file(Path(backup_path))
            self._audit(
                "db_restore",
                self._audit_details_from_pairs(("path", backup_path)),
            )
            self.refresh_patients()
            self.new_patient()
            self.refresh_operational_views()
            if self._has_role("admin", "medic"):
                self.refresh_audit()
            if self._has_role("admin"):
                self.refresh_users()
            messagebox.showinfo("Restore", "Restore finalizat cu succes.")
        except Exception as exc:
            messagebox.showerror("Restore", f"Restore esuat: {exc}")

    def _send_telegram_notification(self, message: str) -> tuple[bool, str]:
        try:
            url = f"https://api.telegram.org/bot{self.notify_telegram_token}/sendMessage"
            payload = urllib_parse.urlencode(
                {
                    "chat_id": self.notify_telegram_chat_id,
                    "text": message,
                    "disable_web_page_preview": "true",
                }
            ).encode("utf-8")
            req = urllib_request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib_request.urlopen(req, timeout=15) as resp:
                _ = resp.read()
            return True, "sent"
        except Exception as exc:
            return False, str(exc)

    def _send_webhook_notification(self, payload: Dict[str, Any]) -> tuple[bool, str]:
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib_request.Request(self.notify_webhook_url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib_request.urlopen(req, timeout=15) as resp:
                _ = resp.read()
            return True, "sent"
        except Exception as exc:
            return False, str(exc)

    def _send_email_notification(self, message: str) -> tuple[bool, str]:
        try:
            email_msg = EmailMessage()
            email_msg["Subject"] = f"[{DEFAULT_HOSPITAL_NAME}] Alerta vitala critica"
            email_msg["From"] = self.notify_email_from
            email_msg["To"] = ", ".join(self.notify_email_to)
            email_msg.set_content(message)

            with smtplib.SMTP(self.notify_smtp_host, self.notify_smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                if self.notify_smtp_port in (587, 25):
                    smtp.starttls()
                    smtp.ehlo()
                if self.notify_smtp_user:
                    smtp.login(self.notify_smtp_user, self.notify_smtp_pass)
                smtp.send_message(email_msg)
            return True, "sent"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _format_notification_channel_result(channel: str, ok: bool, info: str) -> str:
        return f"{str(channel or '').strip()}:{'ok' if ok else 'fail'}:{str(info or '').strip()}"

    @staticmethod
    def _normalize_notification_channels_detail(details: Any) -> str:
        if isinstance(details, (list, tuple)):
            return " | ".join([str(part or "").strip() for part in details if str(part or "").strip()]) or "-"
        return " | ".join([part.strip() for part in str(details or "").split(";") if part.strip()]) or "-"

    @staticmethod
    def _external_notification_audit_details(*, success_count: int, fail_count: int, channels_detail: str) -> str:
        return App._audit_details_from_pairs(
            ("success", success_count),
            ("fail", fail_count),
            ("channels", channels_detail),
        )

    def _on_external_notifications_done(self, success_count: int, fail_count: int, details: Any) -> None:
        self.notify_busy = False
        channels_detail = self._normalize_notification_channels_detail(details)
        if success_count > 0:
            self.notify_last_sent_at = datetime.now()
            self._audit(
                "external_alert_notification_sent",
                self._external_notification_audit_details(
                    success_count=success_count,
                    fail_count=fail_count,
                    channels_detail=channels_detail,
                ),
            )
            self.alert_status_var.set(
                f"Alerte critice: notificari externe trimise ({success_count} canal(e))"
            )
            self.alert_status_label.config(fg="#065f46")
            return
        if fail_count > 0:
            self._audit(
                "external_alert_notification_failed",
                self._external_notification_audit_details(
                    success_count=success_count,
                    fail_count=fail_count,
                    channels_detail=channels_detail,
                ),
            )
            self.alert_status_var.set("Alerte critice: notificari externe esuate")
            self.alert_status_label.config(fg="#b91c1c")

    def test_external_notifications(self) -> None:
        if not self._require_role("Test notificari externe", "admin", "medic", "asistent", "receptie"):
            return
        if not self.notify_enabled:
            messagebox.showinfo("Notificari", "ALERT_NOTIFY_ENABLED este dezactivat.")
            return
        if not self._notification_channels_configured():
            messagebox.showinfo(
                "Notificari",
                "Nu exista canale configurate. Seteaza Telegram, Webhook sau SMTP in variabilele de mediu.",
            )
            return
        fake_alert = {
            "id": 0,
            "patient_id": self.current_patient_id or 0,
            "first_name": "Pacient",
            "last_name": "Test",
            "mrn": "-",
            "recorded_at": now_ts(),
            "reasons": "spo2=88, puls=130",
            "notes": "Test notificare externa",
        }
        self.notify_last_sent_at = None
        self._dispatch_external_notifications([fake_alert])

    def _build_patients_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Pacienti", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 6))

        search_wrap = ttk.Frame(parent)
        search_wrap.pack(fill="x", pady=(0, 8))
        ttk.Label(search_wrap, text="Cauta:").pack(side=LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_patients())
        ttk.Entry(search_wrap, textvariable=self.search_var).pack(side=LEFT, fill="x", expand=True, padx=(6, 0))

        filters_wrap = ttk.Frame(parent)
        filters_wrap.pack(fill="x", pady=(0, 8))
        ttk.Label(filters_wrap, text="Status receptie:").pack(side=LEFT)
        self.patient_status_filter_map = {
            "Toti pacientii": "all",
            "Programati la internare (ziua selectata)": "scheduled_admission",
            "Pacienti internati": "active_admission",
            "Internat UPU": "active_upu",
            "Transferat": "transferred",
            "Programati la externare (ziua selectata)": "scheduled_discharge",
            "Externati fara decont final": "discharged_no_debrief",
            "Externat cu decont": "discharged_with_debrief",
            "Pacienti externati (ziua selectata)": "discharged_on_date",
        }
        default_status_key = str(getattr(self, "patient_filter_status_default", "all") or "all").strip().lower()
        default_status_label = next(
            (label for label, key in self.patient_status_filter_map.items() if key == default_status_key),
            "Toti pacientii",
        )
        self.patient_status_filter_var = tk.StringVar(value=default_status_label)
        ttk.Combobox(
            filters_wrap,
            textvariable=self.patient_status_filter_var,
            values=tuple(self.patient_status_filter_map.keys()),
            state="readonly",
            width=40,
        ).pack(side=LEFT, padx=(6, 6))
        self.patient_status_filter_var.trace_add("write", lambda *_: self.refresh_patients())
        ttk.Label(filters_wrap, text="Data (YYYY-MM-DD):").pack(side=LEFT)
        self.patient_status_date_var = tk.StringVar(value=str(getattr(self, "patient_filter_date_default", datetime.now().strftime("%Y-%m-%d"))))
        self.patient_status_date_var.trace_add("write", lambda *_: self.refresh_patients())
        ttk.Entry(filters_wrap, textvariable=self.patient_status_date_var, width=12).pack(side=LEFT, padx=(6, 0))
        ttk.Button(filters_wrap, text="Reset filtre receptie", command=self.reset_patient_filter_preferences).pack(side=LEFT, padx=(8, 0))

        tree_wrap = ttk.Frame(parent)
        tree_wrap.pack(fill=BOTH, expand=True)

        cols = ("name", "status", "phone", "email")
        self.patient_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=20)
        self.patient_tree.heading("name", text="Nume")
        self.patient_tree.heading("status", text="Status receptie")
        self.patient_tree.heading("phone", text="Telefon")
        self.patient_tree.heading("email", text="Email")
        self.patient_tree.column("name", width=180, anchor="w")
        self.patient_tree.column("status", width=170, anchor="w")
        self.patient_tree.column("phone", width=110, anchor="w")
        self.patient_tree.column("email", width=170, anchor="w")
        self.patient_tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.patient_tree.bind("<<TreeviewSelect>>", self.on_patient_select)

        scrollbar = ttk.Scrollbar(tree_wrap, orient=VERTICAL, command=self.patient_tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.patient_tree.configure(yscrollcommand=scrollbar.set)

        btns = ttk.Frame(parent)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Pacient nou", command=self.new_patient).pack(side=LEFT)
        ttk.Button(btns, text="Sterge pacient", command=self.delete_current_patient).pack(side=LEFT, padx=6)
        ttk.Button(btns, text="Reincarca", command=self.refresh_patients).pack(side=LEFT)

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=BOTH, expand=True)

        tab_dashboard = ttk.Frame(self.notebook)
        tab_stats = ttk.Frame(self.notebook)
        tab_patient = ttk.Frame(self.notebook)
        tab_visits = ttk.Frame(self.notebook)
        tab_admissions = ttk.Frame(self.notebook)
        tab_orders = ttk.Frame(self.notebook)
        tab_vitals = ttk.Frame(self.notebook)
        tab_ai = ttk.Frame(self.notebook)
        tab_users = ttk.Frame(self.notebook)
        tab_audit = ttk.Frame(self.notebook)
        tab_settings = ttk.Frame(self.notebook)
        self.tab_patient = tab_patient

        self.notebook.add(tab_dashboard, text="Dashboard")
        if self._has_role("admin", "medic", "receptie"):
            self.notebook.add(tab_stats, text="Statistici")
        self.notebook.add(tab_patient, text="Fisa pacient")
        self.notebook.add(tab_visits, text="Note clinice")
        self.notebook.add(tab_admissions, text="Internari")
        self.notebook.add(tab_orders, text="Ordine")
        self.notebook.add(tab_vitals, text="Vitale")
        self.notebook.add(tab_ai, text="Asistent AI")
        if self._has_role("admin", "medic"):
            self.notebook.add(tab_audit, text="Audit")
        if self._has_role("admin"):
            self.notebook.add(tab_users, text="Utilizatori")
            self.notebook.add(tab_settings, text="Setari")

        self._build_dashboard_tab(tab_dashboard)
        if self._has_role("admin", "medic", "receptie"):
            self._build_statistics_tab(tab_stats)
        self._build_patient_tab(tab_patient)
        self._build_visits_tab(tab_visits)
        self._build_admissions_tab(tab_admissions)
        self._build_orders_tab(tab_orders)
        self._build_vitals_tab(tab_vitals)
        self._build_ai_tab(tab_ai)
        if self._has_role("admin", "medic"):
            self._build_audit_tab(tab_audit)
        if self._has_role("admin"):
            self._build_users_tab(tab_users)
            self._build_settings_tab(tab_settings)

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        filters = ttk.Frame(frame)
        filters.pack(fill="x")
        ttk.Label(filters, text="Filtru sectie").pack(side=LEFT)
        self.dashboard_department_var = tk.StringVar(value=str(getattr(self, "dashboard_filter_department_default", "")))
        ttk.Entry(filters, textvariable=self.dashboard_department_var, width=22).pack(side=LEFT, padx=(6, 10))
        ttk.Label(filters, text="Data operationala").pack(side=LEFT)
        self.dashboard_operational_date_var = tk.StringVar(value=str(getattr(self, "dashboard_operational_date_default", datetime.now().strftime("%Y-%m-%d"))))
        ttk.Entry(filters, textvariable=self.dashboard_operational_date_var, width=12).pack(side=LEFT, padx=(6, 10))
        ttk.Button(filters, text="Refresh Dashboard", command=self.request_dashboard_refresh).pack(side=LEFT)
        ttk.Button(filters, text="Reset filtre", command=self.reset_dashboard_filter_preferences).pack(side=LEFT, padx=6)
        ttk.Button(filters, text="Reset dashboard+istoric", command=self.reset_dashboard_and_history_preferences).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Snapshot Watchlist", command=self.capture_watchlist_snapshot).pack(side=LEFT, padx=6)
        ttk.Button(filters, text="Export raport garda PDF", command=lambda: self.request_export_action("dashboard_report_pdf", self.export_dashboard_report_pdf)).pack(side=LEFT, padx=6)
        ttk.Button(filters, text="Export Morning Briefing PDF", command=lambda: self.request_export_action("dashboard_morning_briefing_pdf", self.export_dashboard_morning_briefing_pdf)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export Morning Briefing CSV", command=lambda: self.request_export_action("dashboard_morning_briefing_csv", self.export_dashboard_morning_briefing_csv_bundle)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export Handover Shift PDF", command=lambda: self.request_export_action("dashboard_handover_shift_pdf", self.export_dashboard_handover_shift_pdf)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export Handover Shift CSV", command=lambda: self.request_export_action("dashboard_handover_shift_csv", self.export_dashboard_handover_shift_csv_bundle)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export Watchlist PDF", command=lambda: self.request_export_action("dashboard_watchlist_pdf", self.export_dashboard_watchlist_pdf)).pack(side=LEFT, padx=6)
        ttk.Button(filters, text="Export Watchlist CSV", command=lambda: self.request_export_action("dashboard_watchlist_csv", self.export_dashboard_watchlist_csv)).pack(side=LEFT, padx=6)
        ttk.Button(filters, text="Export istoric watchlist PDF", command=lambda: self.request_export_action("dashboard_watchlist_history_pdf", self.export_dashboard_watchlist_history_pdf)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export istoric watchlist CSV", command=lambda: self.request_export_action("dashboard_watchlist_history_csv", self.export_dashboard_watchlist_history_csv)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export liste operationale CSV", command=lambda: self.request_export_action("dashboard_operational_csv", self.export_dashboard_operational_lists_csv)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(filters, text="Export liste operationale PDF", command=lambda: self.request_export_action("dashboard_operational_pdf", self.export_dashboard_operational_lists_pdf)).pack(
            side=LEFT, padx=6
        )

        kpi = ttk.LabelFrame(frame, text="Indicatori sectie")
        kpi.pack(fill="x", pady=(10, 8))
        self.kpi_active_var = tk.StringVar(value="Internari active: 0")
        self.kpi_triage_var = tk.StringVar(value="Triage 1-2: 0")
        self.kpi_orders_var = tk.StringVar(value="Ordine urgente: 0")
        self.kpi_alerts_var = tk.StringVar(value="Alerte vitale 24h: 0")
        ttk.Label(kpi, textvariable=self.kpi_active_var, font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=10, pady=6)
        ttk.Label(kpi, textvariable=self.kpi_triage_var, font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=10, pady=6)
        ttk.Label(kpi, textvariable=self.kpi_orders_var, font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=10, pady=6)
        ttk.Label(kpi, textvariable=self.kpi_alerts_var, font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=10, pady=6)

        admissions_wrap = ttk.LabelFrame(frame, text="Pacienti internati activ")
        admissions_wrap.pack(fill=BOTH, expand=True, pady=(0, 8))
        cols = ("mrn", "patient", "triage", "dept", "ward", "bed", "clinician", "admitted")
        self.dashboard_admission_tree = ttk.Treeview(admissions_wrap, columns=cols, show="headings", height=7)
        self.dashboard_admission_tree.heading("mrn", text="MRN")
        self.dashboard_admission_tree.heading("patient", text="Pacient")
        self.dashboard_admission_tree.heading("triage", text="Triage")
        self.dashboard_admission_tree.heading("dept", text="Sectie")
        self.dashboard_admission_tree.heading("ward", text="Salon")
        self.dashboard_admission_tree.heading("bed", text="Pat")
        self.dashboard_admission_tree.heading("clinician", text="Medic curant")
        self.dashboard_admission_tree.heading("admitted", text="Admis la")
        self.dashboard_admission_tree.column("mrn", width=120, anchor="w")
        self.dashboard_admission_tree.column("patient", width=220, anchor="w")
        self.dashboard_admission_tree.column("triage", width=60, anchor="center")
        self.dashboard_admission_tree.column("dept", width=120, anchor="w")
        self.dashboard_admission_tree.column("ward", width=80, anchor="w")
        self.dashboard_admission_tree.column("bed", width=70, anchor="w")
        self.dashboard_admission_tree.column("clinician", width=160, anchor="w")
        self.dashboard_admission_tree.column("admitted", width=145, anchor="w")
        self.dashboard_admission_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.dashboard_admission_tree.tag_configure("triage_critical", background="#fee2e2")
        self.dashboard_admission_tree.tag_configure("triage_high", background="#fff7ed")
        ttk.Button(admissions_wrap, text="Deschide pacient selectat", command=self.open_patient_from_dashboard_admission).pack(
            anchor="e", padx=6, pady=(0, 6)
        )

        orders_wrap = ttk.LabelFrame(frame, text="Ordine urgente")
        orders_wrap.pack(fill=BOTH, expand=True, pady=(0, 8))
        cols = ("patient", "mrn", "type", "priority", "status", "ordered_at", "text")
        self.dashboard_order_tree = ttk.Treeview(orders_wrap, columns=cols, show="headings", height=6)
        self.dashboard_order_tree.heading("patient", text="Pacient")
        self.dashboard_order_tree.heading("mrn", text="MRN")
        self.dashboard_order_tree.heading("type", text="Tip")
        self.dashboard_order_tree.heading("priority", text="Prioritate")
        self.dashboard_order_tree.heading("status", text="Status")
        self.dashboard_order_tree.heading("ordered_at", text="Ordonat la")
        self.dashboard_order_tree.heading("text", text="Descriere")
        self.dashboard_order_tree.column("patient", width=180, anchor="w")
        self.dashboard_order_tree.column("mrn", width=110, anchor="w")
        self.dashboard_order_tree.column("type", width=90, anchor="w")
        self.dashboard_order_tree.column("priority", width=80, anchor="w")
        self.dashboard_order_tree.column("status", width=90, anchor="w")
        self.dashboard_order_tree.column("ordered_at", width=145, anchor="w")
        self.dashboard_order_tree.column("text", width=420, anchor="w")
        self.dashboard_order_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.dashboard_order_tree.tag_configure("order_stat", background="#fee2e2")
        self.dashboard_order_tree.tag_configure("order_urgent", background="#fff7ed")
        self.dashboard_order_tree.tag_configure("order_in_progress", foreground="#1d4ed8")
        ttk.Button(orders_wrap, text="Deschide pacient selectat", command=self.open_patient_from_dashboard_order).pack(
            anchor="e", padx=6, pady=(0, 6)
        )

        alerts_wrap = ttk.LabelFrame(frame, text="Alerte vitale (ultimele 24h)")
        alerts_wrap.pack(fill=BOTH, expand=True)
        cols = ("patient", "mrn", "time", "reasons", "notes")
        self.dashboard_alert_tree = ttk.Treeview(alerts_wrap, columns=cols, show="headings", height=6)
        self.dashboard_alert_tree.heading("patient", text="Pacient")
        self.dashboard_alert_tree.heading("mrn", text="MRN")
        self.dashboard_alert_tree.heading("time", text="Timestamp")
        self.dashboard_alert_tree.heading("reasons", text="Alerte")
        self.dashboard_alert_tree.heading("notes", text="Note")
        self.dashboard_alert_tree.column("patient", width=180, anchor="w")
        self.dashboard_alert_tree.column("mrn", width=110, anchor="w")
        self.dashboard_alert_tree.column("time", width=145, anchor="w")
        self.dashboard_alert_tree.column("reasons", width=240, anchor="w")
        self.dashboard_alert_tree.column("notes", width=350, anchor="w")
        self.dashboard_alert_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.dashboard_alert_tree.tag_configure("alert_critical", background="#fee2e2")
        self.dashboard_alert_tree.tag_configure("alert_warning", background="#fff7ed")
        self.dashboard_alert_tree.tag_configure("alert_ack", background="#dcfce7")
        alert_actions = ttk.Frame(alerts_wrap)
        alert_actions.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(
            alert_actions,
            text="Confirma alerta selectata",
            command=self.acknowledge_selected_dashboard_alert,
        ).pack(side=LEFT)
        ttk.Button(alert_actions, text="Deschide pacient selectat", command=self.open_patient_from_dashboard_alert).pack(
            side=RIGHT
        )

        watchlist_wrap = ttk.LabelFrame(frame, text="Watchlist risc (Top 10)")
        watchlist_wrap.pack(fill=BOTH, expand=True, pady=(8, 0))
        cols_w = ("score", "trend", "patient", "mrn", "triage", "dept", "signals")
        self.dashboard_watchlist_tree = ttk.Treeview(watchlist_wrap, columns=cols_w, show="headings", height=7)
        self.dashboard_watchlist_tree.heading("score", text="Scor risc")
        self.dashboard_watchlist_tree.heading("trend", text="Trend")
        self.dashboard_watchlist_tree.heading("patient", text="Pacient")
        self.dashboard_watchlist_tree.heading("mrn", text="MRN")
        self.dashboard_watchlist_tree.heading("triage", text="Triage")
        self.dashboard_watchlist_tree.heading("dept", text="Sectie")
        self.dashboard_watchlist_tree.heading("signals", text="Semnale")
        self.dashboard_watchlist_tree.column("score", width=90, anchor="center")
        self.dashboard_watchlist_tree.column("trend", width=92, anchor="center")
        self.dashboard_watchlist_tree.column("patient", width=200, anchor="w")
        self.dashboard_watchlist_tree.column("mrn", width=110, anchor="w")
        self.dashboard_watchlist_tree.column("triage", width=70, anchor="center")
        self.dashboard_watchlist_tree.column("dept", width=130, anchor="w")
        self.dashboard_watchlist_tree.column("signals", width=430, anchor="w")
        self.dashboard_watchlist_tree.tag_configure("watchlist_high", background="#fee2e2")
        self.dashboard_watchlist_tree.tag_configure("watchlist_medium", background="#fff7ed")
        self.dashboard_watchlist_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.watchlist_formula_var = tk.StringVar()
        ttk.Label(watchlist_wrap, textvariable=self.watchlist_formula_var, foreground="#475569").pack(
            anchor="w", padx=6, pady=(0, 4)
        )
        self._refresh_watchlist_formula_hint()
        ttk.Button(watchlist_wrap, text="Deschide pacient selectat", command=self.open_patient_from_dashboard_watchlist).pack(
            anchor="e", padx=6, pady=(0, 6)
        )

        history_wrap = ttk.LabelFrame(frame, text="Istoric watchlist")
        history_wrap.pack(fill=BOTH, expand=True, pady=(8, 0))
        history_filters = ttk.Frame(history_wrap)
        history_filters.pack(fill="x", padx=6, pady=(6, 4))
        ttk.Label(history_filters, text="Interval (ore)").pack(side=LEFT)
        self.watchlist_history_hours_var = tk.StringVar(value=str(getattr(self, "watchlist_history_hours_default", 24)))
        ttk.Entry(history_filters, textvariable=self.watchlist_history_hours_var, width=8).pack(side=LEFT, padx=(6, 10))
        ttk.Label(history_filters, text="Trend").pack(side=LEFT)
        self.watchlist_history_mode_var = tk.StringVar(value=str(getattr(self, "watchlist_history_mode_default", "Toate")))
        ttk.Combobox(
            history_filters,
            textvariable=self.watchlist_history_mode_var,
            state="readonly",
            values=("Toate", "Doar cresteri"),
            width=14,
        ).pack(side=LEFT, padx=(6, 10))
        self.watchlist_history_mode_var.trace_add("write", lambda *_args: self._persist_watchlist_history_preferences())
        ttk.Button(history_filters, text="Refresh istoric", command=self.refresh_watchlist_history_panel).pack(side=LEFT)
        ttk.Button(history_filters, text="Export rapid CSV+PDF", command=self.request_dashboard_watchlist_history_quick_export).pack(
            side=LEFT,
            padx=(6, 0),
        )
        ttk.Button(history_filters, text="Reset preferinte", command=self.reset_watchlist_history_preferences).pack(
            side=LEFT,
            padx=(6, 0),
        )

        history_tables = ttk.Frame(history_wrap)
        history_tables.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))

        snapshots_wrap = ttk.LabelFrame(history_tables, text="Ultime snapshot-uri")
        snapshots_wrap.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 6))
        cols_hs = ("snapshot_ts", "rows_count", "max_score", "avg_score")
        self.dashboard_watchlist_snapshots_tree = ttk.Treeview(snapshots_wrap, columns=cols_hs, show="headings", height=6)
        self.dashboard_watchlist_snapshots_tree.heading("snapshot_ts", text="Timestamp")
        self.dashboard_watchlist_snapshots_tree.heading("rows_count", text="Randuri")
        self.dashboard_watchlist_snapshots_tree.heading("max_score", text="Scor max")
        self.dashboard_watchlist_snapshots_tree.heading("avg_score", text="Scor mediu")
        self.dashboard_watchlist_snapshots_tree.column("snapshot_ts", width=155, anchor="w")
        self.dashboard_watchlist_snapshots_tree.column("rows_count", width=72, anchor="center")
        self.dashboard_watchlist_snapshots_tree.column("max_score", width=78, anchor="center")
        self.dashboard_watchlist_snapshots_tree.column("avg_score", width=90, anchor="center")
        self.dashboard_watchlist_snapshots_tree.pack(fill=BOTH, expand=True, padx=4, pady=4)

        trend_wrap = ttk.LabelFrame(history_tables, text="Evolutie risc Top 10")
        trend_wrap.pack(side=LEFT, fill=BOTH, expand=True)
        cols_ht = ("delta", "score_now", "patient", "mrn")
        self.dashboard_watchlist_trend_tree = ttk.Treeview(trend_wrap, columns=cols_ht, show="headings", height=6)
        self.dashboard_watchlist_trend_tree.heading(
            "delta",
            text="Trend",
            command=lambda: self._toggle_watchlist_history_sort("delta"),
        )
        self.dashboard_watchlist_trend_tree.heading(
            "score_now",
            text="Scor acum",
            command=lambda: self._toggle_watchlist_history_sort("score_now"),
        )
        self.dashboard_watchlist_trend_tree.heading(
            "patient",
            text="Pacient",
            command=lambda: self._toggle_watchlist_history_sort("patient"),
        )
        self.dashboard_watchlist_trend_tree.heading(
            "mrn",
            text="MRN",
            command=lambda: self._toggle_watchlist_history_sort("mrn"),
        )
        self.dashboard_watchlist_trend_tree.column("delta", width=80, anchor="center")
        self.dashboard_watchlist_trend_tree.column("score_now", width=90, anchor="center")
        self.dashboard_watchlist_trend_tree.column("patient", width=220, anchor="w")
        self.dashboard_watchlist_trend_tree.column("mrn", width=110, anchor="w")
        self.dashboard_watchlist_trend_tree.tag_configure("trend_up", background="#dcfce7")
        self.dashboard_watchlist_trend_tree.tag_configure("trend_down", background="#fee2e2")
        self.dashboard_watchlist_trend_tree.tag_configure("trend_flat", background="#fff7ed")
        self.dashboard_watchlist_trend_tree.pack(fill=BOTH, expand=True, padx=4, pady=4)

        self.watchlist_history_status_var = tk.StringVar(value="Istoric watchlist: fara date.")
        ttk.Label(history_wrap, textvariable=self.watchlist_history_status_var, foreground="#475569").pack(
            anchor="w", padx=6, pady=(0, 4)
        )

    def _refresh_watchlist_formula_hint(self) -> None:
        high_thr = max(1, int(getattr(self, "watchlist_score_high_threshold", 90)))
        medium_thr = max(1, int(getattr(self, "watchlist_score_medium_threshold", 60)))
        max_medium = high_thr - 1 if high_thr > 1 else 1
        if medium_thr > max_medium:
            medium_thr = max_medium
        w_t1 = int(getattr(self, "watchlist_weight_triage_1", 60))
        w_t2 = int(getattr(self, "watchlist_weight_triage_2", 40))
        w_t3 = int(getattr(self, "watchlist_weight_triage_3", 20))
        w_t4 = int(getattr(self, "watchlist_weight_triage_4_plus", 5))
        w_unack = int(getattr(self, "watchlist_weight_alert_unack", 25))
        w_crit = int(getattr(self, "watchlist_weight_alert_critical", 15))
        w_stat = int(getattr(self, "watchlist_weight_order_stat", 20))
        w_urgent = int(getattr(self, "watchlist_weight_order_urgent", 10))
        w_progress = int(getattr(self, "watchlist_weight_order_in_progress", 5))
        text = (
            f"Scor = triage(1:{w_t1},2:{w_t2},3:{w_t3},4+:{w_t4}) + "
            f"alerte_neconfirmate*{w_unack} + alerte_critice*{w_crit} + "
            f"ord_stat*{w_stat} + ord_urgent*{w_urgent} + in_progress*{w_progress}"
            f" | Praguri highlight: HIGH >= {high_thr}, MEDIUM >= {medium_thr}"
        )
        if hasattr(self, "watchlist_formula_var"):
            self.watchlist_formula_var.set(text)

    def _build_statistics_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.stats_filter_vars = {
            "department": tk.StringVar(value=str(getattr(self, "stats_filter_department_default", ""))),
            "date_from": tk.StringVar(value=str(getattr(self, "stats_filter_date_from_default", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")))),
            "date_to": tk.StringVar(value=str(getattr(self, "stats_filter_date_to_default", datetime.now().strftime("%Y-%m-%d")))),
        }
        filter_row = ttk.LabelFrame(frame, text="Filtre statistici")
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="Sectie").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(filter_row, textvariable=self.stats_filter_vars["department"], width=18).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(filter_row, text="De la (YYYY-MM-DD)").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(filter_row, textvariable=self.stats_filter_vars["date_from"], width=14).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(filter_row, text="Pana la").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(filter_row, textvariable=self.stats_filter_vars["date_to"], width=14).grid(row=0, column=5, sticky="w", padx=6, pady=4)
        actions = ttk.Frame(filter_row)
        actions.grid(row=0, column=6, sticky="e", padx=6, pady=4)
        ttk.Button(actions, text="7 zile", command=lambda: self.set_stats_range(7)).pack(side=LEFT)
        ttk.Button(actions, text="30 zile", command=lambda: self.set_stats_range(30)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Refresh", command=self.refresh_statistics).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export CSV", command=lambda: self.request_export_action("statistics_csv", self.export_statistics_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export operational CSV", command=lambda: self.request_export_action("statistics_operational_csv", self.export_operational_statistics_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export operational PDF", command=lambda: self.request_export_action("statistics_operational_pdf", self.export_operational_statistics_pdf)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export pe sectii CSV", command=lambda: self.request_export_action("statistics_by_department_csv", self.export_operational_by_department_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export pe sectii PDF", command=lambda: self.request_export_action("statistics_by_department_pdf", self.export_operational_by_department_pdf)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export perf watchlist rapid", command=self.request_watchlist_export_perf_quick).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export perf watchlist CSV", command=lambda: self.request_export_action("watchlist_perf_csv", self.export_watchlist_export_perf_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export perf watchlist PDF", command=lambda: self.request_export_action("watchlist_perf_pdf", self.export_watchlist_export_perf_pdf)).pack(side=LEFT, padx=6)

        kpi_wrap = ttk.LabelFrame(frame, text="Indicatori")
        kpi_wrap.pack(fill="x", pady=(10, 8))
        self.stats_kpi_vars = {
            "admissions": tk.StringVar(value="Internari: 0"),
            "discharges": tk.StringVar(value="Externari: 0"),
            "orders": tk.StringVar(value="Ordine: 0"),
            "vitals": tk.StringVar(value="Vitale: 0"),
            "los": tk.StringVar(value="LOS mediu (zile): 0"),
        }
        for key in ("admissions", "discharges", "orders", "vitals", "los"):
            ttk.Label(kpi_wrap, textvariable=self.stats_kpi_vars[key], font=("Segoe UI", 10, "bold")).pack(
                side=LEFT, padx=10, pady=6
            )

        table_wrap = ttk.LabelFrame(frame, text="Activitate zilnica")
        table_wrap.pack(fill=BOTH, expand=True, pady=(0, 8))
        cols = ("day", "admissions", "discharges", "orders", "vitals")
        self.stats_daily_tree = ttk.Treeview(table_wrap, columns=cols, show="headings", height=12)
        self.stats_daily_tree.heading("day", text="Data")
        self.stats_daily_tree.heading("admissions", text="Internari")
        self.stats_daily_tree.heading("discharges", text="Externari")
        self.stats_daily_tree.heading("orders", text="Ordine")
        self.stats_daily_tree.heading("vitals", text="Vitale")
        self.stats_daily_tree.column("day", width=120, anchor="w")
        self.stats_daily_tree.column("admissions", width=90, anchor="center")
        self.stats_daily_tree.column("discharges", width=90, anchor="center")
        self.stats_daily_tree.column("orders", width=90, anchor="center")
        self.stats_daily_tree.column("vitals", width=90, anchor="center")
        self.stats_daily_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        week_wrap = ttk.LabelFrame(frame, text="Activitate saptamanala (ISO)")
        week_wrap.pack(fill=BOTH, expand=True)
        cols_w = ("week", "admissions", "discharges", "orders", "vitals")
        self.stats_weekly_tree = ttk.Treeview(week_wrap, columns=cols_w, show="headings", height=8)
        self.stats_weekly_tree.heading("week", text="Saptamana")
        self.stats_weekly_tree.heading("admissions", text="Internari")
        self.stats_weekly_tree.heading("discharges", text="Externari")
        self.stats_weekly_tree.heading("orders", text="Ordine")
        self.stats_weekly_tree.heading("vitals", text="Vitale")
        self.stats_weekly_tree.column("week", width=120, anchor="w")
        self.stats_weekly_tree.column("admissions", width=90, anchor="center")
        self.stats_weekly_tree.column("discharges", width=90, anchor="center")
        self.stats_weekly_tree.column("orders", width=90, anchor="center")
        self.stats_weekly_tree.column("vitals", width=90, anchor="center")
        self.stats_weekly_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        operational_kpi_wrap = ttk.LabelFrame(frame, text="Operational internari/externari")
        operational_kpi_wrap.pack(fill="x", pady=(8, 8))
        self.stats_operational_kpi_vars = {
            "scheduled_admissions": tk.StringVar(value="Internari programate: 0"),
            "scheduled_discharges": tk.StringVar(value="Externari programate: 0"),
            "discharged_without_final_decont": tk.StringVar(value="Externati fara decont final: 0"),
        }
        for key in ("scheduled_admissions", "scheduled_discharges", "discharged_without_final_decont"):
            ttk.Label(operational_kpi_wrap, textvariable=self.stats_operational_kpi_vars[key], font=("Segoe UI", 10, "bold")).pack(
                side=LEFT, padx=10, pady=6
            )

        operational_wrap = ttk.LabelFrame(frame, text="Operational zilnic")
        operational_wrap.pack(fill=BOTH, expand=True)
        cols_o = ("day", "scheduled_admissions", "scheduled_discharges", "discharged_without_final_decont")
        self.stats_operational_tree = ttk.Treeview(operational_wrap, columns=cols_o, show="headings", height=8)
        self.stats_operational_tree.heading("day", text="Data")
        self.stats_operational_tree.heading("scheduled_admissions", text="Internari programate")
        self.stats_operational_tree.heading("scheduled_discharges", text="Externari programate")
        self.stats_operational_tree.heading("discharged_without_final_decont", text="Externati fara decont final")
        self.stats_operational_tree.column("day", width=120, anchor="w")
        self.stats_operational_tree.column("scheduled_admissions", width=140, anchor="center")
        self.stats_operational_tree.column("scheduled_discharges", width=140, anchor="center")
        self.stats_operational_tree.column("discharged_without_final_decont", width=180, anchor="center")
        self.stats_operational_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        operational_dept_wrap = ttk.LabelFrame(frame, text="Operational comparativ pe sectii")
        operational_dept_wrap.pack(fill=BOTH, expand=True, pady=(8, 0))
        cols_od = (
            "department",
            "scheduled_admissions",
            "scheduled_discharges",
            "discharged_without_final_decont",
            "total",
        )
        self.stats_operational_dept_tree = ttk.Treeview(operational_dept_wrap, columns=cols_od, show="headings", height=8)
        self.stats_operational_dept_tree.heading("department", text="Sectie")
        self.stats_operational_dept_tree.heading("scheduled_admissions", text="Internari programate")
        self.stats_operational_dept_tree.heading("scheduled_discharges", text="Externari programate")
        self.stats_operational_dept_tree.heading("discharged_without_final_decont", text="Externati fara decont final")
        self.stats_operational_dept_tree.heading("total", text="Total")
        self.stats_operational_dept_tree.column("department", width=220, anchor="w")
        self.stats_operational_dept_tree.column("scheduled_admissions", width=140, anchor="center")
        self.stats_operational_dept_tree.column("scheduled_discharges", width=140, anchor="center")
        self.stats_operational_dept_tree.column("discharged_without_final_decont", width=180, anchor="center")
        self.stats_operational_dept_tree.column("total", width=90, anchor="center")
        self.stats_operational_dept_tree.tag_configure("operational_backlog_alert", background="#fee2e2")
        self.stats_operational_dept_tree.tag_configure("operational_backlog_warning", background="#fff7ed")
        self.stats_operational_dept_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        self.stats_operational_alert_var = tk.StringVar(value="Stare backlog decont final: nicio alerta.")
        ttk.Label(frame, textvariable=self.stats_operational_alert_var, foreground="#b45309").pack(anchor="w", pady=(6, 0))

        export_perf_wrap = ttk.LabelFrame(frame, text="Performanta export rapid istoric watchlist")
        export_perf_wrap.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.stats_watchlist_export_kpi_vars = {
            "exports": tk.StringVar(value="Quick export-uri: 0"),
            "avg_ms": tk.StringVar(value="Durata medie (ms): 0"),
            "trend_rows": tk.StringVar(value="Randuri trend procesate: 0"),
        }
        kpi_row = ttk.Frame(export_perf_wrap)
        kpi_row.pack(fill="x", padx=6, pady=(4, 2))
        for key in ("exports", "avg_ms", "trend_rows"):
            ttk.Label(kpi_row, textvariable=self.stats_watchlist_export_kpi_vars[key], font=("Segoe UI", 10, "bold")).pack(
                side=LEFT,
                padx=10,
                pady=4,
            )

        cols_ep = ("day", "exports", "avg_ms", "max_ms", "snapshot_runs", "trend_rows", "files")
        self.stats_watchlist_export_tree = ttk.Treeview(export_perf_wrap, columns=cols_ep, show="headings", height=7)
        self.stats_watchlist_export_tree.heading("day", text="Data")
        self.stats_watchlist_export_tree.heading("exports", text="Quick export-uri")
        self.stats_watchlist_export_tree.heading("avg_ms", text="Durata medie (ms)")
        self.stats_watchlist_export_tree.heading("max_ms", text="Durata max (ms)")
        self.stats_watchlist_export_tree.heading("snapshot_runs", text="Snapshot runs")
        self.stats_watchlist_export_tree.heading("trend_rows", text="Trend rows")
        self.stats_watchlist_export_tree.heading("files", text="Fisiere")
        self.stats_watchlist_export_tree.column("day", width=120, anchor="w")
        self.stats_watchlist_export_tree.column("exports", width=120, anchor="center")
        self.stats_watchlist_export_tree.column("avg_ms", width=130, anchor="center")
        self.stats_watchlist_export_tree.column("max_ms", width=130, anchor="center")
        self.stats_watchlist_export_tree.column("snapshot_runs", width=120, anchor="center")
        self.stats_watchlist_export_tree.column("trend_rows", width=120, anchor="center")
        self.stats_watchlist_export_tree.column("files", width=100, anchor="center")
        self.stats_watchlist_export_tree.pack(fill=BOTH, expand=True, padx=6, pady=(2, 6))

    def _build_users_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        list_wrap = ttk.LabelFrame(frame, text="Utilizatori")
        list_wrap.pack(fill=BOTH, expand=True)
        cols = ("username", "display", "role", "active", "created")
        self.users_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=10)
        self.users_tree.heading("username", text="Username")
        self.users_tree.heading("display", text="Nume afisat")
        self.users_tree.heading("role", text="Rol")
        self.users_tree.heading("active", text="Activ")
        self.users_tree.heading("created", text="Creat la")
        self.users_tree.column("username", width=140, anchor="w")
        self.users_tree.column("display", width=180, anchor="w")
        self.users_tree.column("role", width=100, anchor="w")
        self.users_tree.column("active", width=70, anchor="center")
        self.users_tree.column("created", width=145, anchor="w")
        self.users_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.users_tree.bind("<<TreeviewSelect>>", self.on_user_select)

        form = ttk.LabelFrame(frame, text="Administrare utilizator")
        form.pack(fill="x", pady=(10, 0))
        self.user_form_vars = {
            "username": tk.StringVar(),
            "display_name": tk.StringVar(),
            "role": tk.StringVar(value="receptie"),
            "password": tk.StringVar(),
        }
        self.user_active_var = tk.BooleanVar(value=True)
        ttk.Label(form, text="Username").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.user_form_vars["username"], width=18).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Nume afisat").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.user_form_vars["display_name"], width=24).grid(
            row=0, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(form, text="Rol").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.user_form_vars["role"],
            state="readonly",
            values=("admin", "medic", "asistent", "receptie"),
            width=16,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(form, text="Activ", variable=self.user_active_var).grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Parola (creare/reset)").grid(row=1, column=3, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.user_form_vars["password"], show="*", width=18).grid(
            row=1, column=4, sticky="w", padx=6, pady=4
        )
        form.grid_columnconfigure(3, weight=1)

        actions = ttk.Frame(form)
        actions.grid(row=2, column=0, columnspan=5, sticky="e", padx=6, pady=(2, 6))
        ttk.Button(actions, text="Creeaza utilizator", command=self.create_user_action).pack(side=LEFT)
        ttk.Button(actions, text="Actualizeaza rol/stare", command=self.update_user_action).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Reset parola", command=self.reset_user_password_action).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Reincarca", command=self.refresh_users).pack(side=LEFT, padx=6)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.settings_bool_vars = {
            "ALERT_NOTIFY_ENABLED": tk.BooleanVar(value=self.notify_enabled),
            "AUTO_BACKUP_ENABLED": tk.BooleanVar(value=self.backup_enabled),
            "AI_ENABLED": tk.BooleanVar(value=self.ai_enabled),
            "DISCHARGE_REQUIRE_FINAL_DECONT": tk.BooleanVar(value=getattr(self, "discharge_require_final_decont", False)),
            "DISCHARGE_REQUIRE_SUMMARY": tk.BooleanVar(value=getattr(self, "discharge_require_summary", False)),
        }
        self.settings_text_vars = {
            "ALERT_POLL_SECONDS": tk.StringVar(),
            "ALERT_NOTIFY_COOLDOWN_SECONDS": tk.StringVar(),
            "ALERT_ESCALATION_MINUTES": tk.StringVar(),
            "ALERT_ESCALATION_COOLDOWN_SECONDS": tk.StringVar(),
            "ALERT_TELEGRAM_BOT_TOKEN": tk.StringVar(),
            "ALERT_TELEGRAM_CHAT_ID": tk.StringVar(),
            "ALERT_WEBHOOK_URL": tk.StringVar(),
            "ALERT_EMAIL_FROM": tk.StringVar(),
            "ALERT_EMAIL_TO": tk.StringVar(),
            "ALERT_SMTP_HOST": tk.StringVar(),
            "ALERT_SMTP_PORT": tk.StringVar(),
            "ALERT_SMTP_USER": tk.StringVar(),
            "ALERT_SMTP_PASS": tk.StringVar(),
            "AUTO_BACKUP_INTERVAL_MINUTES": tk.StringVar(),
            "AUTO_BACKUP_RETENTION_DAYS": tk.StringVar(),
            "CARE_WARD_CAPACITY_DEFAULT": tk.StringVar(),
            "CARE_WARD_CAPACITY_OVERRIDES": tk.StringVar(),
            "OPERATIONAL_BACKLOG_ALERT_THRESHOLD": tk.StringVar(),
            "WATCHLIST_SCORE_HIGH_THRESHOLD": tk.StringVar(),
            "WATCHLIST_SCORE_MEDIUM_THRESHOLD": tk.StringVar(),
            "WATCHLIST_WEIGHT_TRIAGE_1": tk.StringVar(),
            "WATCHLIST_WEIGHT_TRIAGE_2": tk.StringVar(),
            "WATCHLIST_WEIGHT_TRIAGE_3": tk.StringVar(),
            "WATCHLIST_WEIGHT_TRIAGE_4_PLUS": tk.StringVar(),
            "WATCHLIST_WEIGHT_ALERT_UNACK": tk.StringVar(),
            "WATCHLIST_WEIGHT_ALERT_CRITICAL": tk.StringVar(),
            "WATCHLIST_WEIGHT_ORDER_STAT": tk.StringVar(),
            "WATCHLIST_WEIGHT_ORDER_URGENT": tk.StringVar(),
            "WATCHLIST_WEIGHT_ORDER_IN_PROGRESS": tk.StringVar(),
            "DASHBOARD_REFRESH_DEBOUNCE_SECONDS": tk.StringVar(),
            "EXPORT_DEBOUNCE_SECONDS": tk.StringVar(),
            "QUICK_EXPORT_DEBOUNCE_SECONDS": tk.StringVar(),
            "LOGIN_LOCK_MAX_ATTEMPTS": tk.StringVar(),
            "LOGIN_LOCK_MINUTES": tk.StringVar(),
            "OPENAI_API_KEY": tk.StringVar(),
            "OPENAI_MODEL": tk.StringVar(),
            "AI_MODEL_OPTIONS": tk.StringVar(),
            "AI_PROFILE_PRESETS": tk.StringVar(),
            "AI_TEMPERATURE": tk.StringVar(),
            "AI_MAX_OUTPUT_TOKENS": tk.StringVar(),
            "AI_TIMEOUT_SECONDS": tk.StringVar(),
            "AI_ALLOWED_ROLES": tk.StringVar(),
            "AI_SYSTEM_PROMPT": tk.StringVar(),
            "AI_CONTEXT_MAX_CHARS": tk.StringVar(),
            "AI_HISTORY_MESSAGES": tk.StringVar(),
            "AI_TEMPLATE_SUMMARY": tk.StringVar(),
            "AI_TEMPLATE_PLAN_24H": tk.StringVar(),
            "AI_TEMPLATE_DISCHARGE_DRAFT": tk.StringVar(),
            "AI_TEMPLATE_EXPLAIN_ALERT": tk.StringVar(),
        }

        notify_wrap = ttk.LabelFrame(frame, text="Notificari & Escaladare")
        notify_wrap.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(
            notify_wrap,
            text="Activeaza notificari externe",
            variable=self.settings_bool_vars["ALERT_NOTIFY_ENABLED"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        notify_fields = [
            ("ALERT_POLL_SECONDS", "Polling alerte (sec)"),
            ("ALERT_NOTIFY_COOLDOWN_SECONDS", "Cooldown notificari (sec)"),
            ("ALERT_ESCALATION_MINUTES", "Escaladare dupa (minute)"),
            ("ALERT_ESCALATION_COOLDOWN_SECONDS", "Cooldown escaladare (sec)"),
            ("ALERT_TELEGRAM_BOT_TOKEN", "Telegram bot token"),
            ("ALERT_TELEGRAM_CHAT_ID", "Telegram chat id"),
            ("ALERT_WEBHOOK_URL", "Webhook URL"),
            ("ALERT_EMAIL_FROM", "Email From"),
            ("ALERT_EMAIL_TO", "Email To (separate cu ,)"),
            ("ALERT_SMTP_HOST", "SMTP host"),
            ("ALERT_SMTP_PORT", "SMTP port"),
            ("ALERT_SMTP_USER", "SMTP user"),
            ("ALERT_SMTP_PASS", "SMTP pass"),
        ]
        for idx, (key, label_text) in enumerate(notify_fields, start=1):
            ttk.Label(notify_wrap, text=label_text).grid(row=idx, column=0, sticky="w", padx=6, pady=3)
            show_mask = "*" if key in {"ALERT_TELEGRAM_BOT_TOKEN", "ALERT_SMTP_PASS"} else ""
            ttk.Entry(notify_wrap, textvariable=self.settings_text_vars[key], show=show_mask, width=56).grid(
                row=idx,
                column=1,
                sticky="ew",
                padx=6,
                pady=3,
            )
        notify_wrap.grid_columnconfigure(1, weight=1)

        ops_wrap = ttk.LabelFrame(frame, text="Backup & Securitate login")
        ops_wrap.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(
            ops_wrap,
            text="Activeaza backup automat",
            variable=self.settings_bool_vars["AUTO_BACKUP_ENABLED"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(
            ops_wrap,
            text="Externare: decont final obligatoriu",
            variable=self.settings_bool_vars["DISCHARGE_REQUIRE_FINAL_DECONT"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(
            ops_wrap,
            text="Externare: rezumat obligatoriu",
            variable=self.settings_bool_vars["DISCHARGE_REQUIRE_SUMMARY"],
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        ops_fields = [
            ("AUTO_BACKUP_INTERVAL_MINUTES", "Interval backup auto (minute)"),
            ("AUTO_BACKUP_RETENTION_DAYS", "Retentie backup (zile)"),
            ("CARE_WARD_CAPACITY_DEFAULT", "Capacitate implicita salon (paturi)"),
            ("CARE_WARD_CAPACITY_OVERRIDES", "Capacitati specifice (Sectie/Salon=Nr;...)"),
            ("OPERATIONAL_BACKLOG_ALERT_THRESHOLD", "Prag alerta backlog decont final (per sectie)"),
            ("WATCHLIST_SCORE_HIGH_THRESHOLD", "Watchlist prag HIGH (scor)"),
            ("WATCHLIST_SCORE_MEDIUM_THRESHOLD", "Watchlist prag MEDIUM (scor)"),
            ("WATCHLIST_WEIGHT_TRIAGE_1", "Watchlist pondere triage 1"),
            ("WATCHLIST_WEIGHT_TRIAGE_2", "Watchlist pondere triage 2"),
            ("WATCHLIST_WEIGHT_TRIAGE_3", "Watchlist pondere triage 3"),
            ("WATCHLIST_WEIGHT_TRIAGE_4_PLUS", "Watchlist pondere triage 4+"),
            ("WATCHLIST_WEIGHT_ALERT_UNACK", "Watchlist pondere alerta neconfirmata"),
            ("WATCHLIST_WEIGHT_ALERT_CRITICAL", "Watchlist pondere alerta critica"),
            ("WATCHLIST_WEIGHT_ORDER_STAT", "Watchlist pondere ordin STAT"),
            ("WATCHLIST_WEIGHT_ORDER_URGENT", "Watchlist pondere ordin urgent"),
            ("WATCHLIST_WEIGHT_ORDER_IN_PROGRESS", "Watchlist pondere ordin in_progress"),
            ("DASHBOARD_REFRESH_DEBOUNCE_SECONDS", "Dashboard refresh debounce (sec)"),
            ("EXPORT_DEBOUNCE_SECONDS", "Export debounce standard (sec)"),
            ("QUICK_EXPORT_DEBOUNCE_SECONDS", "Export debounce rapid (sec)"),
            ("LOGIN_LOCK_MAX_ATTEMPTS", "Login: incercari pana la lock"),
            ("LOGIN_LOCK_MINUTES", "Login: durata lock (minute)"),
        ]
        for idx, (key, label_text) in enumerate(ops_fields, start=3):
            ttk.Label(ops_wrap, text=label_text).grid(row=idx, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(ops_wrap, textvariable=self.settings_text_vars[key], width=56 if key == "CARE_WARD_CAPACITY_OVERRIDES" else 22).grid(
                row=idx,
                column=1,
                sticky="ew" if key == "CARE_WARD_CAPACITY_OVERRIDES" else "w",
                padx=6,
                pady=3,
            )
        debounce_helper = ttk.Frame(ops_wrap)
        debounce_helper.grid(row=len(ops_fields) + 3, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))
        ttk.Label(debounce_helper, text="Preset debounce").pack(side=LEFT)
        ttk.Button(debounce_helper, text="Conservator", command=lambda: self.apply_debounce_preset("Conservator")).pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(debounce_helper, text="Echilibrat", command=lambda: self.apply_debounce_preset("Echilibrat")).pack(
            side=LEFT, padx=6
        )
        ttk.Button(debounce_helper, text="Rapid", command=lambda: self.apply_debounce_preset("Rapid")).pack(
            side=LEFT
        )
        self.debounce_preset_status_var = tk.StringVar(value="Preset activ: Echilibrat")
        self.debounce_preset_status_label = ttk.Label(
            debounce_helper,
            textvariable=self.debounce_preset_status_var,
            foreground="#166534",
        )
        self.debounce_preset_status_label.pack(side=LEFT, padx=(10, 0))
        self.debounce_preset_status_label.bind("<Enter>", self._on_debounce_status_hover_enter)
        self.debounce_preset_status_label.bind("<Leave>", self._on_debounce_status_hover_leave)
        for key in (
            "DASHBOARD_REFRESH_DEBOUNCE_SECONDS",
            "EXPORT_DEBOUNCE_SECONDS",
            "QUICK_EXPORT_DEBOUNCE_SECONDS",
        ):
            self.settings_text_vars[key].trace_add("write", lambda *_args: self._refresh_debounce_preset_status())
        self._refresh_debounce_preset_status()
        ops_wrap.grid_columnconfigure(1, weight=1)

        ai_wrap = ttk.LabelFrame(frame, text="AI (OpenAI)")
        ai_wrap.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(
            ai_wrap,
            text="Activeaza AI in aplicatie",
            variable=self.settings_bool_vars["AI_ENABLED"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        self.ai_profiles_frame = ttk.Frame(ai_wrap)
        self.ai_profiles_frame.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        self._render_ai_profile_buttons()

        ai_fields = [
            ("OPENAI_API_KEY", "OpenAI API key", True),
            ("OPENAI_MODEL", "Model"),
            ("AI_TEMPERATURE", "Temperatura (0.0-1.0)"),
            ("AI_MAX_OUTPUT_TOKENS", "Max output tokens"),
            ("AI_TIMEOUT_SECONDS", "Timeout API (sec)"),
            ("AI_ALLOWED_ROLES", "Roluri permise (csv)"),
            ("AI_CONTEXT_MAX_CHARS", "Context max caractere"),
            ("AI_HISTORY_MESSAGES", "Istoric mesaje trimise la AI"),
            ("AI_SYSTEM_PROMPT", "System prompt AI"),
            ("AI_TEMPLATE_SUMMARY", "Template - Rezumat"),
            ("AI_TEMPLATE_PLAN_24H", "Template - Plan 24h"),
            ("AI_TEMPLATE_DISCHARGE_DRAFT", "Template - Draft externare"),
            ("AI_TEMPLATE_EXPLAIN_ALERT", "Template - Explica alerta"),
        ]
        for idx, field in enumerate(ai_fields, start=2):
            key = field[0]
            label_text = field[1]
            is_secret = bool(field[2]) if len(field) > 2 else False
            ttk.Label(ai_wrap, text=label_text).grid(row=idx, column=0, sticky="w", padx=6, pady=3)
            if key == "OPENAI_MODEL":
                self.ai_model_combobox = ttk.Combobox(
                    ai_wrap,
                    textvariable=self.settings_text_vars[key],
                    values=tuple(getattr(self, "ai_model_options", [DEFAULT_MODEL])),
                    width=54,
                )
                self.ai_model_combobox.grid(row=idx, column=1, sticky="ew", padx=6, pady=3)
                self.ai_model_combobox.bind(
                    "<<ComboboxSelected>>",
                    lambda _e: self._refresh_ai_model_combobox_values(),
                )
            else:
                ttk.Entry(
                    ai_wrap,
                    textvariable=self.settings_text_vars[key],
                    show="*" if is_secret else "",
                    width=56,
                ).grid(row=idx, column=1, sticky="ew", padx=6, pady=3)

        next_row = len(ai_fields) + 2
        ttk.Label(ai_wrap, text="Modele disponibile (csv)").grid(row=next_row, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(
            ai_wrap,
            textvariable=self.settings_text_vars["AI_MODEL_OPTIONS"],
            width=56,
        ).grid(row=next_row, column=1, sticky="ew", padx=6, pady=3)
        self.settings_text_vars["AI_MODEL_OPTIONS"].trace_add("write", lambda *_args: self._refresh_ai_model_combobox_values())
        next_row += 1
        ttk.Label(ai_wrap, text="Profiluri rapide (nume|model|temperatura; ...)").grid(
            row=next_row,
            column=0,
            sticky="w",
            padx=6,
            pady=3,
        )
        ttk.Entry(
            ai_wrap,
            textvariable=self.settings_text_vars["AI_PROFILE_PRESETS"],
            width=56,
        ).grid(row=next_row, column=1, sticky="ew", padx=6, pady=3)
        self.settings_text_vars["AI_PROFILE_PRESETS"].trace_add("write", lambda *_args: self._render_ai_profile_buttons())
        next_row += 1
        helper = ttk.Frame(ai_wrap)
        helper.grid(row=next_row, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 3))
        ttk.Label(
            helper,
            text="Format: Nume|model|temperatura;Nume2|model2|temperatura2",
            foreground="#475569",
        ).pack(side=LEFT)
        ttk.Button(helper, text="Copiaza exemplu", command=self.copy_ai_profile_presets_example).pack(side=LEFT, padx=8)
        ttk.Button(helper, text="Reseteaza la preseturi implicite", command=self.reset_ai_profile_presets_default).pack(
            side=LEFT,
            padx=8,
        )
        ai_wrap.grid_columnconfigure(1, weight=1)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(actions, text="Reincarca din DB", command=self.refresh_settings_form).pack(side=LEFT)
        ttk.Button(actions, text="Salveaza setari", command=lambda: self.save_admin_settings(True)).pack(
            side=LEFT,
            padx=6,
        )
        ttk.Button(actions, text="Salveaza fara aplicare", command=lambda: self.save_admin_settings(False)).pack(
            side=LEFT,
            padx=6,
        )
        ttk.Button(actions, text="Export setari JSON", command=lambda: self.request_export_action("settings_export_json", self.export_admin_settings_json)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Import setari JSON", command=lambda: self.request_export_action("settings_import_json", self.import_admin_settings_json)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Vezi detalii ultim import", command=self.show_last_settings_import_details).pack(
            side=LEFT,
            padx=6,
        )
        ttk.Button(actions, text="Sterge raport ultim import", command=self.clear_last_settings_import_details).pack(
            side=LEFT,
            padx=6,
        )

        self.settings_hint_var = tk.StringVar(value="Setari runtime pentru notificari, backup si securitate login.")
        ttk.Label(frame, textvariable=self.settings_hint_var, foreground="#1d4ed8").pack(anchor="w", pady=(6, 0))
        self.refresh_settings_form()

    def refresh_settings_form(self) -> None:
        if not self._has_role("admin"):
            return
        defaults = {
            "ALERT_POLL_SECONDS": str(self.alert_poll_seconds),
            "ALERT_NOTIFY_COOLDOWN_SECONDS": str(self.notify_cooldown_seconds),
            "ALERT_ESCALATION_MINUTES": str(self.alert_escalation_minutes),
            "ALERT_ESCALATION_COOLDOWN_SECONDS": str(self.alert_escalation_cooldown_seconds),
            "ALERT_TELEGRAM_BOT_TOKEN": self.notify_telegram_token,
            "ALERT_TELEGRAM_CHAT_ID": self.notify_telegram_chat_id,
            "ALERT_WEBHOOK_URL": self.notify_webhook_url,
            "ALERT_EMAIL_FROM": self.notify_email_from,
            "ALERT_EMAIL_TO": ",".join(self.notify_email_to),
            "ALERT_SMTP_HOST": self.notify_smtp_host,
            "ALERT_SMTP_PORT": str(self.notify_smtp_port),
            "ALERT_SMTP_USER": self.notify_smtp_user,
            "ALERT_SMTP_PASS": self.notify_smtp_pass,
            "AUTO_BACKUP_INTERVAL_MINUTES": str(self.backup_interval_minutes),
            "AUTO_BACKUP_RETENTION_DAYS": str(self.backup_retention_days),
            "CARE_WARD_CAPACITY_DEFAULT": str(getattr(self, "care_ward_capacity_default", 4)),
            "CARE_WARD_CAPACITY_OVERRIDES": getattr(self, "care_ward_capacity_overrides", ""),
            "OPERATIONAL_BACKLOG_ALERT_THRESHOLD": str(getattr(self, "operational_backlog_alert_threshold", 5)),
            "WATCHLIST_SCORE_HIGH_THRESHOLD": str(getattr(self, "watchlist_score_high_threshold", 90)),
            "WATCHLIST_SCORE_MEDIUM_THRESHOLD": str(getattr(self, "watchlist_score_medium_threshold", 60)),
            "WATCHLIST_WEIGHT_TRIAGE_1": str(getattr(self, "watchlist_weight_triage_1", 60)),
            "WATCHLIST_WEIGHT_TRIAGE_2": str(getattr(self, "watchlist_weight_triage_2", 40)),
            "WATCHLIST_WEIGHT_TRIAGE_3": str(getattr(self, "watchlist_weight_triage_3", 20)),
            "WATCHLIST_WEIGHT_TRIAGE_4_PLUS": str(getattr(self, "watchlist_weight_triage_4_plus", 5)),
            "WATCHLIST_WEIGHT_ALERT_UNACK": str(getattr(self, "watchlist_weight_alert_unack", 25)),
            "WATCHLIST_WEIGHT_ALERT_CRITICAL": str(getattr(self, "watchlist_weight_alert_critical", 15)),
            "WATCHLIST_WEIGHT_ORDER_STAT": str(getattr(self, "watchlist_weight_order_stat", 20)),
            "WATCHLIST_WEIGHT_ORDER_URGENT": str(getattr(self, "watchlist_weight_order_urgent", 10)),
            "WATCHLIST_WEIGHT_ORDER_IN_PROGRESS": str(getattr(self, "watchlist_weight_order_in_progress", 5)),
            "DASHBOARD_REFRESH_DEBOUNCE_SECONDS": str(getattr(self, "dashboard_refresh_debounce_seconds", 0.8)),
            "EXPORT_DEBOUNCE_SECONDS": str(getattr(self, "export_debounce_seconds", 0.9)),
            "QUICK_EXPORT_DEBOUNCE_SECONDS": str(getattr(self, "quick_export_debounce_seconds", 1.2)),
            "LOGIN_LOCK_MAX_ATTEMPTS": self.db.get_setting("LOGIN_LOCK_MAX_ATTEMPTS", "5"),
            "LOGIN_LOCK_MINUTES": self.db.get_setting("LOGIN_LOCK_MINUTES", "10"),
            "OPENAI_API_KEY": self.ai_api_key,
            "OPENAI_MODEL": self.ai_model,
            "AI_MODEL_OPTIONS": ",".join(getattr(self, "ai_model_options", []) or [self.ai_model or DEFAULT_MODEL]),
            "AI_PROFILE_PRESETS": self._serialize_ai_profile_presets(
                getattr(self, "ai_profile_presets", [])
                or self._parse_ai_profile_presets(DEFAULT_AI_PROFILE_PRESETS, DEFAULT_AI_PROFILE_PRESETS)
            ),
            "AI_TEMPERATURE": str(self.ai_temperature),
            "AI_MAX_OUTPUT_TOKENS": str(self.ai_max_output_tokens),
            "AI_TIMEOUT_SECONDS": str(self.ai_timeout_seconds),
            "AI_ALLOWED_ROLES": ",".join(self.ai_allowed_roles),
            "AI_SYSTEM_PROMPT": self.ai_system_prompt,
            "AI_CONTEXT_MAX_CHARS": str(self.ai_context_max_chars),
            "AI_HISTORY_MESSAGES": str(self.ai_history_messages),
            "AI_TEMPLATE_SUMMARY": self.db.get_setting(
                "AI_TEMPLATE_SUMMARY",
                "Genereaza rezumat de garda: situatie, risc, recomandare, monitorizare pe 24h.",
            ),
            "AI_TEMPLATE_PLAN_24H": self.db.get_setting(
                "AI_TEMPLATE_PLAN_24H",
                "Genereaza plan clinic pe 24h: investigatii, ordine medicale prioritare, monitorizare si criterii de reevaluare.",
            ),
            "AI_TEMPLATE_DISCHARGE_DRAFT": self.db.get_setting(
                "AI_TEMPLATE_DISCHARGE_DRAFT",
                "Genereaza draft de externare: evolutie, tratament recomandat, semne de alarma, follow-up si instructiuni pacient.",
            ),
            "AI_TEMPLATE_EXPLAIN_ALERT": self.db.get_setting(
                "AI_TEMPLATE_EXPLAIN_ALERT",
                "Explica alerta vitala recenta si impactul clinic imediat.",
            ),
        }
        saved = self.db.get_settings(list(defaults.keys()))
        for key, var in self.settings_text_vars.items():
            var.set(saved.get(key, defaults.get(key, "")))

        bool_saved_notify = self.db.get_setting("ALERT_NOTIFY_ENABLED", "1" if self.notify_enabled else "0")
        bool_saved_backup = self.db.get_setting("AUTO_BACKUP_ENABLED", "1" if self.backup_enabled else "0")
        bool_saved_ai = self.db.get_setting("AI_ENABLED", "1" if self.ai_enabled else "0")
        bool_saved_discharge_decont = self.db.get_setting(
            "DISCHARGE_REQUIRE_FINAL_DECONT",
            "1" if getattr(self, "discharge_require_final_decont", False) else "0",
        )
        bool_saved_discharge_summary = self.db.get_setting(
            "DISCHARGE_REQUIRE_SUMMARY",
            "1" if getattr(self, "discharge_require_summary", False) else "0",
        )
        self.settings_bool_vars["ALERT_NOTIFY_ENABLED"].set(self._to_bool(bool_saved_notify, True))
        self.settings_bool_vars["AUTO_BACKUP_ENABLED"].set(self._to_bool(bool_saved_backup, True))
        self.settings_bool_vars["AI_ENABLED"].set(self._to_bool(bool_saved_ai, True))
        self.settings_bool_vars["DISCHARGE_REQUIRE_FINAL_DECONT"].set(
            self._to_bool(bool_saved_discharge_decont, False)
        )
        self.settings_bool_vars["DISCHARGE_REQUIRE_SUMMARY"].set(
            self._to_bool(bool_saved_discharge_summary, False)
        )
        self._refresh_ai_model_combobox_values()
        self._refresh_debounce_preset_status()

    def save_admin_settings(self, apply_now: bool) -> None:
        if not self._require_role("Setari aplicatie", "admin"):
            return

        int_rules = {
            "ALERT_POLL_SECONDS": 15,
            "ALERT_NOTIFY_COOLDOWN_SECONDS": 0,
            "ALERT_ESCALATION_MINUTES": 1,
            "ALERT_ESCALATION_COOLDOWN_SECONDS": 60,
            "ALERT_SMTP_PORT": 1,
            "AUTO_BACKUP_INTERVAL_MINUTES": 10,
            "AUTO_BACKUP_RETENTION_DAYS": 1,
            "CARE_WARD_CAPACITY_DEFAULT": 1,
            "OPERATIONAL_BACKLOG_ALERT_THRESHOLD": 1,
            "WATCHLIST_SCORE_HIGH_THRESHOLD": 1,
            "WATCHLIST_SCORE_MEDIUM_THRESHOLD": 1,
            "WATCHLIST_WEIGHT_TRIAGE_1": 0,
            "WATCHLIST_WEIGHT_TRIAGE_2": 0,
            "WATCHLIST_WEIGHT_TRIAGE_3": 0,
            "WATCHLIST_WEIGHT_TRIAGE_4_PLUS": 0,
            "WATCHLIST_WEIGHT_ALERT_UNACK": 0,
            "WATCHLIST_WEIGHT_ALERT_CRITICAL": 0,
            "WATCHLIST_WEIGHT_ORDER_STAT": 0,
            "WATCHLIST_WEIGHT_ORDER_URGENT": 0,
            "WATCHLIST_WEIGHT_ORDER_IN_PROGRESS": 0,
            "LOGIN_LOCK_MAX_ATTEMPTS": 3,
            "LOGIN_LOCK_MINUTES": 1,
            "AI_MAX_OUTPUT_TOKENS": 200,
            "AI_TIMEOUT_SECONDS": 10,
            "AI_CONTEXT_MAX_CHARS": 2000,
            "AI_HISTORY_MESSAGES": 2,
        }

        payload: Dict[str, Any] = {
            "ALERT_NOTIFY_ENABLED": "1" if self.settings_bool_vars["ALERT_NOTIFY_ENABLED"].get() else "0",
            "AUTO_BACKUP_ENABLED": "1" if self.settings_bool_vars["AUTO_BACKUP_ENABLED"].get() else "0",
            "AI_ENABLED": "1" if self.settings_bool_vars["AI_ENABLED"].get() else "0",
            "DISCHARGE_REQUIRE_FINAL_DECONT": "1" if self.settings_bool_vars["DISCHARGE_REQUIRE_FINAL_DECONT"].get() else "0",
            "DISCHARGE_REQUIRE_SUMMARY": "1" if self.settings_bool_vars["DISCHARGE_REQUIRE_SUMMARY"].get() else "0",
        }
        for key, var in self.settings_text_vars.items():
            value = (var.get() or "").strip()
            if key in int_rules:
                try:
                    parsed = int(value or "0")
                except Exception:
                    messagebox.showerror("Setari", f"Valoare invalida pentru {key}: {value}")
                    return
                parsed = max(int_rules[key], parsed)
                payload[key] = str(parsed)
                var.set(str(parsed))
            else:
                payload[key] = value

        try:
            ai_temp = float(payload.get("AI_TEMPERATURE", "0.2") or "0.2")
            ai_temp = max(0.0, min(1.0, ai_temp))
            payload["AI_TEMPERATURE"] = str(ai_temp)
            self.settings_text_vars["AI_TEMPERATURE"].set(str(ai_temp))
        except Exception:
            messagebox.showerror("Setari", "Valoare invalida pentru AI_TEMPERATURE.")
            return

        debounce_float_rules = {
            "DASHBOARD_REFRESH_DEBOUNCE_SECONDS": (0.8, 0.1, 10.0),
            "EXPORT_DEBOUNCE_SECONDS": (0.9, 0.1, 10.0),
            "QUICK_EXPORT_DEBOUNCE_SECONDS": (1.2, 0.1, 15.0),
        }
        for key, (default_v, min_v, max_v) in debounce_float_rules.items():
            try:
                parsed = float(payload.get(key, str(default_v)) or default_v)
            except Exception:
                messagebox.showerror("Setari", f"Valoare invalida pentru {key}: {payload.get(key, '')}")
                return
            parsed = max(min_v, min(max_v, parsed))
            normalized = (f"{parsed:.2f}").rstrip("0").rstrip(".")
            payload[key] = normalized
            if key in self.settings_text_vars:
                self.settings_text_vars[key].set(normalized)

        selected_model = (payload.get("OPENAI_MODEL", "") or "").strip() or DEFAULT_MODEL
        payload["OPENAI_MODEL"] = selected_model
        self.settings_text_vars["OPENAI_MODEL"].set(selected_model)
        model_options_csv = (payload.get("AI_MODEL_OPTIONS", "") or "").strip()
        model_options = self._parse_csv_options(model_options_csv, DEFAULT_AI_MODEL_OPTIONS)
        if selected_model not in model_options:
            model_options.insert(0, selected_model)
        payload["AI_MODEL_OPTIONS"] = ",".join(model_options)
        self.settings_text_vars["AI_MODEL_OPTIONS"].set(payload["AI_MODEL_OPTIONS"])

        profiles_csv = (payload.get("AI_PROFILE_PRESETS", "") or "").strip()
        profile_presets = self._parse_ai_profile_presets(profiles_csv, DEFAULT_AI_PROFILE_PRESETS)
        if not any((p.get("model") or "").strip() == selected_model for p in profile_presets):
            profile_presets.insert(
                0,
                {
                    "name": "Custom",
                    "model": selected_model,
                    "temperature": payload.get("AI_TEMPERATURE", "0.2"),
                },
            )
        payload["AI_PROFILE_PRESETS"] = self._serialize_ai_profile_presets(profile_presets)
        self.settings_text_vars["AI_PROFILE_PRESETS"].set(payload["AI_PROFILE_PRESETS"])

        try:
            payload["CARE_WARD_CAPACITY_OVERRIDES"] = self._normalize_capacity_overrides(
                payload.get("CARE_WARD_CAPACITY_OVERRIDES", "")
            )
            self.settings_text_vars["CARE_WARD_CAPACITY_OVERRIDES"].set(payload["CARE_WARD_CAPACITY_OVERRIDES"])
        except ValueError as exc:
            messagebox.showerror("Setari", str(exc))
            return

        watch_high = int(payload.get("WATCHLIST_SCORE_HIGH_THRESHOLD", "90") or "90")
        watch_medium = int(payload.get("WATCHLIST_SCORE_MEDIUM_THRESHOLD", "60") or "60")
        max_medium = watch_high - 1 if watch_high > 1 else 1
        if watch_medium > max_medium:
            watch_medium = max_medium
        payload["WATCHLIST_SCORE_HIGH_THRESHOLD"] = str(watch_high)
        payload["WATCHLIST_SCORE_MEDIUM_THRESHOLD"] = str(watch_medium)
        self.settings_text_vars["WATCHLIST_SCORE_HIGH_THRESHOLD"].set(str(watch_high))
        self.settings_text_vars["WATCHLIST_SCORE_MEDIUM_THRESHOLD"].set(str(watch_medium))

        self._refresh_ai_model_combobox_values()
        self._render_ai_profile_buttons()

        self.db.set_settings(payload)
        self._audit(
            "update_app_settings",
            self._audit_details_from_pairs(("keys", ",".join(sorted(payload.keys())))),
        )

        if apply_now:
            self._load_runtime_settings()
            self.refresh_ai_status()
            self._schedule_alert_poll()
            if self.backup_enabled:
                self._schedule_backup_job(delay_seconds=15)
            elif self.backup_job:
                try:
                    self.root.after_cancel(self.backup_job)
                except Exception:
                    pass
                self.backup_job = None
            self.refresh_dashboard()
            if self._has_role("admin", "medic", "receptie"):
                self.refresh_statistics()
            self.settings_hint_var.set(
                "Setari salvate si aplicate in sesiunea curenta. "
                f"Debounce activ: refresh={self._format_debounce_seconds(self.dashboard_refresh_debounce_seconds)}s, "
                f"export={self._format_debounce_seconds(self.export_debounce_seconds)}s, "
                f"rapid={self._format_debounce_seconds(self.quick_export_debounce_seconds)}s."
            )
        else:
            self.settings_hint_var.set("Setari salvate. Vor fi aplicate integral la restart.")

        messagebox.showinfo("Setari", "Setarile au fost salvate.")

    def _settings_export_keys(self) -> List[str]:
        keys = set(self.settings_text_vars.keys())
        keys.update(self.settings_bool_vars.keys())
        keys.update(
            {
                "DASHBOARD_FILTER_DEPARTMENT",
                "DASHBOARD_OPERATIONAL_DATE",
                "PATIENT_STATUS_FILTER",
                "PATIENT_STATUS_DATE",
                "STATS_FILTER_DEPARTMENT",
                "STATS_FILTER_DATE_FROM",
                "STATS_FILTER_DATE_TO",
            }
        )
        return sorted(keys)

    def export_admin_settings_json(self) -> None:
        if not self._require_role("Export setari", "admin"):
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"app_settings_{stamp}.json"
        out_path = filedialog.asksaveasfilename(
            title="Export setari aplicatie",
            initialdir=str(EXPORTS_DIR),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=(("JSON", "*.json"), ("Toate fisierele", "*.*")),
        )
        if not out_path:
            return
        all_settings = self.db.get_all_settings()
        keys = self._settings_export_keys()
        payload = {
            "meta": {
                "exported_at": now_ts(),
                "app": "PacientiAIIndependent",
                "settings_schema_version": SETTINGS_SCHEMA_VERSION,
            },
            "settings": {k: all_settings.get(k, "") for k in keys},
        }
        try:
            Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._audit(
                "export_app_settings_json",
                self._audit_details_from_pairs(("file", out_path)),
            )
            messagebox.showinfo("Setari", f"Setari exportate:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Setari", f"Export esuat: {exc}")

    def import_admin_settings_json(self) -> None:
        if not self._require_role("Import setari", "admin"):
            return
        in_path = filedialog.askopenfilename(
            title="Import setari aplicatie",
            initialdir=str(EXPORTS_DIR),
            filetypes=(("JSON", "*.json"), ("Toate fisierele", "*.*")),
        )
        if not in_path:
            return
        try:
            raw = Path(in_path).read_text(encoding="utf-8")
            payload = json.loads(raw)
            meta = payload.get("meta") if isinstance(payload, dict) else None
            schema_version = 1
            if isinstance(meta, dict):
                try:
                    schema_version = int(meta.get("settings_schema_version", 1) or 1)
                except Exception:
                    schema_version = 1

            if schema_version > SETTINGS_SCHEMA_VERSION:
                proceed = messagebox.askyesno(
                    "Schema setari mai noua",
                    (
                        "Fisierul de setari este exportat dintr-o versiune mai noua a aplicatiei.\n"
                        f"Schema fisier: {schema_version}; schema locala: {SETTINGS_SCHEMA_VERSION}.\n\n"
                        "Continui cu import best-effort (doar cheile compatibile)?"
                    ),
                )
                if not proceed:
                    return

            settings = payload.get("settings") if isinstance(payload, dict) else None
            if not isinstance(settings, dict):
                raise ValueError("Fisier JSON invalid: lipseste obiectul 'settings'.")

            allowed = set(self._settings_export_keys())
            normalized = {str(k): str(v) for k, v in settings.items()}
            filtered = {k: v for k, v in normalized.items() if k in allowed}
            ignored = sorted([k for k in normalized.keys() if k not in allowed])
            if not filtered:
                raise ValueError("Nu s-au gasit chei de setari compatibile.")

            self.db.set_settings(filtered)
            self._audit(
                "import_app_settings_json",
                self._audit_details_from_pairs(
                    ("file", in_path),
                    ("imported", len(filtered)),
                    ("ignored", len(ignored)),
                    ("schema", schema_version),
                ),
            )
            self.refresh_settings_form()

            apply_now = messagebox.askyesno(
                "Setari",
                "Import finalizat. Aplic setarile imediat in sesiunea curenta?",
            )
            if apply_now:
                self._load_runtime_settings()
                self.refresh_ai_status()
                self._schedule_alert_poll()
                if self.backup_enabled:
                    self._schedule_backup_job(delay_seconds=15)
                elif self.backup_job:
                    try:
                        self.root.after_cancel(self.backup_job)
                    except Exception:
                        pass
                    self.backup_job = None
                self.settings_hint_var.set("Setari importate si aplicate in sesiunea curenta.")
            else:
                self.settings_hint_var.set("Setari importate. Recomandat restart pentru aplicare completa.")
            details = [
                "Import setari finalizat.",
                f"Chei importate: {len(filtered)}",
                f"Chei ignorate: {len(ignored)}",
            ]
            if ignored:
                preview = ", ".join(ignored[:8])
                suffix = "..." if len(ignored) > 8 else ""
                details.append(f"Ignorate: {preview}{suffix}")
            details_text = "\n".join(details)
            self.last_settings_import_report = details_text
            try:
                self.db.set_setting("LAST_SETTINGS_IMPORT_REPORT", details_text)
            except Exception:
                pass
            messagebox.showinfo("Setari", details_text)
        except Exception as exc:
            messagebox.showerror("Setari", f"Import esuat: {exc}")

    def show_last_settings_import_details(self) -> None:
        if not self._require_role("Detalii import setari", "admin"):
            return
        if not self.last_settings_import_report:
            self.last_settings_import_report = (self.db.get_setting("LAST_SETTINGS_IMPORT_REPORT", "") or "").strip()
        if not self.last_settings_import_report:
            messagebox.showinfo("Setari", "Nu exista inca un import de setari in sesiunea curenta.")
            return
        messagebox.showinfo("Setari", self.last_settings_import_report)

    def clear_last_settings_import_details(self) -> None:
        if not self._require_role("Stergere raport import setari", "admin"):
            return
        confirm = messagebox.askyesno("Setari", "Sterg raportul ultimului import salvat?")
        if not confirm:
            return
        self.last_settings_import_report = ""
        try:
            self.db.set_setting("LAST_SETTINGS_IMPORT_REPORT", "")
        except Exception:
            pass
        self._audit(
            "clear_last_import_report",
            self._audit_details_from_pairs(("key", "LAST_SETTINGS_IMPORT_REPORT")),
        )
        self.settings_hint_var.set("Raportul ultimului import a fost sters.")
        messagebox.showinfo("Setari", "Raportul ultimului import a fost sters.")

    def _build_audit_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        filters = ttk.LabelFrame(frame, text="Filtre audit")
        filters.pack(fill="x")
        self.audit_filter_vars = {
            "username": tk.StringVar(),
            "action": tk.StringVar(),
            "patient_id": tk.StringVar(),
            "date_from": tk.StringVar(),
            "date_to": tk.StringVar(),
        }
        ttk.Label(filters, text="User").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(filters, textvariable=self.audit_filter_vars["username"], width=16).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(filters, text="Actiune").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(filters, textvariable=self.audit_filter_vars["action"], width=18).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(filters, text="Patient ID").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(filters, textvariable=self.audit_filter_vars["patient_id"], width=10).grid(row=0, column=5, sticky="w", padx=6, pady=4)
        ttk.Label(filters, text="De la (YYYY-MM-DD HH:MM:SS)").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(filters, textvariable=self.audit_filter_vars["date_from"], width=22).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(filters, text="Pana la").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(filters, textvariable=self.audit_filter_vars["date_to"], width=22).grid(row=1, column=3, sticky="w", padx=6, pady=4)
        actions = ttk.Frame(filters)
        actions.grid(row=1, column=4, columnspan=2, sticky="e", padx=6, pady=4)
        ttk.Button(actions, text="Filtreaza", command=self.refresh_audit).pack(side=LEFT)
        ttk.Button(actions, text="Export Audit CSV", command=lambda: self.request_export_action("audit_export_csv", self.export_audit_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Audit Handoff CSV", command=lambda: self.request_export_action("audit_handoff_status_csv", self.export_handoff_status_audit_csv)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Export Audit Handoff JSON", command=lambda: self.request_export_action("audit_handoff_status_json", self.export_handoff_status_audit_json)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Curata", command=self.clear_audit_filters).pack(side=LEFT, padx=6)
        ttk.Label(
            filters,
            text=(
                "Hint: Export Audit CSV foloseste filtrul curent. "
                "Export Audit Handoff CSV/JSON include doar evenimente handoff status "
                f"(ultimele {HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT})."
            ),
            foreground="#475569",
            wraplength=900,
            justify="left",
        ).grid(row=2, column=0, columnspan=6, sticky="w", padx=6, pady=(2, 4))
        self.audit_export_profile_var = tk.StringVar(value=self._audit_export_profile_text())
        ttk.Label(filters, textvariable=self.audit_export_profile_var, foreground="#475569", wraplength=900, justify="left").grid(
            row=3, column=0, columnspan=6, sticky="w", padx=6, pady=(0, 4)
        )

        list_wrap = ttk.LabelFrame(frame, text="Audit log")
        list_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))
        cols = ("time", "user", "action", "patient_id", "patient_name", "details")
        self.audit_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=16)
        self.audit_tree.heading("time", text="Timestamp")
        self.audit_tree.heading("user", text="User")
        self.audit_tree.heading("action", text="Actiune")
        self.audit_tree.heading("patient_id", text="Patient ID")
        self.audit_tree.heading("patient_name", text="Pacient")
        self.audit_tree.heading("details", text="Detalii")
        self.audit_tree.column("time", width=150, anchor="w")
        self.audit_tree.column("user", width=100, anchor="w")
        self.audit_tree.column("action", width=150, anchor="w")
        self.audit_tree.column("patient_id", width=80, anchor="center")
        self.audit_tree.column("patient_name", width=200, anchor="w")
        self.audit_tree.column("details", width=540, anchor="w")
        self.audit_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        bottom = ttk.Frame(list_wrap)
        bottom.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(bottom, text="Deschide pacient selectat", command=self.open_patient_from_audit).pack(side=RIGHT)

    def _compute_watchlist_rows(
        self,
        admissions: List[sqlite3.Row],
        orders: List[sqlite3.Row],
        alerts: List[Dict[str, Any]],
        acked_ids: set[int],
    ) -> List[Dict[str, Any]]:
        alerts_by_admission: Dict[int, Dict[str, int]] = {}
        for item in alerts:
            admission_id = int(item.get("admission_id") or 0)
            if admission_id <= 0:
                continue
            bucket = alerts_by_admission.setdefault(admission_id, {"unack": 0, "critical_unack": 0})
            vital_id = int(item.get("id") or 0)
            if vital_id in acked_ids:
                continue
            bucket["unack"] += 1
            if self._is_critical_alert_reasons(item.get("reasons") or ""):
                bucket["critical_unack"] += 1

        orders_by_admission: Dict[int, Dict[str, int]] = {}
        for item in orders:
            admission_id = int(item.get("admission_id") or 0)
            if admission_id <= 0:
                continue
            bucket = orders_by_admission.setdefault(admission_id, {"stat": 0, "urgent": 0, "in_progress": 0})
            priority = (item.get("priority") or "").strip().lower()
            status = (item.get("status") or "").strip().lower()
            if priority == "stat":
                bucket["stat"] += 1
            elif priority == "urgent":
                bucket["urgent"] += 1
            if status == "in_progress":
                bucket["in_progress"] += 1

        watchlist_rows: List[Dict[str, Any]] = []
        triage_weight_1 = int(getattr(self, "watchlist_weight_triage_1", 60))
        triage_weight_2 = int(getattr(self, "watchlist_weight_triage_2", 40))
        triage_weight_3 = int(getattr(self, "watchlist_weight_triage_3", 20))
        triage_weight_4_plus = int(getattr(self, "watchlist_weight_triage_4_plus", 5))
        weight_alert_unack = int(getattr(self, "watchlist_weight_alert_unack", 25))
        weight_alert_critical = int(getattr(self, "watchlist_weight_alert_critical", 15))
        weight_order_stat = int(getattr(self, "watchlist_weight_order_stat", 20))
        weight_order_urgent = int(getattr(self, "watchlist_weight_order_urgent", 10))
        weight_order_in_progress = int(getattr(self, "watchlist_weight_order_in_progress", 5))

        for row in admissions:
            admission_id = int(row["id"])
            triage = int(row.get("triage_level") or 3)
            triage_score = (
                triage_weight_1
                if triage <= 1
                else triage_weight_2
                if triage == 2
                else triage_weight_3
                if triage == 3
                else triage_weight_4_plus
            )
            alert_info = alerts_by_admission.get(admission_id, {"unack": 0, "critical_unack": 0})
            order_info = orders_by_admission.get(admission_id, {"stat": 0, "urgent": 0, "in_progress": 0})

            score_alert_unack = int(alert_info["unack"]) * weight_alert_unack
            score_alert_critical = int(alert_info["critical_unack"]) * weight_alert_critical
            score_order_stat = int(order_info["stat"]) * weight_order_stat
            score_order_urgent = int(order_info["urgent"]) * weight_order_urgent
            score_order_in_progress = int(order_info["in_progress"]) * weight_order_in_progress
            score = (
                triage_score
                + score_alert_unack
                + score_alert_critical
                + score_order_stat
                + score_order_urgent
                + score_order_in_progress
            )

            signals = [f"triage={triage}"]
            if alert_info["unack"]:
                signals.append(f"alerte_neconfirmate={alert_info['unack']}")
            if alert_info["critical_unack"]:
                signals.append(f"alerte_critice={alert_info['critical_unack']}")
            if order_info["stat"]:
                signals.append(f"ord_stat={order_info['stat']}")
            if order_info["urgent"]:
                signals.append(f"ord_urgent={order_info['urgent']}")
            if order_info["in_progress"]:
                signals.append(f"ord_in_progress={order_info['in_progress']}")

            score_breakdown = (
                f"triage={triage_score};"
                f"alert_unack={score_alert_unack};"
                f"alert_critical={score_alert_critical};"
                f"ord_stat={score_order_stat};"
                f"ord_urgent={score_order_urgent};"
                f"ord_in_progress={score_order_in_progress}"
            )

            watchlist_rows.append(
                {
                    "admission_id": admission_id,
                    "patient_id": int(row["patient_id"]),
                    "mrn": row["mrn"],
                    "patient_name": f"{row['last_name']} {row['first_name']}".strip(),
                    "triage_level": triage,
                    "department": row["department"],
                    "score": score,
                    "signals": ", ".join(signals),
                    "score_breakdown": score_breakdown,
                    "admitted_at": row["admitted_at"],
                }
            )

        watchlist_rows.sort(key=lambda item: (-int(item["score"]), int(item["triage_level"]), str(item["admitted_at"] or "")))
        return watchlist_rows

    @staticmethod
    def _watchlist_sort_key(item: Dict[str, Any]) -> Tuple[int, int, str]:
        return (-int(item["score"]), int(item["triage_level"]), str(item["admitted_at"] or ""))

    @staticmethod
    def _watchlist_trend_label(previous_score: Optional[int], current_score: int) -> Tuple[str, int]:
        if previous_score is None:
            return ("NOU", 0)
        delta = int(current_score) - int(previous_score)
        if delta > 0:
            return (f"â†‘ +{delta}", delta)
        if delta < 0:
            return (f"â†“ {delta}", delta)
        return ("â†’ 0", 0)

    def _apply_watchlist_trend(self, rows: List[Dict[str, Any]], department: str) -> str:
        snapshot_ts = now_ts()
        previous_scores = self.db.get_previous_watchlist_scores(department=department, before_ts=snapshot_ts)
        for item in rows:
            admission_id = int(item.get("admission_id") or 0)
            prev_score = previous_scores.get(admission_id)
            label, delta = self._watchlist_trend_label(prev_score, int(item.get("score") or 0))
            item["previous_score"] = prev_score
            item["trend_label"] = label
            item["trend_delta"] = delta
        return snapshot_ts

    def _persist_watchlist_snapshot(self, rows: List[Dict[str, Any]], department: str, snapshot_ts: Optional[str] = None) -> int:
        if not rows:
            return 0
        when = (snapshot_ts or "").strip() or now_ts()
        top_rows = sorted(list(rows), key=self._watchlist_sort_key)[:10]
        try:
            return self.db.save_watchlist_snapshot(
                department=department,
                snapshot_ts=when,
                rows=top_rows,
                user_id=int(self.current_user_id) if self.current_user_id is not None else None,
            )
        except Exception:
            return 0

    def capture_watchlist_snapshot(self) -> None:
        if not self._require_role("Snapshot Watchlist", "admin", "medic", "asistent", "receptie"):
            return
        if not self.dashboard_watchlist_map:
            self.refresh_dashboard()
        rows = list(self.dashboard_watchlist_map.values())
        if not rows:
            messagebox.showinfo("Watchlist", "Nu exista date in watchlist pentru snapshot.")
            return
        department, _on_date = self._resolve_dashboard_filters(persist=True)
        snapshot_ts = now_ts()
        saved = self._persist_watchlist_snapshot(rows, department, snapshot_ts)
        self._audit(
            "watchlist_snapshot",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("ts", snapshot_ts),
                ("rows", saved),
            ),
        )
        self.refresh_watchlist_history_panel()
        messagebox.showinfo(
            "Snapshot Watchlist",
            f"Snapshot salvat ({saved} randuri) la {snapshot_ts}.",
        )

    def refresh_watchlist_history_panel(self) -> None:
        if not hasattr(self, "dashboard_watchlist_snapshots_tree") or not hasattr(self, "dashboard_watchlist_trend_tree"):
            return

        for iid in self.dashboard_watchlist_snapshots_tree.get_children():
            self.dashboard_watchlist_snapshots_tree.delete(iid)
        for iid in self.dashboard_watchlist_trend_tree.get_children():
            self.dashboard_watchlist_trend_tree.delete(iid)

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        hours = self._watchlist_history_hours()
        positive_only = self._watchlist_history_positive_only()

        snapshots = self.db.list_watchlist_snapshot_runs(department=department, limit=20)
        for row in snapshots:
            self.dashboard_watchlist_snapshots_tree.insert(
                "",
                END,
                values=(
                    row["snapshot_ts"],
                    row["rows_count"],
                    row["max_score"],
                    row["avg_score"],
                ),
            )

        trends_raw = self.db.get_watchlist_trend_top(department=department, hours=hours, limit=50)
        trends = [row for row in trends_raw if int(row["delta"] or 0) > 0] if positive_only else list(trends_raw)
        self.dashboard_watchlist_trend_rows = [
            {
                "delta": int(row["delta"] or 0),
                "score_now": int(row["score_now"] or 0),
                "patient": f"{(row['last_name'] or '').strip()} {(row['first_name'] or '').strip()}".strip() or "-",
                "mrn": row["mrn"] or "-",
            }
            for row in trends
        ]
        self._render_watchlist_history_trend_tree(limit=10)
        trends_count = min(10, len(self.dashboard_watchlist_trend_rows))

        section_name = department or "toate sectiile"
        mode_text = "doar cresteri" if positive_only else "toate trendurile"
        if hasattr(self, "watchlist_history_status_var"):
            self.watchlist_history_status_var.set(
                f"Istoric {section_name}: {len(snapshots)} snapshot-uri, {trends_count} trenduri ({mode_text}) in ultimele {hours}h."
            )

    def _watchlist_history_sort_key(self, row: Dict[str, Any], column: str) -> Any:
        if column == "delta":
            return int(row.get("delta") or 0)
        if column == "score_now":
            return int(row.get("score_now") or 0)
        return str(row.get(column) or "").lower()

    def _render_watchlist_history_trend_tree(self, *, limit: int = 10) -> None:
        if not hasattr(self, "dashboard_watchlist_trend_tree"):
            return
        for iid in self.dashboard_watchlist_trend_tree.get_children():
            self.dashboard_watchlist_trend_tree.delete(iid)
        sorted_rows = sorted(
            self.dashboard_watchlist_trend_rows,
            key=lambda row: self._watchlist_history_sort_key(row, str(self.watchlist_history_sort_column)),
            reverse=bool(self.watchlist_history_sort_desc),
        )
        for row in sorted_rows[: max(1, int(limit))]:
            delta = int(row.get("delta") or 0)
            delta_text = f"+{delta}" if delta > 0 else str(delta)
            tags: Tuple[str, ...]
            if delta > 0:
                tags = ("trend_up",)
            elif delta < 0:
                tags = ("trend_down",)
            else:
                tags = ("trend_flat",)
            self.dashboard_watchlist_trend_tree.insert(
                "",
                END,
                values=(
                    delta_text,
                    int(row.get("score_now") or 0),
                    row.get("patient") or "-",
                    row.get("mrn") or "-",
                ),
                tags=tags,
            )

    def _toggle_watchlist_history_sort(self, column: str) -> None:
        col = (column or "").strip()
        if not col:
            return
        if self.watchlist_history_sort_column == col:
            self.watchlist_history_sort_desc = not bool(self.watchlist_history_sort_desc)
        else:
            self.watchlist_history_sort_column = col
            self.watchlist_history_sort_desc = True if col in {"delta", "score_now"} else False
        self._persist_watchlist_history_preferences()
        self._render_watchlist_history_trend_tree(limit=10)

    def _watchlist_history_hours(self) -> int:
        try:
            hours = int((self.watchlist_history_hours_var.get() or "24").strip())
        except Exception:
            hours = 24
            if hasattr(self, "watchlist_history_hours_var"):
                self.watchlist_history_hours_var.set("24")
        hours = max(1, min(24 * 30, hours))
        if hasattr(self, "watchlist_history_hours_var"):
            self.watchlist_history_hours_var.set(str(hours))
        self._persist_watchlist_history_preferences()
        return hours

    def _watchlist_history_positive_only(self) -> bool:
        mode = (self.watchlist_history_mode_var.get() if hasattr(self, "watchlist_history_mode_var") else "Toate").strip().lower()
        return "crest" in mode

    def _persist_watchlist_history_preferences(self) -> None:
        try:
            hours = int((self.watchlist_history_hours_var.get() if hasattr(self, "watchlist_history_hours_var") else "24") or "24")
        except Exception:
            hours = 24
        hours = max(1, min(24 * 30, hours))
        payload = {
            "WATCHLIST_HISTORY_HOURS": str(hours),
            "WATCHLIST_HISTORY_MODE": "Doar cresteri" if self._watchlist_history_positive_only() else "Toate",
            "WATCHLIST_HISTORY_SORT_COLUMN": str(getattr(self, "watchlist_history_sort_column", "delta") or "delta"),
            "WATCHLIST_HISTORY_SORT_DESC": "1" if bool(getattr(self, "watchlist_history_sort_desc", True)) else "0",
        }
        try:
            self.db.set_settings(payload)
        except Exception:
            pass

    def _persist_dashboard_filter_preferences(self, department: str, operational_date: str) -> None:
        payload = {
            "DASHBOARD_FILTER_DEPARTMENT": (department or "").strip(),
            "DASHBOARD_OPERATIONAL_DATE": (operational_date or "").strip(),
        }
        try:
            self.db.set_settings(payload)
        except Exception:
            pass

    def _persist_patient_filter_preferences(self, status_filter: str, status_date: str) -> None:
        payload = {
            "PATIENT_STATUS_FILTER": (status_filter or "all").strip().lower(),
            "PATIENT_STATUS_DATE": (status_date or "").strip(),
        }
        try:
            self.db.set_settings(payload)
        except Exception:
            pass

    def _resolve_patient_filters(self, *, persist: bool = True) -> Tuple[str, str]:
        selected_label = (self.patient_status_filter_var.get() or "Toti pacientii").strip()
        status_filter = self.patient_status_filter_map.get(selected_label, "all")
        raw_date = (self.patient_status_date_var.get() or "").strip() if hasattr(self, "patient_status_date_var") else ""
        status_date = raw_date or datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(status_date, "%Y-%m-%d")
        except Exception:
            status_date = datetime.now().strftime("%Y-%m-%d")
        if persist:
            self._persist_patient_filter_preferences(status_filter, status_date)
        return status_filter, status_date

    def _resolve_dashboard_filters(self, *, persist: bool = True) -> Tuple[str, str]:
        department = self.dashboard_department_var.get().strip() if hasattr(self, "dashboard_department_var") else ""
        raw_date = (
            self.dashboard_operational_date_var.get().strip()
            if hasattr(self, "dashboard_operational_date_var")
            else datetime.now().strftime("%Y-%m-%d")
        )
        operational_date = parse_iso_date(raw_date) or date.today()
        operational_date_txt = operational_date.isoformat()
        if hasattr(self, "dashboard_department_var"):
            self.dashboard_department_var.set(department)
        if hasattr(self, "dashboard_operational_date_var"):
            self.dashboard_operational_date_var.set(operational_date_txt)
        if persist:
            self._persist_dashboard_filter_preferences(department, operational_date_txt)
        return department, operational_date_txt

    def reset_watchlist_history_preferences(self) -> None:
        default_hours = 24
        default_mode = "Toate"
        default_sort_column = "delta"
        default_sort_desc = True

        if hasattr(self, "watchlist_history_hours_var"):
            self.watchlist_history_hours_var.set(str(default_hours))
        if hasattr(self, "watchlist_history_mode_var"):
            self.watchlist_history_mode_var.set(default_mode)
        self.watchlist_history_sort_column = default_sort_column
        self.watchlist_history_sort_desc = default_sort_desc

        self._persist_watchlist_history_preferences()
        self.refresh_watchlist_history_panel()
        messagebox.showinfo(
            "Istoric watchlist",
            "Preferintele au fost resetate la valorile implicite (24h, Toate, sortare Trend desc).",
        )

    def reset_dashboard_filter_preferences(self) -> None:
        if hasattr(self, "dashboard_department_var"):
            self.dashboard_department_var.set("")
        if hasattr(self, "dashboard_operational_date_var"):
            self.dashboard_operational_date_var.set(date.today().isoformat())
        department, operational_date_txt = self._resolve_dashboard_filters(persist=True)
        self.refresh_dashboard()
        messagebox.showinfo(
            "Dashboard",
            f"Filtrele Dashboard au fost resetate (sectie: {department or 'toate'}, data: {operational_date_txt}).",
        )

    def reset_patient_filter_preferences(self) -> None:
        if hasattr(self, "patient_status_filter_var"):
            self.patient_status_filter_var.set("Toti pacientii")
        if hasattr(self, "patient_status_date_var"):
            self.patient_status_date_var.set(date.today().isoformat())
        status_filter, status_date = self._resolve_patient_filters(persist=True)
        self.refresh_patients()
        label = next((text for text, key in self.patient_status_filter_map.items() if key == status_filter), "Toti pacientii")
        messagebox.showinfo(
            "Filtre receptie",
            f"Filtrele receptie au fost resetate (status: {label}, data: {status_date}).",
        )

    def reset_dashboard_and_history_preferences(self) -> None:
        if hasattr(self, "dashboard_department_var"):
            self.dashboard_department_var.set("")
        if hasattr(self, "dashboard_operational_date_var"):
            self.dashboard_operational_date_var.set(date.today().isoformat())

        if hasattr(self, "watchlist_history_hours_var"):
            self.watchlist_history_hours_var.set("24")
        if hasattr(self, "watchlist_history_mode_var"):
            self.watchlist_history_mode_var.set("Toate")
        self.watchlist_history_sort_column = "delta"
        self.watchlist_history_sort_desc = True

        department, operational_date_txt = self._resolve_dashboard_filters(persist=True)
        self._persist_watchlist_history_preferences()
        self.refresh_dashboard()
        messagebox.showinfo(
            "Dashboard",
            (
                "Preferintele Dashboard + Istoric watchlist au fost resetate "
                f"(sectie: {department or 'toate'}, data: {operational_date_txt}, istoric: 24h/Toate/Trend desc)."
            ),
        )

    def request_dashboard_refresh(self) -> None:
        now_tick = time.monotonic()
        cooldown = max(0.1, float(getattr(self, "dashboard_refresh_debounce_seconds", 0.8) or 0.8))
        last_tick = float(getattr(self, "_dashboard_refresh_last_click_ts", 0.0) or 0.0)
        elapsed = now_tick - last_tick
        if elapsed < cooldown:
            self._show_debounce_feedback("Refresh Dashboard", cooldown - elapsed)
            return
        self._dashboard_refresh_last_click_ts = now_tick
        self.refresh_dashboard()

    def _show_debounce_feedback(self, action_label: str, remaining_seconds: float) -> None:
        if not hasattr(self, "root"):
            return
        remaining = max(0.1, float(remaining_seconds or 0.1))
        remaining_text = f"{remaining:.2f}" if remaining < 1.0 else f"{remaining:.1f}"
        text = f"{action_label}: asteapta ~{remaining_text}s inainte de urmatorul click."

        target_var: Optional[Any] = None
        if hasattr(self, "watchlist_history_status_var"):
            target_var = self.watchlist_history_status_var
        elif hasattr(self, "settings_hint_var"):
            target_var = self.settings_hint_var
        elif hasattr(self, "alert_status_var"):
            target_var = self.alert_status_var

        if target_var is None:
            return

        try:
            previous = str(target_var.get())
        except Exception:
            previous = ""

        try:
            target_var.set(text)
        except Exception:
            return

        if self._debounce_feedback_job:
            try:
                self.root.after_cancel(self._debounce_feedback_job)
            except Exception:
                pass
            self._debounce_feedback_job = None

        self._debounce_feedback_restore = (target_var, previous)

        def _restore_feedback() -> None:
            restore_ctx = self._debounce_feedback_restore
            self._debounce_feedback_restore = None
            self._debounce_feedback_job = None
            if not restore_ctx:
                return
            restore_var, restore_text = restore_ctx
            try:
                restore_var.set(restore_text)
            except Exception:
                pass

        self._debounce_feedback_job = self.root.after(1400, _restore_feedback)

    def _allow_debounced_action(self, action_key: str, cooldown_seconds: float) -> bool:
        key = (action_key or "").strip()
        if not key:
            return True
        cooldown = max(0.1, float(cooldown_seconds or 0.1))
        now_tick = time.monotonic()
        last_tick = float(self._action_last_run_ts.get(key, 0.0) or 0.0)
        if now_tick - last_tick < cooldown:
            return False
        self._action_last_run_ts[key] = now_tick
        return True

    def _debounce_remaining_seconds(self, action_key: str, cooldown_seconds: float) -> float:
        key = (action_key or "").strip()
        if not key:
            return 0.0
        cooldown = max(0.1, float(cooldown_seconds or 0.1))
        last_tick = float(self._action_last_run_ts.get(key, 0.0) or 0.0)
        if last_tick <= 0:
            return 0.0
        remaining = cooldown - (time.monotonic() - last_tick)
        return remaining if remaining > 0 else 0.0

    def request_export_action(self, action_key: str, callback: Any, *, cooldown_seconds: Optional[float] = None) -> None:
        cooldown = (
            float(cooldown_seconds)
            if cooldown_seconds is not None
            else float(getattr(self, "export_debounce_seconds", 0.9) or 0.9)
        )
        key = (action_key or "").strip() or "export"

        feedback_label = "Export"
        key_l = key.lower()
        if key_l.startswith("settings_import") or "import" in key_l:
            feedback_label = "Import setari"
        elif "pdf" in key_l:
            feedback_label = "Export PDF"
        elif "csv" in key_l:
            feedback_label = "Export CSV"
        elif "quick" in key_l:
            feedback_label = "Export rapid"

        debounce_key = f"export::{key}"
        if not self._allow_debounced_action(debounce_key, cooldown):
            self._show_debounce_feedback(feedback_label, self._debounce_remaining_seconds(debounce_key, cooldown))
            return
        if callable(callback):
            callback()
            self._track_handoff_status_after_action(key)

    def _track_handoff_status_after_action(self, action_key: str) -> None:
        key = (action_key or "").strip()
        if not key:
            return
        should_track = key.startswith("fo_package_") or key.startswith("fo_handoff_")
        if not should_track:
            return
        ts = now_ts()
        self.handoff_last_action_key = key
        self.handoff_last_action_ts = ts
        recent = [{"key": key, "ts": ts}]
        for item in list(getattr(self, "handoff_recent_actions", []) or []):
            if not isinstance(item, dict):
                continue
            item_key = str(item.get("key") or "").strip()
            item_ts = str(item.get("ts") or "").strip()
            if not item_key:
                continue
            if item_key == key and item_ts == ts:
                continue
            recent.append({"key": item_key, "ts": item_ts})
        self.handoff_recent_actions = recent[:5]
        try:
            self.db.set_setting("HANDOFF_LAST_ACTION", key)
            self.db.set_setting("HANDOFF_LAST_ACTION_TS", ts)
            self.db.set_setting(
                "HANDOFF_RECENT_ACTIONS",
                json.dumps(self.handoff_recent_actions, ensure_ascii=False),
            )
        except Exception:
            pass

    @staticmethod
    def _parse_handoff_recent_actions(raw: str) -> List[Dict[str, str]]:
        try:
            payload = json.loads(str(raw or "[]"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        parsed: List[Dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            ts = str(item.get("ts") or "").strip()
            if not key:
                continue
            parsed.append({"key": key, "ts": ts})
            if len(parsed) >= 5:
                break
        return parsed

    @staticmethod
    def _normalize_handoff_status_filter_mode(mode: str) -> str:
        value = str(mode or "all").strip().lower()
        if value in {"all", "minimal", "all_in"}:
            return value
        return "all"

    @staticmethod
    def _handoff_status_filter_label(mode: str) -> str:
        value = str(mode or "all").strip().lower()
        return {
            "all": "all",
            "minimal": "minim",
            "all_in": "all-in",
        }.get(value, "all")

    @staticmethod
    def _handoff_status_audit_action(base_action: str, mode: str) -> str:
        if base_action not in HANDOFF_STATUS_AUDIT_BASE_ACTIONS:
            return base_action
        normalized_mode = str(mode or "all").strip().lower()
        suffix = HANDOFF_STATUS_AUDIT_MODE_SUFFIX.get(normalized_mode, "")
        return f"{base_action}{suffix}" if suffix else base_action

    @staticmethod
    def _handoff_status_mode_from_audit_action(action: str) -> str:
        key = str(action or "").strip().lower()
        if key.endswith("_minimal"):
            return "minimal"
        if key.endswith("_all_in"):
            return "all_in"
        return "all"

    @staticmethod
    def _normalize_exported_by(value: str) -> str:
        normalized = str(value or "").strip()
        return normalized or "-"

    @staticmethod
    def _handoff_status_audit_actions_set() -> set[str]:
        actions: set[str] = set()
        for base in HANDOFF_STATUS_AUDIT_BASE_ACTIONS:
            actions.add(base)
            for suffix in HANDOFF_STATUS_AUDIT_MODE_SUFFIX.values():
                if suffix:
                    actions.add(f"{base}{suffix}")
        return actions

    @staticmethod
    def _handoff_status_audit_actions_sorted() -> List[str]:
        return sorted(App._handoff_status_audit_actions_set())

    @staticmethod
    def _handoff_status_events_hash(rows: List[Dict[str, Any]]) -> str:
        try:
            payload = json.dumps(list(rows or []), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            payload = "[]"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _handoff_status_checksum_from_lines(lines: List[str]) -> str:
        for line in reversed(list(lines or [])):
            text = str(line or "").strip()
            if not text.startswith("StatusChecksum:"):
                continue
            return (text.split(":", 1)[1] if ":" in text else "").strip() or "-"
        return "-"

    @staticmethod
    def _handoff_status_checksum_from_payload(payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return "-"
        footer = payload.get("footer")
        if not isinstance(footer, dict):
            return "-"
        return str(footer.get("StatusChecksum") or "-").strip() or "-"

    @staticmethod
    def _handoff_status_line_count_from_payload(payload: Dict[str, Any]) -> int:
        if not isinstance(payload, dict):
            return 0
        try:
            return max(0, int(payload.get("lineCount", 0)))
        except Exception:
            return 0

    @staticmethod
    def _handoff_status_audit_details(*, mode: str, mode_label: str, line_count: Any, status_checksum: str) -> str:
        try:
            normalized_line_count = max(0, int(line_count))
        except Exception:
            normalized_line_count = 0
        normalized_checksum = str(status_checksum or "-").strip() or "-"
        return (
            f"mode={str(mode or '').strip()}; "
            f"mode_label={str(mode_label or '').strip()}; "
            f"lineCount={normalized_line_count}; "
            f"statusChecksum={normalized_checksum}"
        )

    def _handoff_status_mode_audit_context(self, base_action: str, mode: str) -> Tuple[str, str]:
        mode_label = self._handoff_status_filter_label(mode)
        audit_action = self._handoff_status_audit_action(base_action, mode)
        return mode_label, audit_action

    def _set_clipboard_text(self, value: Any) -> None:
        payload = str(value or "")
        self.root.clipboard_clear()
        self.root.clipboard_append(payload)

    def _audit_current_patient(self, action: str, details: str = "") -> None:
        self._audit(action, details, self.current_patient_id)

    @staticmethod
    def _audit_encode_detail_value(value: Any) -> str:
        text = str(value if value is not None else "-").strip() or "-"
        if any(ch in text for ch in (";", "|", "=", "\n", "\r")):
            return f"urlenc:{urllib_parse.quote(text, safe='')}"
        return text

    @staticmethod
    def _audit_decode_detail_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return text
        if text.startswith("urlenc:"):
            encoded = text[len("urlenc:") :]
            try:
                return urllib_parse.unquote(encoded)
            except Exception:
                return encoded
        return text

    @staticmethod
    def _audit_details_from_pairs(*pairs: Tuple[str, Any]) -> str:
        parts: List[str] = []
        for key, value in pairs:
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            normalized_value = App._audit_encode_detail_value(value)
            parts.append(f"{normalized_key}={normalized_value}")
        return "; ".join(parts)

    @staticmethod
    def _handoff_status_feedback_note(*, line_count: Any, status_checksum: str) -> str:
        try:
            normalized_line_count = max(0, int(line_count))
        except Exception:
            normalized_line_count = 0
        normalized_checksum = str(status_checksum or "-").strip() or "-"
        return f"lineCount={normalized_line_count}; statusChecksum={normalized_checksum}"

    @staticmethod
    def _handoff_action_label(action_key: str) -> str:
        key = (action_key or "").strip().lower()
        labels = {
            "fo_package_handoff_minimal": "Handoff minim",
            "fo_package_handoff_minimal_open_zip": "Handoff minim + deschide ZIP",
            "fo_package_handoff_minimal_open_zip_email": "Handoff minim + ZIP + e-mail",
            "fo_package_handoff_minimal_open_zip_email_checklist": "Handoff minim + ZIP + e-mail + checklist",
            "fo_package_handoff_minimal_all_in": "Handoff minim all-in",
            "fo_handoff_reset": "Reseteaza blocul Handoff FO",
        }
        if key in labels:
            return labels[key]
        friendly = key.replace("_", " ").strip()
        return friendly.capitalize() if friendly else "-"

    def request_dashboard_watchlist_history_quick_export(self) -> None:
        self.request_export_action(
            "quick_export_watchlist_history",
            self.export_dashboard_watchlist_history_quick,
            cooldown_seconds=self.quick_export_debounce_seconds,
        )

    def request_watchlist_export_perf_quick(self) -> None:
        self.request_export_action(
            "quick_export_watchlist_perf",
            self.export_watchlist_export_perf_quick,
            cooldown_seconds=self.quick_export_debounce_seconds,
        )

    def refresh_dashboard(self) -> None:
        department, _operational_date_txt = self._resolve_dashboard_filters(persist=True)
        self._refresh_watchlist_formula_hint()
        kpi = self.db.get_dashboard_kpis(department=department)
        self.kpi_active_var.set(f"Internari active: {kpi['active_admissions']}")
        self.kpi_triage_var.set(f"Triage 1-2: {kpi['triage_1_2']}")
        self.kpi_orders_var.set(f"Ordine urgente: {kpi['urgent_orders']}")
        self.kpi_alerts_var.set(f"Alerte vitale 24h: {kpi['vital_alerts_24h']}")

        for iid in self.dashboard_admission_tree.get_children():
            self.dashboard_admission_tree.delete(iid)
        for iid in self.dashboard_order_tree.get_children():
            self.dashboard_order_tree.delete(iid)
        for iid in self.dashboard_alert_tree.get_children():
            self.dashboard_alert_tree.delete(iid)
        for iid in self.dashboard_watchlist_tree.get_children():
            self.dashboard_watchlist_tree.delete(iid)
        self.dashboard_admission_map.clear()
        self.dashboard_order_map.clear()
        self.dashboard_alert_map.clear()
        self.dashboard_watchlist_map.clear()

        admissions = self.db.list_active_admissions_dashboard(department=department, limit=1000)
        for row in admissions:
            iid = str(row["id"])
            self.dashboard_admission_map[iid] = dict(row)
            triage = int(row["triage_level"] or 3)
            tags: List[str] = []
            if triage <= 1:
                tags.append("triage_critical")
            elif triage <= 2:
                tags.append("triage_high")
            self.dashboard_admission_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["mrn"],
                    f"{row['last_name']} {row['first_name']}",
                    row["triage_level"],
                    row["department"],
                    row["ward"],
                    row["bed"],
                    row["attending_clinician"],
                    row["admitted_at"],
                ),
                tags=tuple(tags),
            )

        orders = self.db.list_urgent_orders_dashboard(department=department, limit=1000)
        for row in orders:
            iid = str(row["id"])
            self.dashboard_order_map[iid] = dict(row)
            text_preview = (row["order_text"] or "").replace("\n", " ").strip()
            if len(text_preview) > 80:
                text_preview = text_preview[:77] + "..."
            tags = []
            if (row["priority"] or "").strip().lower() == "stat":
                tags.append("order_stat")
            else:
                tags.append("order_urgent")
            if (row["status"] or "").strip().lower() == "in_progress":
                tags.append("order_in_progress")
            self.dashboard_order_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    f"{row['last_name']} {row['first_name']}",
                    row["mrn"] or "-",
                    row["order_type"],
                    row["priority"],
                    row["status"],
                    row["ordered_at"],
                    text_preview,
                ),
                tags=tuple(tags),
            )

        alerts = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=1000)
        acked_ids = self.db.get_acknowledged_vital_ids([int(r["id"]) for r in alerts])
        for row in alerts:
            iid = str(row["id"])
            self.dashboard_alert_map[iid] = dict(row)
            notes_preview = (row.get("notes") or "").replace("\n", " ").strip()
            if len(notes_preview) > 70:
                notes_preview = notes_preview[:67] + "..."
            if int(row["id"]) in acked_ids:
                tags = ["alert_ack"]
            else:
                tags = ["alert_critical"] if self._is_critical_alert_reasons(row["reasons"]) else ["alert_warning"]
            self.dashboard_alert_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    f"{row['last_name']} {row['first_name']}",
                    row.get("mrn") or "-",
                    row["recorded_at"],
                    row["reasons"],
                    notes_preview,
                ),
                tags=tuple(tags),
            )

        watchlist_rows = self._compute_watchlist_rows(admissions, orders, alerts, acked_ids)
        self.dashboard_watchlist_snapshot_ts = self._apply_watchlist_trend(watchlist_rows, department)
        high_thr = max(1, int(getattr(self, "watchlist_score_high_threshold", 90)))
        medium_thr = max(1, int(getattr(self, "watchlist_score_medium_threshold", 60)))
        max_medium = high_thr - 1 if high_thr > 1 else 1
        if medium_thr > max_medium:
            medium_thr = max_medium
        for idx, row in enumerate(watchlist_rows[:10], start=1):
            iid = str(idx)
            self.dashboard_watchlist_map[iid] = row
            tags: Tuple[str, ...] = ()
            if int(row["score"]) >= high_thr:
                tags = ("watchlist_high",)
            elif int(row["score"]) >= medium_thr:
                tags = ("watchlist_medium",)
            self.dashboard_watchlist_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["score"],
                    row.get("trend_label", "NOU"),
                    row["patient_name"],
                    row["mrn"],
                    row["triage_level"],
                    row["department"],
                    row["signals"],
                ),
                tags=tags,
            )
            self.refresh_watchlist_history_panel()

    def clear_audit_filters(self) -> None:
        if not self._has_role("admin", "medic"):
            return
        self.audit_filter_vars["username"].set("")
        self.audit_filter_vars["action"].set("")
        self.audit_filter_vars["patient_id"].set("")
        self.audit_filter_vars["date_from"].set("")
        self.audit_filter_vars["date_to"].set("")
        self.refresh_audit()

    def refresh_audit(self) -> None:
        if not self._has_role("admin", "medic"):
            return
        for iid in self.audit_tree.get_children():
            self.audit_tree.delete(iid)
        self.audit_map.clear()

        patient_id_val: Optional[int] = None
        raw_patient_id = self.audit_filter_vars["patient_id"].get().strip()
        if raw_patient_id:
            if not raw_patient_id.isdigit():
                messagebox.showerror("Filtru invalid", "Patient ID trebuie sa fie numeric.")
                return
            patient_id_val = int(raw_patient_id)

        rows = self.db.list_recent_audit(
            limit=2000,
            username=self.audit_filter_vars["username"].get().strip(),
            action=self.audit_filter_vars["action"].get().strip(),
            patient_id=patient_id_val,
            date_from=self.audit_filter_vars["date_from"].get().strip(),
            date_to=self.audit_filter_vars["date_to"].get().strip(),
        )
        for row in rows:
            iid = str(row["id"])
            self.audit_map[iid] = dict(row)
            detail_preview = (row["details"] or "").replace("\n", " ").strip()
            if len(detail_preview) > 120:
                detail_preview = detail_preview[:117] + "..."
            self.audit_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["created_at"],
                    row["username"],
                    row["action"],
                    row["patient_id"] or "-",
                    row["patient_name"] or "-",
                    detail_preview,
                ),
            )

    def refresh_operational_views(self) -> None:
        self.refresh_dashboard()
        if self._has_role("admin", "medic", "receptie") and hasattr(self, "stats_daily_tree"):
            self.refresh_statistics()

    def export_audit_csv(self) -> None:
        if not self._require_role("Export audit CSV", "admin", "medic"):
            return
        rows = list(self.audit_map.values())
        if not rows:
            rows_raw = self.db.list_recent_audit(limit=2000)
            rows = [dict(r) for r in rows_raw]
        if not rows:
            messagebox.showinfo("Audit", "Nu exista date pentru export.")
            return
        events_hash = self._handoff_status_events_hash(rows)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EXPORTS_DIR / f"audit_export_{stamp}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "created_at", "username", "action", "patient_id", "patient_name", "details"])
            for row in rows:
                writer.writerow(
                    [
                        row.get("id"),
                        row.get("created_at"),
                        row.get("username"),
                        row.get("action"),
                        row.get("patient_id"),
                        row.get("patient_name"),
                        row.get("details"),
                    ]
                )
        self._audit("export_audit_csv", self._export_audit_details(row_count=len(rows), events_hash=events_hash, out_path=out_path))
        self._show_export_success_message(
            "Audit",
            "Audit exportat",
            out_path,
            row_count=len(rows),
            extra_note=self._export_popup_note(row_count=len(rows), events_hash=events_hash),
        )

    def export_handoff_status_audit_csv(self) -> None:
        if not self._require_role("Export audit Handoff status CSV", "admin", "medic"):
            return
        rows = self._collect_handoff_status_audit_rows(limit=HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT)
        if not rows:
            messagebox.showinfo("Audit", "Nu exista evenimente Handoff status pentru export.")
            return
        exported_by = self._normalize_exported_by(str((self.current_user or {}).get("username") or ""))
        exported_by_role = normalize_role(str((self.current_user or {}).get("role") or ""))
        metadata = self._build_handoff_status_export_metadata(
            export_source="audit_tab_csv",
            exported_by=exported_by,
            exported_by_role=exported_by_role,
            row_count=len(rows),
        )
        action_keys = self._handoff_status_audit_actions_sorted()
        events_hash = self._handoff_status_events_hash(rows)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EXPORTS_DIR / f"{HANDOFF_STATUS_AUDIT_EXPORT_FILENAME_PREFIX}_{stamp}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            metadata_line = self._export_handoff_csv_metadata_line(
                metadata=metadata,
                action_keys_count=len(action_keys),
                events_hash=events_hash,
            )
            export_source = str((metadata or {}).get("exportSource") or "-")
            export_version = str((metadata or {}).get("exportVersion") or "-")
            exported_by = str((metadata or {}).get("exportedBy") or "-")
            exported_by_role = str((metadata or {}).get("exportedByRole") or "-")
            writer.writerow([metadata_line])
            writer.writerow([
                "id",
                "created_at",
                "username",
                "action",
                "mode",
                "mode_label",
                "export_source",
                "export_version",
                "exported_by",
                "exported_by_role",
                "patient_id",
                "patient_name",
                "details",
            ])
            for row in rows:
                action = str(row.get("action") or "")
                mode = self._handoff_status_mode_from_audit_action(action)
                writer.writerow(
                    [
                        row.get("id"),
                        row.get("created_at"),
                        row.get("username"),
                        action,
                        mode,
                        self._handoff_status_filter_label(mode),
                        export_source,
                        export_version,
                        exported_by,
                        exported_by_role,
                        row.get("patient_id"),
                        row.get("patient_name"),
                        row.get("details"),
                    ]
                )

        self._audit(
            "export_handoff_status_audit_csv",
            self._export_audit_details(row_count=len(rows), events_hash=events_hash, out_path=out_path),
        )
        self._show_export_success_message(
            "Audit",
            "Audit Handoff status exportat",
            out_path,
            row_count=len(rows),
            row_limit=HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT,
            extra_note=self._export_popup_note(row_count=len(rows), events_hash=events_hash),
        )

    def export_handoff_status_audit_json(self) -> None:
        if not self._require_role("Export audit Handoff status JSON", "admin", "medic"):
            return
        rows = self._collect_handoff_status_audit_rows(limit=HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT)
        if not rows:
            messagebox.showinfo("Audit", "Nu exista evenimente Handoff status pentru export.")
            return
        exported_by = self._normalize_exported_by(str((self.current_user or {}).get("username") or ""))
        exported_by_role = normalize_role(str((self.current_user or {}).get("role") or ""))
        metadata = self._build_handoff_status_export_metadata(
            export_source="audit_tab_json",
            exported_by=exported_by,
            exported_by_role=exported_by_role,
            row_count=len(rows),
        )
        action_keys = self._handoff_status_audit_actions_sorted()
        events_hash = self._handoff_status_events_hash(rows)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EXPORTS_DIR / f"{HANDOFF_STATUS_AUDIT_EXPORT_FILENAME_PREFIX}_{stamp}.json"
        payload = {
            **metadata,
            "actionKeys": action_keys,
            "actionKeysCount": len(action_keys),
            "eventsHash": events_hash,
            "events": rows,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self._audit(
            "export_handoff_status_audit_json",
            self._export_audit_details(row_count=len(rows), events_hash=events_hash, out_path=out_path),
        )
        self._show_export_success_message(
            "Audit",
            "Audit Handoff status JSON exportat",
            out_path,
            row_count=len(rows),
            row_limit=HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT,
            extra_note=self._export_popup_note(row_count=len(rows), events_hash=events_hash),
        )

    def _collect_handoff_status_audit_rows(self, *, limit: int = HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT) -> List[Dict[str, Any]]:
        try:
            normalized_limit = max(1, int(limit))
        except Exception:
            normalized_limit = HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT
        allowed_actions = self._handoff_status_audit_actions_set()
        rows_raw = self.db.list_recent_audit(limit=normalized_limit)
        rows: List[Dict[str, Any]] = []
        for raw in rows_raw:
            row = dict(raw)
            action = str(row.get("action") or "")
            if action not in allowed_actions:
                continue
            mode = self._handoff_status_mode_from_audit_action(action)
            rows.append(
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "username": row.get("username"),
                    "action": action,
                    "mode": mode,
                    "mode_label": self._handoff_status_filter_label(mode),
                    "patient_id": row.get("patient_id"),
                    "patient_name": row.get("patient_name"),
                    "details": row.get("details"),
                }
            )
            if len(rows) >= normalized_limit:
                break
        return rows

    @staticmethod
    def _build_handoff_status_export_metadata(
        *,
        export_source: str,
        exported_by: str,
        exported_by_role: str,
        row_count: int,
    ) -> Dict[str, Any]:
        normalized_source = str(export_source or "").strip()
        if normalized_source not in HANDOFF_STATUS_EXPORT_SOURCES:
            normalized_source = "audit_tab_json"
        try:
            normalized_row_count = max(0, int(row_count))
        except Exception:
            normalized_row_count = 0
        return {
            "schema": HANDOFF_STATUS_AUDIT_EXPORT_SCHEMA,
            "schemaVersion": HANDOFF_STATUS_AUDIT_EXPORT_SCHEMA_VERSION,
            "generatedAt": now_ts(),
            "generatedAtUnix": int(time.time()),
            "timezone": APP_TIMEZONE,
            "exportSource": normalized_source,
            "exportVersion": HANDOFF_STATUS_AUDIT_EXPORT_VERSION,
            "exportedBy": App._normalize_exported_by(str(exported_by or "")),
            "exportedByRole": normalize_role(str(exported_by_role or "")),
            "rowCount": normalized_row_count,
        }

    @staticmethod
    def _export_handoff_csv_metadata_line(*, metadata: Dict[str, Any], action_keys_count: int, events_hash: str) -> str:
        metadata_map = dict(metadata or {})
        export_source = str(metadata_map.get("exportSource") or "-").strip() or "-"
        export_version = str(metadata_map.get("exportVersion") or "-").strip() or "-"
        schema_version = str(metadata_map.get("schemaVersion") or HANDOFF_STATUS_AUDIT_EXPORT_SCHEMA_VERSION).strip() or HANDOFF_STATUS_AUDIT_EXPORT_SCHEMA_VERSION
        exported_by = str(metadata_map.get("exportedBy") or "-").strip() or "-"
        exported_by_role = str(metadata_map.get("exportedByRole") or "-").strip() or "-"
        generated_at = str(metadata_map.get("generatedAt") or now_ts()).strip() or now_ts()
        try:
            generated_at_unix = int(metadata_map.get("generatedAtUnix", int(time.time())))
        except Exception:
            generated_at_unix = int(time.time())
        timezone_name = str(metadata_map.get("timezone") or APP_TIMEZONE).strip() or APP_TIMEZONE
        try:
            normalized_action_keys_count = max(0, int(action_keys_count))
        except Exception:
            normalized_action_keys_count = 0
        try:
            normalized_row_count = max(0, int(metadata_map.get("rowCount", 0)))
        except Exception:
            normalized_row_count = 0
        return (
            f"# exportSource={export_source};"
            f"exportVersion={export_version};"
            f"schema_version={schema_version};"
            f"schemaVersion={schema_version};"
            f"exportedBy={exported_by};"
            f"exportedByRole={exported_by_role};"
            f"generatedAt={generated_at};"
            f"generatedAtUnix={generated_at_unix};"
            f"timezone={timezone_name};"
            f"rowCount={normalized_row_count};"
            f"actionKeysCount={normalized_action_keys_count};"
            f"eventsHash={str(events_hash or '').strip()}"
        )

    @staticmethod
    def _export_audit_details(*, row_count: int, events_hash: str, out_path: Path) -> str:
        try:
            normalized_count = max(0, int(row_count))
        except Exception:
            normalized_count = 0
        normalized_hash = str(events_hash or "").strip()
        return f"rows={normalized_count}; rowCount={normalized_count}; eventsHash={normalized_hash}; path={out_path}"

    @staticmethod
    def _export_popup_note(*, row_count: int, events_hash: str) -> str:
        try:
            normalized_count = max(0, int(row_count))
        except Exception:
            normalized_count = 0
        normalized_hash = str(events_hash or "").strip()
        return f"rowCount={normalized_count}; eventsHash={normalized_hash}"

    @staticmethod
    def _show_export_success_message(
        title: str,
        subject: str,
        out_path: Path,
        *,
        row_count: Optional[int] = None,
        row_limit: Optional[int] = None,
        extra_note: Optional[str] = None,
    ) -> None:
        base = str(subject or "Export finalizat").strip() or "Export finalizat"
        details = ""
        if row_count is not None and row_limit is not None:
            details = f" ({int(row_count)} randuri, limita {int(row_limit)})"
        elif row_count is not None:
            details = f" ({int(row_count)} randuri)"
        note = str(extra_note or "").strip()
        note_suffix = f"\n{note}" if note else ""
        messagebox.showinfo(str(title or "Export"), f"{base}{details}:\n{out_path}{note_suffix}")

    @staticmethod
    def _audit_export_profile_text() -> str:
        return (
            "Export profile: General = filtru audit curent | "
            f"Handoff = ultimele {HANDOFF_STATUS_AUDIT_EXPORT_LIMIT_DEFAULT}, schema v1"
        )

    def open_patient_from_audit(self) -> None:
        if not self._has_role("admin", "medic"):
            return
        selected = self.audit_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza un rand de audit.")
            return
        row = self.audit_map.get(selected[0])
        if not row:
            return
        patient_id = row.get("patient_id")
        if not patient_id:
            messagebox.showinfo("Audit", "Acest eveniment nu are pacient asociat.")
            return
        self._open_patient_by_id(int(patient_id))

    def _open_patient_by_id(self, patient_id: int) -> None:
        if patient_id <= 0:
            return
        self._focus_patient(patient_id)
        try:
            self.notebook.select(self.tab_patient)
        except Exception:
            pass

    def open_patient_from_dashboard_admission(self) -> None:
        selected = self.dashboard_admission_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza o internare.")
            return
        row = self.dashboard_admission_map.get(selected[0])
        if not row:
            return
        self._open_patient_by_id(int(row["patient_id"]))

    def open_patient_from_dashboard_order(self) -> None:
        selected = self.dashboard_order_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza un ordin.")
            return
        row = self.dashboard_order_map.get(selected[0])
        if not row:
            return
        self._open_patient_by_id(int(row["patient_id"]))

    def open_patient_from_dashboard_alert(self) -> None:
        selected = self.dashboard_alert_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza o alerta.")
            return
        row = self.dashboard_alert_map.get(selected[0])
        if not row:
            return
        self._open_patient_by_id(int(row["patient_id"]))

    def open_patient_from_dashboard_watchlist(self) -> None:
        selected = self.dashboard_watchlist_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza un pacient din watchlist.")
            return
        row = self.dashboard_watchlist_map.get(selected[0])
        if not row:
            return
        self._open_patient_by_id(int(row["patient_id"]))

    def acknowledge_selected_dashboard_alert(self) -> None:
        selected = self.dashboard_alert_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza o alerta.")
            return
        row = self.dashboard_alert_map.get(selected[0])
        if not row:
            return
        vital_id = int(row["id"])
        if self.db.is_vital_alert_acknowledged(vital_id):
            messagebox.showinfo("Alerte", "Alerta este deja confirmata.")
            return
        self.db.acknowledge_vital_alert(vital_id, self.current_user.get("id"))
        self._audit(
            "ack_vital_alert",
            self._audit_details_from_pairs(("vital_id", vital_id)),
            int(row.get("patient_id") or 0),
        )
        self.refresh_dashboard()

    def set_stats_range(self, days: int) -> None:
        days = max(1, int(days))
        self.stats_filter_vars["date_to"].set(datetime.now().strftime("%Y-%m-%d"))
        self.stats_filter_vars["date_from"].set((datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d"))
        self._persist_statistics_filter_preferences()
        self.refresh_statistics()

    def _persist_statistics_filter_preferences(self) -> None:
        if not hasattr(self, "stats_filter_vars"):
            return
        payload = {
            "STATS_FILTER_DEPARTMENT": (self.stats_filter_vars["department"].get() or "").strip(),
            "STATS_FILTER_DATE_FROM": (self.stats_filter_vars["date_from"].get() or "").strip(),
            "STATS_FILTER_DATE_TO": (self.stats_filter_vars["date_to"].get() or "").strip(),
        }
        try:
            self.db.set_settings(payload)
        except Exception:
            pass

    def refresh_statistics(self) -> None:
        if not self._has_role("admin", "medic", "receptie"):
            return
        date_from = self.stats_filter_vars["date_from"].get().strip()
        date_to = self.stats_filter_vars["date_to"].get().strip()
        department = self.stats_filter_vars["department"].get().strip()
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Data invalida", "Format date statistici: YYYY-MM-DD.")
            return
        if dt_to < dt_from:
            date_from, date_to = date_to, date_from
            self.stats_filter_vars["date_from"].set(date_from)
            self.stats_filter_vars["date_to"].set(date_to)

        self.stats_filter_vars["department"].set(department)
        self._persist_statistics_filter_preferences()

        summary = self.db.get_statistics_summary(date_from=date_from, date_to=date_to, department=department)
        self.stats_kpi_vars["admissions"].set(f"Internari: {int(summary['admissions'])}")
        self.stats_kpi_vars["discharges"].set(f"Externari: {int(summary['discharges'])}")
        self.stats_kpi_vars["orders"].set(f"Ordine: {int(summary['orders'])}")
        self.stats_kpi_vars["vitals"].set(f"Vitale: {int(summary['vitals'])}")
        self.stats_kpi_vars["los"].set(f"LOS mediu (zile): {summary['avg_los_days']:.2f}")

        for iid in self.stats_daily_tree.get_children():
            self.stats_daily_tree.delete(iid)
        for iid in self.stats_weekly_tree.get_children():
            self.stats_weekly_tree.delete(iid)
        for iid in self.stats_operational_tree.get_children():
            self.stats_operational_tree.delete(iid)
        for iid in self.stats_operational_dept_tree.get_children():
            self.stats_operational_dept_tree.delete(iid)
        if hasattr(self, "stats_watchlist_export_tree"):
            for iid in self.stats_watchlist_export_tree.get_children():
                self.stats_watchlist_export_tree.delete(iid)

        self.stats_daily_data = self.db.get_daily_activity(date_from=date_from, date_to=date_to, department=department)
        weekly: Dict[str, Dict[str, int]] = {}
        for row in self.stats_daily_data:
            day_dt = datetime.strptime(row["day"], "%Y-%m-%d")
            iso_year, iso_week, _ = day_dt.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            bucket = weekly.setdefault(key, {"admissions": 0, "discharges": 0, "orders": 0, "vitals": 0})
            bucket["admissions"] += int(row["admissions"])
            bucket["discharges"] += int(row["discharges"])
            bucket["orders"] += int(row["orders"])
            bucket["vitals"] += int(row["vitals"])

        self.stats_weekly_data = []
        for week_key in sorted(weekly.keys()):
            rec = {"week": week_key}
            rec.update(weekly[week_key])
            self.stats_weekly_data.append(rec)

        for row in self.stats_daily_data:
            self.stats_daily_tree.insert(
                "",
                END,
                values=(row["day"], row["admissions"], row["discharges"], row["orders"], row["vitals"]),
            )
        for row in self.stats_weekly_data:
            self.stats_weekly_tree.insert(
                "",
                END,
                values=(row["week"], row["admissions"], row["discharges"], row["orders"], row["vitals"]),
            )

        self.stats_operational_data = self.db.get_daily_operational_activity(
            date_from=date_from,
            date_to=date_to,
            department=department,
        )
        total_scheduled_adm = sum(int(row["scheduled_admissions"]) for row in self.stats_operational_data)
        total_scheduled_dis = sum(int(row["scheduled_discharges"]) for row in self.stats_operational_data)
        total_no_final = sum(int(row["discharged_without_final_decont"]) for row in self.stats_operational_data)
        self.stats_operational_kpi_vars["scheduled_admissions"].set(f"Internari programate: {total_scheduled_adm}")
        self.stats_operational_kpi_vars["scheduled_discharges"].set(f"Externari programate: {total_scheduled_dis}")
        self.stats_operational_kpi_vars["discharged_without_final_decont"].set(
            f"Externati fara decont final: {total_no_final}"
        )
        for row in self.stats_operational_data:
            self.stats_operational_tree.insert(
                "",
                END,
                values=(
                    row["day"],
                    row["scheduled_admissions"],
                    row["scheduled_discharges"],
                    row["discharged_without_final_decont"],
                ),
            )

        self.stats_operational_by_department_data = self.db.get_operational_by_department(
            date_from=date_from,
            date_to=date_to,
            department=department,
        )
        alert_threshold = max(1, int(getattr(self, "operational_backlog_alert_threshold", 5)))
        warning_threshold = max(1, alert_threshold - 1)
        sections_alert: List[str] = []
        sections_warning: List[str] = []
        for row in self.stats_operational_by_department_data:
            department_name = str(row["department"])
            backlog = int(row["discharged_without_final_decont"])
            tags: Tuple[str, ...] = ()
            if backlog >= alert_threshold:
                tags = ("operational_backlog_alert",)
                sections_alert.append(department_name)
            elif backlog >= warning_threshold:
                tags = ("operational_backlog_warning",)
                sections_warning.append(department_name)
            self.stats_operational_dept_tree.insert(
                "",
                END,
                values=(
                    department_name,
                    row["scheduled_admissions"],
                    row["scheduled_discharges"],
                    row["discharged_without_final_decont"],
                    row["total"],
                ),
                tags=tags,
            )

        if sections_alert:
            self.stats_operational_alert_var.set(
                f"ALERTA backlog (>= {alert_threshold}): " + ", ".join(sections_alert)
            )
        elif sections_warning:
            self.stats_operational_alert_var.set(
                f"Atentie backlog (>= {warning_threshold}): " + ", ".join(sections_warning)
            )
        else:
            self.stats_operational_alert_var.set(
                f"Stare backlog decont final: nicio alerta (prag {alert_threshold})."
            )

        quick_rows = self.db.list_recent_audit(
            limit=5000,
            action="export_dashboard_watchlist_history_quick",
            date_from=f"{date_from} 00:00:00",
            date_to=f"{date_to} 23:59:59",
        )
        daily_perf: Dict[str, Dict[str, int]] = {}
        for row in quick_rows:
            day = str(row["created_at"] or "")[:10]
            if not day:
                continue
            bucket = daily_perf.setdefault(
                day,
                {
                    "exports": 0,
                    "duration_sum": 0,
                    "duration_max": 0,
                    "snapshot_runs": 0,
                    "trend_rows": 0,
                    "files": 0,
                },
            )
            details = self._parse_audit_kv_details(str(row["details"] or ""))
            try:
                duration_ms = int((details.get("duration_ms") or "0").strip() or 0)
            except Exception:
                duration_ms = 0
            try:
                snapshot_runs = int((details.get("snapshot_runs") or "0").strip() or 0)
            except Exception:
                snapshot_runs = 0
            try:
                trend_rows = int((details.get("trend_rows") or "0").strip() or 0)
            except Exception:
                trend_rows = 0
            try:
                files_count = int((details.get("files") or "0").strip() or 0)
            except Exception:
                files_count = 0

            bucket["exports"] += 1
            bucket["duration_sum"] += duration_ms
            bucket["duration_max"] = max(bucket["duration_max"], duration_ms)
            bucket["snapshot_runs"] += snapshot_runs
            bucket["trend_rows"] += trend_rows
            bucket["files"] += files_count

        self.stats_watchlist_export_perf_data = []
        total_exports = 0
        total_duration = 0
        total_trend_rows = 0
        for day in sorted(daily_perf.keys()):
            rec = dict(daily_perf[day])
            exports_count = max(1, int(rec["exports"]))
            avg_ms = int(round(int(rec["duration_sum"]) / exports_count))
            rec_out = {
                "day": day,
                "exports": int(rec["exports"]),
                "avg_ms": avg_ms,
                "max_ms": int(rec["duration_max"]),
                "snapshot_runs": int(rec["snapshot_runs"]),
                "trend_rows": int(rec["trend_rows"]),
                "files": int(rec["files"]),
            }
            self.stats_watchlist_export_perf_data.append(rec_out)
            total_exports += rec_out["exports"]
            total_duration += int(rec["duration_sum"])
            total_trend_rows += rec_out["trend_rows"]
            if hasattr(self, "stats_watchlist_export_tree"):
                self.stats_watchlist_export_tree.insert(
                    "",
                    END,
                    values=(
                        rec_out["day"],
                        rec_out["exports"],
                        rec_out["avg_ms"],
                        rec_out["max_ms"],
                        rec_out["snapshot_runs"],
                        rec_out["trend_rows"],
                        rec_out["files"],
                    ),
                )

        avg_total_ms = int(round(total_duration / total_exports)) if total_exports > 0 else 0
        if hasattr(self, "stats_watchlist_export_kpi_vars"):
            self.stats_watchlist_export_kpi_vars["exports"].set(f"Quick export-uri: {total_exports}")
            self.stats_watchlist_export_kpi_vars["avg_ms"].set(f"Durata medie (ms): {avg_total_ms}")
            self.stats_watchlist_export_kpi_vars["trend_rows"].set(f"Randuri trend procesate: {total_trend_rows}")

    @staticmethod
    def _parse_audit_kv_details(details: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        text = (details or "").strip()
        if not text:
            return out
        for chunk in re.split(r"[|;]", text):
            part = chunk.strip()
            if not part or "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = App._audit_decode_detail_value(value.strip())
            if key:
                out[key] = value
        return out

    def export_statistics_csv(self) -> None:
        if not self._require_role("Export statistici CSV", "admin", "medic", "receptie"):
            return
        if not self.stats_daily_data:
            self.refresh_statistics()
        if not self.stats_daily_data:
            messagebox.showinfo("Statistici", "Nu exista date de exportat.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(self.stats_filter_vars["department"].get().strip() or "toate_sectiile")
        daily_path = EXPORTS_DIR / f"statistici_daily_{base}_{stamp}.csv"
        weekly_path = EXPORTS_DIR / f"statistici_weekly_{base}_{stamp}.csv"

        with daily_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["day", "admissions", "discharges", "orders", "vitals"])
            for row in self.stats_daily_data:
                writer.writerow([row["day"], row["admissions"], row["discharges"], row["orders"], row["vitals"]])

        with weekly_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["week", "admissions", "discharges", "orders", "vitals"])
            for row in self.stats_weekly_data:
                writer.writerow([row["week"], row["admissions"], row["discharges"], row["orders"], row["vitals"]])

        self._audit(
            "export_statistics_csv",
            self._audit_details_from_pairs(
                ("daily", daily_path),
                ("weekly", weekly_path),
            ),
        )
        messagebox.showinfo("Statistici", f"Export finalizat:\n{daily_path}\n{weekly_path}")

    def export_watchlist_export_perf_csv(self, *, show_dialog: bool = True) -> Optional[Path]:
        if not self._require_role("Export perf watchlist CSV", "admin", "medic", "receptie"):
            return None
        if not self.stats_watchlist_export_perf_data:
            self.refresh_statistics()
        if not self.stats_watchlist_export_perf_data:
            messagebox.showinfo("Statistici performanta", "Nu exista date de exportat pentru performanta watchlist.")
            return None

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(self.stats_filter_vars["department"].get().strip() or "toate_sectiile")
        out_path = EXPORTS_DIR / f"statistici_watchlist_export_perf_{base}_{stamp}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["day", "exports", "avg_ms", "max_ms", "snapshot_runs", "trend_rows", "files"])
            for row in self.stats_watchlist_export_perf_data:
                writer.writerow(
                    [
                        row["day"],
                        row["exports"],
                        row["avg_ms"],
                        row["max_ms"],
                        row["snapshot_runs"],
                        row["trend_rows"],
                        row["files"],
                    ]
                )

        self._audit(
            "export_watchlist_export_perf_csv",
            self._audit_details_from_pairs(("file", out_path)),
        )
        if show_dialog:
            messagebox.showinfo("Statistici performanta", f"Export finalizat:\n{out_path}")
        return out_path

    def export_watchlist_export_perf_pdf(self, *, show_dialog: bool = True) -> Optional[Path]:
        if not self._require_role("Export perf watchlist PDF", "admin", "medic", "receptie"):
            return None
        if not self._ensure_pdf_backend():
            return None
        if not self.stats_watchlist_export_perf_data:
            self.refresh_statistics()
        if not self.stats_watchlist_export_perf_data:
            messagebox.showinfo("Statistici performanta", "Nu exista date de exportat pentru performanta watchlist.")
            return None

        date_from = self.stats_filter_vars["date_from"].get().strip()
        date_to = self.stats_filter_vars["date_to"].get().strip()
        department = self.stats_filter_vars["department"].get().strip()
        section_name = department or "Toate sectiile"

        total_exports = sum(int(row["exports"]) for row in self.stats_watchlist_export_perf_data)
        total_trend_rows = sum(int(row["trend_rows"]) for row in self.stats_watchlist_export_perf_data)
        total_snapshot_runs = sum(int(row["snapshot_runs"]) for row in self.stats_watchlist_export_perf_data)
        avg_ms = int(round(sum(int(row["avg_ms"]) * int(row["exports"]) for row in self.stats_watchlist_export_perf_data) / max(1, total_exports)))
        max_ms = max(int(row["max_ms"]) for row in self.stats_watchlist_export_perf_data)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(section_name)
        out_path = EXPORTS_DIR / f"statistici_watchlist_export_perf_{base}_{date_from}_{date_to}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Performanta export rapid watchlist")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Interval: {date_from} - {date_to} | Generat la: {now_ts()}")
        y -= 16

        totals_text = (
            f"Quick export-uri: {total_exports}\n"
            f"Durata medie (ms): {avg_ms}\n"
            f"Durata maxima (ms): {max_ms}\n"
            f"Snapshot runs procesate: {total_snapshot_runs}\n"
            f"Trend rows procesate: {total_trend_rows}"
        )
        y = self._pdf_draw_block(pdf, y, "KPI performanta", totals_text)

        lines = [
            f"{row['day']} | exporturi {row['exports']} | avg_ms {row['avg_ms']} | max_ms {row['max_ms']} | "
            f"snapshot_runs {row['snapshot_runs']} | trend_rows {row['trend_rows']} | fisiere {row['files']}"
            for row in self.stats_watchlist_export_perf_data
        ]
        y = self._pdf_draw_block(pdf, y, "Detaliu zilnic", "\n".join(lines) if lines else "-")

        signature = self._build_document_signature(
            "statistici_watchlist_export_perf",
            f"department={section_name}|date_from={date_from}|date_to={date_to}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_watchlist_export_perf_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        if show_dialog:
            messagebox.showinfo("Statistici performanta", f"Export PDF finalizat:\n{out_path}")
        return out_path

    def export_watchlist_export_perf_quick(self) -> None:
        if not self._require_role("Export perf watchlist rapid", "admin", "medic", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        started_at = datetime.now()
        csv_path = self.export_watchlist_export_perf_csv(show_dialog=False)
        pdf_path = self.export_watchlist_export_perf_pdf(show_dialog=False)
        if not csv_path and not pdf_path:
            return

        elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        self._audit(
            "export_watchlist_export_perf_quick",
            self._audit_details_from_pairs(
                ("csv", csv_path or "-"),
                ("pdf", pdf_path or "-"),
                ("duration_ms", elapsed_ms),
            ),
        )

        lines: List[str] = ["Export rapid performanta watchlist finalizat:"]
        if csv_path:
            lines.append(f"CSV: {csv_path}")
        if pdf_path:
            lines.append(f"PDF: {pdf_path}")
        lines.append(f"Durata: {elapsed_ms} ms")
        messagebox.showinfo("Export rapid", "\n".join(lines))

    def export_operational_statistics_csv(self) -> None:
        if not self._require_role("Export operational CSV", "admin", "medic", "receptie"):
            return
        if not self.stats_operational_data:
            self.refresh_statistics()
        if not self.stats_operational_data:
            messagebox.showinfo("Statistici operationale", "Nu exista date de exportat.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(self.stats_filter_vars["department"].get().strip() or "toate_sectiile")
        out_path = EXPORTS_DIR / f"statistici_operationale_{base}_{stamp}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["day", "scheduled_admissions", "scheduled_discharges", "discharged_without_final_decont"])
            for row in self.stats_operational_data:
                writer.writerow(
                    [
                        row["day"],
                        row["scheduled_admissions"],
                        row["scheduled_discharges"],
                        row["discharged_without_final_decont"],
                    ]
                )

        self._audit(
            "export_operational_statistics_csv",
            self._audit_details_from_pairs(("file", out_path)),
        )
        messagebox.showinfo("Statistici operationale", f"Export finalizat:\n{out_path}")

    def export_operational_statistics_pdf(self) -> None:
        if not self._require_role("Export operational PDF", "admin", "medic", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return
        if not self.stats_operational_data:
            self.refresh_statistics()
        if not self.stats_operational_data:
            messagebox.showinfo("Statistici operationale", "Nu exista date de exportat.")
            return

        date_from = self.stats_filter_vars["date_from"].get().strip()
        date_to = self.stats_filter_vars["date_to"].get().strip()
        department = self.stats_filter_vars["department"].get().strip()
        section_name = department or "Toate sectiile"
        total_scheduled_adm = sum(int(row["scheduled_admissions"]) for row in self.stats_operational_data)
        total_scheduled_dis = sum(int(row["scheduled_discharges"]) for row in self.stats_operational_data)
        total_no_final = sum(int(row["discharged_without_final_decont"]) for row in self.stats_operational_data)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(section_name)
        out_path = EXPORTS_DIR / f"statistici_operationale_{base}_{date_from}_{date_to}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Statistici operationale")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Interval: {date_from} - {date_to} | Generat la: {now_ts()}")
        y -= 16

        totals_text = (
            f"Internari programate: {total_scheduled_adm}\n"
            f"Externari programate: {total_scheduled_dis}\n"
            f"Externati fara decont final: {total_no_final}"
        )
        y = self._pdf_draw_block(pdf, y, "Totaluri", totals_text)

        lines = [
            f"{row['day']} | internari programate {row['scheduled_admissions']} | "
            f"externari programate {row['scheduled_discharges']} | "
            f"externati fara decont final {row['discharged_without_final_decont']}"
            for row in self.stats_operational_data
        ]
        y = self._pdf_draw_block(pdf, y, "Detaliu zilnic", "\n".join(lines) if lines else "-")

        signature = self._build_document_signature(
            "statistici_operationale",
            f"department={section_name}|date_from={date_from}|date_to={date_to}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_operational_statistics_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Statistici operationale", f"Export PDF finalizat:\n{out_path}")

    def export_operational_by_department_csv(self) -> None:
        if not self._require_role("Export operational pe sectii CSV", "admin", "medic", "receptie"):
            return
        if not self.stats_operational_by_department_data:
            self.refresh_statistics()
        if not self.stats_operational_by_department_data:
            messagebox.showinfo("Statistici pe sectii", "Nu exista date de exportat.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(self.stats_filter_vars["department"].get().strip() or "toate_sectiile")
        out_path = EXPORTS_DIR / f"statistici_operationale_pe_sectii_{base}_{stamp}.csv"
        alert_threshold = max(1, int(getattr(self, "operational_backlog_alert_threshold", 5)))
        warning_threshold = max(1, alert_threshold - 1)

        def _row_status(backlog_value: int) -> str:
            if backlog_value >= alert_threshold:
                return "ALERTA"
            if backlog_value >= warning_threshold:
                return "WARNING"
            return "OK"

        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "department",
                    "scheduled_admissions",
                    "scheduled_discharges",
                    "discharged_without_final_decont",
                    "total",
                    "backlog_status",
                    "backlog_threshold",
                ]
            )
            for row in self.stats_operational_by_department_data:
                backlog = int(row["discharged_without_final_decont"])
                writer.writerow(
                    [
                        row["department"],
                        row["scheduled_admissions"],
                        row["scheduled_discharges"],
                        backlog,
                        row["total"],
                        _row_status(backlog),
                        alert_threshold,
                    ]
                )

        self._audit(
            "export_operational_by_department_csv",
            self._audit_details_from_pairs(("file", out_path)),
        )
        messagebox.showinfo("Statistici pe sectii", f"Export finalizat:\n{out_path}")

    def export_operational_by_department_pdf(self) -> None:
        if not self._require_role("Export operational pe sectii PDF", "admin", "medic", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return
        if not self.stats_operational_by_department_data:
            self.refresh_statistics()
        if not self.stats_operational_by_department_data:
            messagebox.showinfo("Statistici pe sectii", "Nu exista date de exportat.")
            return

        date_from = self.stats_filter_vars["date_from"].get().strip()
        date_to = self.stats_filter_vars["date_to"].get().strip()
        department = self.stats_filter_vars["department"].get().strip()
        section_name = department or "Toate sectiile"
        alert_threshold = max(1, int(getattr(self, "operational_backlog_alert_threshold", 5)))
        warning_threshold = max(1, alert_threshold - 1)

        def _row_status(backlog_value: int) -> str:
            if backlog_value >= alert_threshold:
                return "ALERTA"
            if backlog_value >= warning_threshold:
                return "WARNING"
            return "OK"

        top_rows = sorted(
            self.stats_operational_by_department_data,
            key=lambda item: int(item["total"]),
            reverse=True,
        )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self._safe_filename(section_name)
        out_path = EXPORTS_DIR / f"statistici_operationale_pe_sectii_{base}_{date_from}_{date_to}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Operational comparativ pe sectii")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Filtru sectie: {section_name} | Interval: {date_from} - {date_to} | Generat la: {now_ts()}")
        y -= 16

        y = self._pdf_draw_block(pdf, y, "Prag alertare backlog", f"ALERTA >= {alert_threshold}, WARNING >= {warning_threshold}")

        lines = [
            f"{row['department']} | internari programate {row['scheduled_admissions']} | "
            f"externari programate {row['scheduled_discharges']} | "
            f"externati fara decont final {row['discharged_without_final_decont']} | total {row['total']} | "
            f"status {_row_status(int(row['discharged_without_final_decont']))}"
            for row in top_rows
        ]
        y = self._pdf_draw_block(pdf, y, "Clasament sectii", "\n".join(lines) if lines else "-")

        signature = self._build_document_signature(
            "statistici_operationale_pe_sectii",
            f"department={section_name}|date_from={date_from}|date_to={date_to}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_operational_by_department_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Statistici pe sectii", f"Export PDF finalizat:\n{out_path}")

    def _selected_user_id(self) -> Optional[int]:
        if not self._has_role("admin"):
            return None
        selected = self.users_tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except Exception:
            return None

    def refresh_users(self) -> None:
        if not self._has_role("admin"):
            return
        for iid in self.users_tree.get_children():
            self.users_tree.delete(iid)
        self.users_map.clear()
        rows = self.db.list_users()
        for row in rows:
            iid = str(row["id"])
            self.users_map[iid] = dict(row)
            self.users_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["username"],
                    row["display_name"],
                    row["role"],
                    "DA" if row["active"] else "NU",
                    row["created_at"],
                ),
            )

    def on_user_select(self, _event: Any = None) -> None:
        user_id = self._selected_user_id()
        if not user_id:
            return
        row = self.users_map.get(str(user_id))
        if not row:
            return
        self.user_form_vars["username"].set(row["username"])
        self.user_form_vars["display_name"].set(row["display_name"])
        self.user_form_vars["role"].set(normalize_role(row["role"]))
        self.user_active_var.set(bool(row["active"]))

    def create_user_action(self) -> None:
        if not self._require_role("Creeaza utilizator", "admin"):
            return
        username = self.user_form_vars["username"].get().strip()
        display_name = self.user_form_vars["display_name"].get().strip()
        role = self.user_form_vars["role"].get().strip()
        password = self.user_form_vars["password"].get()
        if not username:
            messagebox.showerror("Eroare", "Username obligatoriu.")
            return
        if not password:
            messagebox.showerror("Eroare", "Parola obligatorie.")
            return
        try:
            new_id = self.db.create_user(
                username=username,
                password=password,
                role=role,
                display_name=display_name,
                active=self.user_active_var.get(),
            )
        except sqlite3.IntegrityError:
            messagebox.showerror("Eroare", "Username deja existent.")
            return
        except ValueError as exc:
            messagebox.showerror("Eroare", str(exc))
            return

        self._audit("create_user", self._audit_details_from_pairs(("user_id", new_id)))
        self.user_form_vars["password"].set("")
        self.refresh_users()
        messagebox.showinfo("Succes", "Utilizator creat.")

    def update_user_action(self) -> None:
        if not self._require_role("Actualizeaza utilizator", "admin"):
            return
        user_id = self._selected_user_id()
        if not user_id:
            messagebox.showwarning("Neselectat", "Selecteaza un utilizator.")
            return
        role = self.user_form_vars["role"].get().strip()
        display_name = self.user_form_vars["display_name"].get().strip()
        active = self.user_active_var.get()
        self.db.update_user(user_id=user_id, role=role, display_name=display_name, active=active)
        self._audit(
            "update_user",
            self._audit_details_from_pairs(
                ("user_id", user_id),
                ("role", role),
                ("active", active),
            ),
        )
        self.refresh_users()
        messagebox.showinfo("Succes", "Utilizator actualizat.")

    def reset_user_password_action(self) -> None:
        if not self._require_role("Reset parola utilizator", "admin"):
            return
        user_id = self._selected_user_id()
        if not user_id:
            messagebox.showwarning("Neselectat", "Selecteaza un utilizator.")
            return
        new_password = self.user_form_vars["password"].get()
        if not new_password:
            messagebox.showerror("Eroare", "Introduce parola noua in campul de parola.")
            return
        try:
            self.db.set_user_password(user_id=user_id, new_password=new_password)
        except ValueError as exc:
            messagebox.showerror("Eroare", str(exc))
            return
        self._audit("reset_user_password", self._audit_details_from_pairs(("user_id", user_id)))
        self.user_form_vars["password"].set("")
        messagebox.showinfo("Succes", "Parola a fost resetata.")

    def change_my_password(self) -> None:
        old_pwd = simpledialog.askstring("Schimba parola", "Parola curenta:", show="*", parent=self.root)
        if old_pwd is None:
            return
        if not old_pwd:
            messagebox.showerror("Eroare", "Parola curenta este obligatorie.")
            return
        auth = self.db.authenticate_user(self.current_user.get("username", ""), old_pwd)
        if not auth:
            messagebox.showerror("Eroare", "Parola curenta este incorecta.")
            return
        new_pwd = simpledialog.askstring("Schimba parola", "Parola noua (minim 6):", show="*", parent=self.root)
        if new_pwd is None:
            return
        confirm_pwd = simpledialog.askstring("Schimba parola", "Confirma parola noua:", show="*", parent=self.root)
        if confirm_pwd is None:
            return
        if new_pwd != confirm_pwd:
            messagebox.showerror("Eroare", "Parolele nu coincid.")
            return
        try:
            self.db.set_user_password(int(self.current_user["id"]), new_pwd)
        except ValueError as exc:
            messagebox.showerror("Eroare", str(exc))
            return
        self._audit(
            "change_own_password",
            self._audit_details_from_pairs(("user", self.current_user.get("username") or "-")),
        )
        messagebox.showinfo("Succes", "Parola a fost schimbata.")

    def _build_patient_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.patient_vars = {
            "first_name": tk.StringVar(),
            "last_name": tk.StringVar(),
            "cnp": tk.StringVar(),
            "phone": tk.StringVar(),
            "email": tk.StringVar(),
            "birth_date": tk.StringVar(),
            "address": tk.StringVar(),
            "gender": tk.StringVar(),
            "occupation": tk.StringVar(),
            "insurance_provider": tk.StringVar(),
            "insurance_id": tk.StringVar(),
            "emergency_contact_name": tk.StringVar(),
            "emergency_contact_phone": tk.StringVar(),
            "blood_type": tk.StringVar(),
            "height_cm": tk.StringVar(),
            "weight_kg": tk.StringVar(),
        }

        entry_fields = [
            ("Prenume", "first_name"),
            ("Nume", "last_name"),
            ("CNP", "cnp"),
            ("Telefon", "phone"),
            ("Email", "email"),
            ("Data nasterii (YYYY-MM-DD)", "birth_date"),
            ("Adresa", "address"),
            ("Sex", "gender"),
            ("Ocupatie", "occupation"),
            ("Asigurator", "insurance_provider"),
            ("Nr. asigurare", "insurance_id"),
            ("Contact urgenta (nume)", "emergency_contact_name"),
            ("Contact urgenta (tel)", "emergency_contact_phone"),
            ("Grupa sanguina", "blood_type"),
            ("Inaltime (cm)", "height_cm"),
            ("Greutate (kg)", "weight_kg"),
        ]

        for idx, (label, key) in enumerate(entry_fields):
            row = idx // 2
            col_base = (idx % 2) * 2
            ttk.Label(frame, text=label).grid(row=row, column=col_base, sticky="w", pady=2, padx=(0, 6))
            ttk.Entry(frame, textvariable=self.patient_vars[key], width=70).grid(
                row=row, column=col_base + 1, sticky="ew", pady=2, padx=(0, 10)
            )

        self.patient_text_widgets: Dict[str, ScrolledText] = {}
        text_fields = [
            ("Istoric medical", "medical_history", 4),
            ("Alergii", "allergies", 3),
            ("Afectiuni cronice", "chronic_conditions", 3),
            ("Tratament curent", "current_medication", 3),
            ("Interventii/chirurgii", "surgeries", 3),
            ("Antecedente familiale", "family_history", 3),
            ("Stil de viata", "lifestyle_notes", 3),
        ]

        base_row = (len(entry_fields) + 1) // 2
        for offset, (label, key, height) in enumerate(text_fields):
            r = base_row + offset
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky="nw", pady=2)
            txt = ScrolledText(frame, height=height, wrap="word")
            txt.grid(row=r, column=1, columnspan=3, sticky="nsew", pady=2, padx=(0, 10))
            self.patient_text_widgets[key] = txt

        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(3, weight=1)
        for idx in range(len(text_fields)):
            frame.grid_rowconfigure(base_row + idx, weight=1)

        actions = ttk.Frame(frame)
        actions.grid(row=base_row + len(text_fields), column=3, sticky="e", pady=(8, 0))
        ttk.Button(actions, text="Salveaza pacient", command=self.save_patient).pack(side=LEFT)
        ttk.Button(actions, text="Export fisa PDF", command=lambda: self.request_export_action("patient_sheet_pdf", self.export_patient_sheet_pdf)).pack(side=LEFT, padx=6)

    def _build_visits_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.visit_vars = {
            "visit_date": tk.StringVar(value=datetime.now().strftime("%Y-%m-%d")),
            "reason": tk.StringVar(),
            "diagnosis": tk.StringVar(),
            "treatment": tk.StringVar(),
        }

        form = ttk.LabelFrame(frame, text="Adauga consultatie")
        form.pack(fill="x")

        ttk.Label(form, text="Data").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.visit_vars["visit_date"], width=18).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )
        ttk.Label(form, text="Motiv").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.visit_vars["reason"], width=28).grid(
            row=0, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(form, text="Diagnostic").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.visit_vars["diagnosis"], width=28).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(form, text="Tratament").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.visit_vars["treatment"], width=28).grid(
            row=1, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(form, text="Note").grid(row=2, column=0, sticky="nw", padx=6, pady=4)
        self.visit_notes = ScrolledText(form, height=4, wrap="word")
        self.visit_notes.grid(row=2, column=1, columnspan=3, sticky="ew", padx=6, pady=4)
        ttk.Button(form, text="Adauga", command=self.add_visit).grid(row=3, column=3, sticky="e", padx=6, pady=6)

        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)

        list_wrap = ttk.LabelFrame(frame, text="Istoric consultatii")
        list_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))

        cols = ("date", "reason", "diagnosis", "treatment", "notes")
        self.visit_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=11)
        self.visit_tree.heading("date", text="Data")
        self.visit_tree.heading("reason", text="Motiv")
        self.visit_tree.heading("diagnosis", text="Diagnostic")
        self.visit_tree.heading("treatment", text="Tratament")
        self.visit_tree.heading("notes", text="Preview note")
        self.visit_tree.column("date", width=90, anchor="w")
        self.visit_tree.column("reason", width=180, anchor="w")
        self.visit_tree.column("diagnosis", width=180, anchor="w")
        self.visit_tree.column("treatment", width=180, anchor="w")
        self.visit_tree.column("notes", width=300, anchor="w")
        self.visit_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.visit_tree.bind("<<TreeviewSelect>>", self.on_visit_select)

        details_wrap = ttk.Frame(list_wrap)
        details_wrap.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        ttk.Label(details_wrap, text="Detalii consultatie selectata").pack(anchor="w")
        self.visit_details = ScrolledText(details_wrap, height=6, wrap="word", state="disabled")
        self.visit_details.pack(fill=BOTH, expand=True)

        bottom = ttk.Frame(list_wrap)
        bottom.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(bottom, text="Sterge consultatia selectata", command=self.delete_selected_visit).pack(side=LEFT)

    def _build_admissions_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.active_admission_var = tk.StringVar(value="Fara internare activa.")
        ttk.Label(frame, textvariable=self.active_admission_var, foreground="#0f766e").pack(anchor="w", pady=(0, 8))
        self.case_finalization_var = tk.StringVar(value="Finalizare caz: -")
        ttk.Label(frame, textvariable=self.case_finalization_var, foreground="#1d4ed8").pack(anchor="w", pady=(0, 8))
        self.discharge_rules_var = tk.StringVar(value="Reguli externare: -")
        self.discharge_rules_label = ttk.Label(frame, textvariable=self.discharge_rules_var, foreground="#7c2d12")
        self.discharge_rules_label.pack(anchor="w", pady=(0, 8))

        form = ttk.LabelFrame(frame, text="Internare noua")
        form.pack(fill="x")

        self.admission_vars = {
            "admitted_at": tk.StringVar(value=now_ts()),
            "admission_type": tk.StringVar(value="inpatient"),
            "triage_level": tk.StringVar(value="3"),
            "department": tk.StringVar(),
            "ward": tk.StringVar(),
            "bed": tk.StringVar(),
            "attending_clinician": tk.StringVar(),
            "chief_complaint": tk.StringVar(),
        }

        ttk.Label(form, text="Admis la").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["admitted_at"], width=20).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )
        ttk.Label(form, text="Tip").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.admission_vars["admission_type"],
            state="readonly",
            values=("inpatient", "outpatient", "ER", "daycare"),
            width=14,
        ).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Triage (1-5)").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.admission_vars["triage_level"],
            state="readonly",
            values=("1", "2", "3", "4", "5"),
            width=8,
        ).grid(row=0, column=5, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Sectie").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["department"]).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(form, text="Salon").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["ward"]).grid(row=1, column=3, sticky="ew", padx=6, pady=4)
        ttk.Label(form, text="Pat").grid(row=1, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["bed"], width=10).grid(row=1, column=5, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Medic curant").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["attending_clinician"]).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=4
        )
        ttk.Label(form, text="Motiv prezentare").grid(row=2, column=3, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.admission_vars["chief_complaint"]).grid(
            row=2, column=4, columnspan=2, sticky="ew", padx=6, pady=4
        )

        for idx in (1, 3, 5):
            form.grid_columnconfigure(idx, weight=1 if idx % 2 == 1 else 0)

        actions = ttk.Frame(form)
        actions.grid(row=3, column=0, columnspan=6, sticky="e", padx=6, pady=(4, 6))
        ttk.Button(actions, text="Creeaza internare", command=self.create_admission).pack(side=LEFT)
        ttk.Button(actions, text="Reincarca", command=self.refresh_admissions).pack(side=LEFT, padx=6)

        list_wrap = ttk.LabelFrame(frame, text="Istoric internari")
        list_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))
        cols = ("mrn", "type", "triage", "dept", "ward", "bed", "status", "admitted", "discharged")
        self.admission_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=8)
        self.admission_tree.heading("mrn", text="MRN")
        self.admission_tree.heading("type", text="Tip")
        self.admission_tree.heading("triage", text="Triage")
        self.admission_tree.heading("dept", text="Sectie")
        self.admission_tree.heading("ward", text="Salon")
        self.admission_tree.heading("bed", text="Pat")
        self.admission_tree.heading("status", text="Status")
        self.admission_tree.heading("admitted", text="Admis la")
        self.admission_tree.heading("discharged", text="Externat la")
        self.admission_tree.column("mrn", width=120, anchor="w")
        self.admission_tree.column("type", width=90, anchor="w")
        self.admission_tree.column("triage", width=60, anchor="center")
        self.admission_tree.column("dept", width=120, anchor="w")
        self.admission_tree.column("ward", width=80, anchor="w")
        self.admission_tree.column("bed", width=60, anchor="w")
        self.admission_tree.column("status", width=90, anchor="w")
        self.admission_tree.column("admitted", width=145, anchor="w")
        self.admission_tree.column("discharged", width=145, anchor="w")
        self.admission_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)
        self.admission_tree.bind("<<TreeviewSelect>>", self.on_admission_select)

        discharge = ttk.Frame(list_wrap)
        discharge.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))
        ttk.Label(discharge, text="Rezumat externare (pentru internarea selectata)").pack(anchor="w")
        self.discharge_summary_box = ScrolledText(discharge, height=4, wrap="word")
        self.discharge_summary_box.pack(fill=BOTH, expand=True, pady=(4, 4))

        diagnosis_wrap = ttk.LabelFrame(discharge, text="Diagnostice FO (tipizate)")
        diagnosis_wrap.pack(fill="x", pady=(4, 6))
        self.admission_diag_vars = {
            "referral_diagnosis": tk.StringVar(),
            "admission_diagnosis": tk.StringVar(),
            "discharge_diagnosis": tk.StringVar(),
            "secondary_diagnoses": tk.StringVar(),
            "dietary_regimen": tk.StringVar(),
            "admission_criteria": tk.StringVar(),
            "discharge_criteria": tk.StringVar(),
        }
        ttk.Label(diagnosis_wrap, text="Diagnostic trimitere").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["referral_diagnosis"]).grid(
            row=0, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Diagnostic internare").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["admission_diagnosis"]).grid(
            row=0, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Diagnostic externare").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["discharge_diagnosis"]).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Diagnostice secundare").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["secondary_diagnoses"]).grid(
            row=1, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Regim alimentar").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["dietary_regimen"]).grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Criterii internare").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["admission_criteria"]).grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(diagnosis_wrap, text="Criterii externare").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(diagnosis_wrap, textvariable=self.admission_diag_vars["discharge_criteria"]).grid(
            row=4, column=1, columnspan=3, sticky="ew", padx=6, pady=4
        )
        diagnosis_wrap.grid_columnconfigure(1, weight=1)
        diagnosis_wrap.grid_columnconfigure(3, weight=1)

        diagnosis_actions = ttk.Frame(diagnosis_wrap)
        diagnosis_actions.grid(row=5, column=0, columnspan=4, sticky="e", padx=6, pady=(2, 6))
        ttk.Button(diagnosis_actions, text="Salveaza diagnostice", command=self.save_selected_admission_diagnoses).pack(side=RIGHT)

        discharge_actions = ttk.Frame(discharge)
        self.discharge_actions = discharge_actions
        self.handoff_compact_mode = bool(getattr(self, "handoff_compact_mode_default", False))
        self.handoff_managed_labels = {
            "Pachet FO PDF",
            "Pachet FO + checklist TXT",
            "Pachet FO ZIP",
            "Regenereaza + deschide pachet FO complet",
            "Copiaza sumar pachet FO",
            "Copiaza sumar + draft e-mail",
            "Copiere sumar scurt FO",
            "Copiere sumar scurt FO + cai",
            "Copiere sumar scurt FO + cai + PS",
            "Regenerare silent + sumar FO + cai + PS",
            "Handoff minim",
            "Handoff minim + deschide ZIP",
            "Handoff minim + ZIP + e-mail",
            "Handoff minim + ZIP + e-mail + checklist",
            "Handoff minim all-in",
            "Reseteaza blocul Handoff FO",
            "Deschide ultimul FO ZIP",
            "Deschide ultimul checklist FO",
            "Deschide ultimele 3 artefacte FO",
            "Deschide toate artefactele FO",
            "Deschide folder exporturi",
            "Ultimele artefacte FO",
            "Copiaza cai artefacte FO",
            "Status Handoff FO",
            "Status Handoff FO (minim)",
            "Status Handoff FO (all-in)",
            "Copiaza status Handoff FO",
            "Copiaza status Handoff JSON",
            "Export status Handoff JSON",
            "Export JSON (minim)",
            "Export JSON (all-in)",
            "Copiaza status JSON (minim)",
            "Copiaza status JSON (all-in)",
            "Copiaza status (minim)",
            "Copiaza status (all-in)",
            "Status + Copiaza Handoff FO",
            "Status + Copiaza Handoff JSON",
            "Status + Copiaza JSON (minim)",
            "Status + Copiaza JSON (all-in)",
            "Status + Copy (minim)",
            "Status + Copy (all-in)",
        }
        self.handoff_compact_keep_enabled = {
            "Handoff minim",
            "Handoff minim + deschide ZIP",
            "Handoff minim all-in",
            "Reseteaza blocul Handoff FO",
            "Status Handoff FO",
            "Copiaza status Handoff FO",
            "Copiaza status Handoff JSON",
            "Export status Handoff JSON",
            "Export JSON (minim)",
            "Export JSON (all-in)",
            "Copiaza status JSON (minim)",
            "Copiaza status JSON (all-in)",
            "Copiaza status (minim)",
            "Copiaza status (all-in)",
            "Status + Copiaza Handoff FO",
            "Status + Copiaza Handoff JSON",
            "Status + Copiaza JSON (minim)",
            "Status + Copiaza JSON (all-in)",
            "Status + Copy (minim)",
            "Status + Copy (all-in)",
        }
        discharge_actions.pack(fill="x")
        self.handoff_compact_toggle_btn = ttk.Button(
            discharge_actions,
            text="Handoff compact: OFF",
            command=self.toggle_handoff_compact_mode,
        )
        self.handoff_compact_toggle_btn.pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Export internare PDF",
            command=lambda: self.request_export_action("admission_pdf", self.export_selected_admission_pdf),
        ).pack(side=LEFT)
        ttk.Button(
            discharge_actions,
            text="Bilet externare PDF",
            command=lambda: self.request_export_action("discharge_ticket_pdf", self.export_selected_discharge_ticket_pdf),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Pachet FO PDF",
            command=lambda: self.request_export_action("fo_package_pdf", self.export_selected_fo_package_pdf),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Pachet FO + checklist TXT",
            command=lambda: self.request_export_action("fo_package_with_checklist", self.export_selected_fo_package_with_checklist),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Pachet FO ZIP",
            command=lambda: self.request_export_action("fo_package_zip", self.export_selected_fo_package_zip),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Regenereaza + deschide pachet FO complet",
            command=lambda: self.request_export_action("fo_package_regen_open", self.regenerate_and_open_fo_full_package),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza sumar pachet FO",
            command=lambda: self.request_export_action("fo_package_copy_summary", self.copy_fo_package_summary_to_clipboard),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza sumar + draft e-mail",
            command=lambda: self.request_export_action("fo_package_copy_summary_email", self.copy_fo_package_summary_and_open_email_draft),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiere sumar scurt FO",
            command=lambda: self.request_export_action("fo_package_copy_short_summary", self.copy_fo_short_summary_to_clipboard),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiere sumar scurt FO + cai",
            command=lambda: self.request_export_action("fo_package_copy_short_summary_paths", self.copy_fo_short_summary_with_paths_to_clipboard),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiere sumar scurt FO + cai + PS",
            command=lambda: self.request_export_action("fo_package_copy_short_summary_paths_ps", self.copy_fo_short_summary_with_paths_and_ps_to_clipboard),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Regenerare silent + sumar FO + cai + PS",
            command=lambda: self.request_export_action("fo_package_regen_silent_copy_short_paths_ps", self.regenerate_silent_and_copy_fo_short_summary_with_paths_and_ps),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Handoff minim",
            command=lambda: self.request_export_action("fo_package_handoff_minimal", self.regenerate_silent_and_copy_fo_minimal_handoff),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Handoff minim + deschide ZIP",
            command=lambda: self.request_export_action("fo_package_handoff_minimal_open_zip", self.regenerate_silent_copy_fo_minimal_handoff_and_open_zip),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Handoff minim + ZIP + e-mail",
            command=lambda: self.request_export_action("fo_package_handoff_minimal_open_zip_email", self.regenerate_silent_copy_fo_minimal_handoff_open_zip_and_email),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Handoff minim + ZIP + e-mail + checklist",
            command=lambda: self.request_export_action("fo_package_handoff_minimal_open_zip_email_checklist", self.regenerate_silent_copy_fo_minimal_handoff_open_zip_email_and_checklist),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Handoff minim all-in",
            command=lambda: self.request_export_action("fo_package_handoff_minimal_all_in", self.regenerate_silent_copy_fo_minimal_all_in),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Reseteaza blocul Handoff FO",
            command=lambda: self.request_export_action("fo_handoff_reset", self.reset_fo_handoff_block),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status Handoff FO",
            command=self.show_handoff_status_popup,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status Handoff FO (minim)",
            command=lambda: self.show_handoff_status_popup("minimal"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status Handoff FO (all-in)",
            command=lambda: self.show_handoff_status_popup("all_in"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status Handoff FO",
            command=self.copy_handoff_status_to_clipboard,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status Handoff JSON",
            command=self.copy_handoff_status_as_json,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Export status Handoff JSON",
            command=lambda: self.request_export_action("fo_handoff_status_json_file", self.export_handoff_status_json_file),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Export JSON (minim)",
            command=lambda: self.request_export_action("fo_handoff_status_json_file_minimal", lambda: self.export_handoff_status_json_file("minimal")),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Export JSON (all-in)",
            command=lambda: self.request_export_action("fo_handoff_status_json_file_all_in", lambda: self.export_handoff_status_json_file("all_in")),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status JSON (minim)",
            command=lambda: self.copy_handoff_status_as_json("minimal"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status JSON (all-in)",
            command=lambda: self.copy_handoff_status_as_json("all_in"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status (minim)",
            command=lambda: self.copy_handoff_status_to_clipboard("minimal"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza status (all-in)",
            command=lambda: self.copy_handoff_status_to_clipboard("all_in"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copiaza Handoff FO",
            command=self.show_and_copy_handoff_status,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copiaza Handoff JSON",
            command=self.show_and_copy_handoff_status_json,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copiaza JSON (minim)",
            command=lambda: self.show_and_copy_handoff_status_json("minimal"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copiaza JSON (all-in)",
            command=lambda: self.show_and_copy_handoff_status_json("all_in"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copy (minim)",
            command=lambda: self.show_and_copy_handoff_status("minimal"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Status + Copy (all-in)",
            command=lambda: self.show_and_copy_handoff_status("all_in"),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Deschide ultimul FO ZIP",
            command=lambda: self.request_export_action("open_latest_fo_zip", self.open_latest_fo_zip),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Deschide ultimul checklist FO",
            command=lambda: self.request_export_action("open_latest_fo_checklist", self.open_latest_fo_checklist),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Deschide ultimele 3 artefacte FO",
            command=lambda: self.request_export_action("open_latest_fo_triplet", self.open_latest_fo_triplet),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Deschide toate artefactele FO",
            command=lambda: self.request_export_action("open_latest_fo_all", self.open_latest_fo_all_artifacts),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Deschide folder exporturi",
            command=lambda: self.request_export_action("open_exports_folder", self.open_exports_folder),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Ultimele artefacte FO",
            command=lambda: self.request_export_action("fo_latest_artifacts", self.show_latest_fo_artifacts),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Copiaza cai artefacte FO",
            command=lambda: self.request_export_action("fo_latest_artifacts_copy_paths", self.copy_latest_fo_artifacts_paths),
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Checklist raportare",
            command=self.show_selected_admission_reporting_checklist,
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Externeaza internarea selectata",
            command=self.discharge_selected_admission,
        ).pack(side=RIGHT)
        ttk.Button(
            discharge_actions,
            text="Valideaza caz",
            command=self.validate_selected_admission_case,
        ).pack(side=RIGHT, padx=6)
        ttk.Button(
            discharge_actions,
            text="Finalizeaza caz",
            command=self.finalize_selected_admission_case,
        ).pack(side=RIGHT, padx=6)
        self._apply_handoff_compact_mode()

        billing_wrap = ttk.LabelFrame(frame, text="Decont internare (partial/final)")
        billing_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))

        self.billing_type_var = tk.StringVar(value="partial")
        self.billing_amount_var = tk.StringVar(value="0")
        self.billing_issued_at_var = tk.StringVar(value=now_ts())
        ttk.Label(billing_wrap, text="Tip decont").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            billing_wrap,
            textvariable=self.billing_type_var,
            state="readonly",
            values=("partial", "final"),
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(billing_wrap, text="Valoare (RON)").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(billing_wrap, textvariable=self.billing_amount_var, width=12).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(billing_wrap, text="Data emitere").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(billing_wrap, textvariable=self.billing_issued_at_var, width=20).grid(row=0, column=5, sticky="w", padx=6, pady=4)

        ttk.Label(billing_wrap, text="Note decont").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        self.billing_notes_box = ScrolledText(billing_wrap, height=3, wrap="word")
        self.billing_notes_box.grid(row=1, column=1, columnspan=5, sticky="ew", padx=6, pady=4)
        billing_wrap.grid_columnconfigure(5, weight=1)

        billing_actions = ttk.Frame(billing_wrap)
        billing_actions.grid(row=2, column=0, columnspan=6, sticky="e", padx=6, pady=(2, 6))
        ttk.Button(billing_actions, text="Emite decont", command=self.issue_billing_record).pack(side=LEFT)
        ttk.Button(billing_actions, text="Reincarca deconturi", command=self.refresh_billing_records).pack(side=LEFT, padx=6)

        billing_cols = ("issued", "type", "amount", "currency", "status", "notes")
        self.billing_tree = ttk.Treeview(billing_wrap, columns=billing_cols, show="headings", height=5)
        self.billing_tree.heading("issued", text="Emis la")
        self.billing_tree.heading("type", text="Tip")
        self.billing_tree.heading("amount", text="Valoare")
        self.billing_tree.heading("currency", text="Moneda")
        self.billing_tree.heading("status", text="Status")
        self.billing_tree.heading("notes", text="Note")
        self.billing_tree.column("issued", width=145, anchor="w")
        self.billing_tree.column("type", width=80, anchor="w")
        self.billing_tree.column("amount", width=90, anchor="e")
        self.billing_tree.column("currency", width=70, anchor="center")
        self.billing_tree.column("status", width=90, anchor="w")
        self.billing_tree.column("notes", width=420, anchor="w")
        self.billing_tree.grid(row=3, column=0, columnspan=6, sticky="nsew", padx=6, pady=(0, 6))
        billing_wrap.grid_rowconfigure(3, weight=1)

        booking_wrap = ttk.LabelFrame(frame, text="Programari (internare / operatie / externare)")
        booking_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))

        self.booking_vars = {
            "booking_type": tk.StringVar(value="admission"),
            "starts_at": tk.StringVar(value=now_ts()),
            "ends_at": tk.StringVar(value=(datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")),
            "department": tk.StringVar(),
            "ward": tk.StringVar(),
            "bed": tk.StringVar(),
            "operating_room": tk.StringVar(),
            "attending_clinician": tk.StringVar(),
        }

        ttk.Label(booking_wrap, text="Tip").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            booking_wrap,
            textvariable=self.booking_vars["booking_type"],
            state="readonly",
            values=("admission", "operation", "discharge"),
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(booking_wrap, text="Start").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["starts_at"], width=20).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(booking_wrap, text="End").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["ends_at"], width=20).grid(row=0, column=5, sticky="w", padx=6, pady=4)

        ttk.Label(booking_wrap, text="Sectie").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["department"]).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(booking_wrap, text="Salon").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["ward"]).grid(row=1, column=3, sticky="ew", padx=6, pady=4)
        ttk.Label(booking_wrap, text="Pat").grid(row=1, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["bed"]).grid(row=1, column=5, sticky="w", padx=6, pady=4)

        ttk.Label(booking_wrap, text="Sala operatie").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["operating_room"]).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(booking_wrap, text="Medic").grid(row=2, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(booking_wrap, textvariable=self.booking_vars["attending_clinician"]).grid(row=2, column=3, columnspan=3, sticky="ew", padx=6, pady=4)

        ttk.Label(booking_wrap, text="Note").grid(row=3, column=0, sticky="nw", padx=6, pady=4)
        self.booking_notes_box = ScrolledText(booking_wrap, height=3, wrap="word")
        self.booking_notes_box.grid(row=3, column=1, columnspan=5, sticky="ew", padx=6, pady=4)

        self.booking_operation_preview_var = tk.StringVar(
            value="Previzualizare operatie: completeaza tip=operation + interval + sala/medic."
        )
        self.booking_operation_preview_label = ttk.Label(
            booking_wrap,
            textvariable=self.booking_operation_preview_var,
            foreground="#475569",
            wraplength=960,
        )
        self.booking_operation_preview_label.grid(row=4, column=0, columnspan=6, sticky="w", padx=6, pady=(0, 4))

        for idx in (1, 3, 5):
            booking_wrap.grid_columnconfigure(idx, weight=1)

        booking_actions = ttk.Frame(booking_wrap)
        booking_actions.grid(row=5, column=0, columnspan=6, sticky="e", padx=6, pady=(2, 6))
        self.booking_show_conflicts_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            booking_actions,
            text="Doar conflicte operatie",
            variable=self.booking_show_conflicts_only_var,
            command=self.refresh_bookings,
        ).pack(side=LEFT, padx=(0, 10))
        ttk.Button(booking_actions, text="Adauga programare", command=self.create_care_booking).pack(side=LEFT)
        ttk.Button(booking_actions, text="Marcheaza finalizata", command=self.complete_selected_booking).pack(side=LEFT, padx=6)
        ttk.Button(booking_actions, text="Anuleaza programare", command=self.cancel_selected_booking).pack(side=LEFT, padx=6)
        ttk.Button(booking_actions, text="Reincarca", command=self.refresh_bookings).pack(side=LEFT, padx=6)

        booking_cols = ("type", "start", "end", "dept", "ward", "bed", "oroom", "clinician", "status")
        self.booking_tree = ttk.Treeview(booking_wrap, columns=booking_cols, show="headings", height=6)
        self.booking_tree.heading("type", text="Tip")
        self.booking_tree.heading("start", text="Start")
        self.booking_tree.heading("end", text="End")
        self.booking_tree.heading("dept", text="Sectie")
        self.booking_tree.heading("ward", text="Salon")
        self.booking_tree.heading("bed", text="Pat")
        self.booking_tree.heading("oroom", text="Sala")
        self.booking_tree.heading("clinician", text="Medic")
        self.booking_tree.heading("status", text="Status")
        self.booking_tree.column("type", width=80, anchor="w")
        self.booking_tree.column("start", width=140, anchor="w")
        self.booking_tree.column("end", width=140, anchor="w")
        self.booking_tree.column("dept", width=100, anchor="w")
        self.booking_tree.column("ward", width=90, anchor="w")
        self.booking_tree.column("bed", width=60, anchor="w")
        self.booking_tree.column("oroom", width=80, anchor="w")
        self.booking_tree.column("clinician", width=140, anchor="w")
        self.booking_tree.column("status", width=90, anchor="w")
        self.booking_tree.tag_configure("operation_conflict", foreground="#b91c1c")
        self.booking_tree.grid(row=6, column=0, columnspan=6, sticky="nsew", padx=6, pady=(0, 6))
        booking_wrap.grid_rowconfigure(6, weight=1)

        for key in ("booking_type", "starts_at", "ends_at", "operating_room", "attending_clinician"):
            self.booking_vars[key].trace_add("write", lambda *_args: self._refresh_booking_operation_preview())
        self._refresh_booking_operation_preview()

        transfer_wrap = ttk.LabelFrame(frame, text="Transferuri internare (sectie/salon/pat)")
        transfer_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))

        self.transfer_vars = {
            "transferred_at": tk.StringVar(value=now_ts()),
            "to_department": tk.StringVar(),
            "to_ward": tk.StringVar(),
            "to_bed": tk.StringVar(),
        }

        ttk.Label(transfer_wrap, text="Moment transfer").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(transfer_wrap, textvariable=self.transfer_vars["transferred_at"], width=20).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )
        ttk.Label(transfer_wrap, text="Sectie tinta").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(transfer_wrap, textvariable=self.transfer_vars["to_department"]).grid(
            row=0, column=3, sticky="ew", padx=6, pady=4
        )
        ttk.Label(transfer_wrap, text="Salon tinta").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(transfer_wrap, textvariable=self.transfer_vars["to_ward"]).grid(row=0, column=5, sticky="ew", padx=6, pady=4)
        ttk.Label(transfer_wrap, text="Pat tinta").grid(row=0, column=6, sticky="w", padx=6, pady=4)
        ttk.Entry(transfer_wrap, textvariable=self.transfer_vars["to_bed"], width=10).grid(row=0, column=7, sticky="w", padx=6, pady=4)

        ttk.Label(transfer_wrap, text="Note transfer").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        self.transfer_notes_box = ScrolledText(transfer_wrap, height=3, wrap="word")
        self.transfer_notes_box.grid(row=1, column=1, columnspan=7, sticky="ew", padx=6, pady=4)
        for idx in (1, 3, 5, 7):
            transfer_wrap.grid_columnconfigure(idx, weight=1)

        transfer_actions = ttk.Frame(transfer_wrap)
        transfer_actions.grid(row=2, column=0, columnspan=8, sticky="e", padx=6, pady=(2, 6))
        ttk.Button(transfer_actions, text="Inregistreaza transfer", command=self.add_transfer_for_selected_admission).pack(
            side=LEFT
        )
        ttk.Button(transfer_actions, text="Reincarca transferuri", command=self.refresh_transfers).pack(side=LEFT, padx=6)

        transfer_cols = ("moment", "tip", "de_la", "la", "note")
        self.transfer_tree = ttk.Treeview(transfer_wrap, columns=transfer_cols, show="headings", height=6)
        self.transfer_tree.heading("moment", text="Moment")
        self.transfer_tree.heading("tip", text="Tip")
        self.transfer_tree.heading("de_la", text="De la")
        self.transfer_tree.heading("la", text="La")
        self.transfer_tree.heading("note", text="Note")
        self.transfer_tree.column("moment", width=145, anchor="w")
        self.transfer_tree.column("tip", width=90, anchor="w")
        self.transfer_tree.column("de_la", width=210, anchor="w")
        self.transfer_tree.column("la", width=210, anchor="w")
        self.transfer_tree.column("note", width=360, anchor="w")
        self.transfer_tree.grid(row=3, column=0, columnspan=8, sticky="nsew", padx=6, pady=(0, 6))
        transfer_wrap.grid_rowconfigure(3, weight=1)

    def _build_orders_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        form = ttk.LabelFrame(frame, text="Ordin medical nou")
        form.pack(fill="x")

        self.order_type_var = tk.StringVar(value="lab")
        self.order_priority_var = tk.StringVar(value="normal")
        ttk.Label(form, text="Tip ordin").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.order_type_var,
            state="readonly",
            values=("lab", "imaging", "medication", "procedure", "consult"),
            width=14,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Prioritate").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.order_priority_var,
            state="readonly",
            values=("stat", "urgent", "normal", "low"),
            width=12,
        ).grid(row=0, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Descriere ordin").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        self.order_text = ScrolledText(form, height=4, wrap="word")
        self.order_text.grid(row=1, column=1, columnspan=3, sticky="ew", padx=6, pady=4)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)

        order_actions = ttk.Frame(form)
        order_actions.grid(row=2, column=0, columnspan=4, sticky="e", padx=6, pady=(0, 6))
        ttk.Button(order_actions, text="Adauga ordin", command=self.add_order).pack(side=LEFT)
        ttk.Button(order_actions, text="Reincarca", command=self.refresh_orders).pack(side=LEFT, padx=6)

        list_wrap = ttk.LabelFrame(frame, text="Ordine medicale")
        list_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))
        cols = ("admission", "type", "priority", "status", "ordered_at", "text")
        self.order_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=10)
        self.order_tree.heading("admission", text="Internare")
        self.order_tree.heading("type", text="Tip")
        self.order_tree.heading("priority", text="Prioritate")
        self.order_tree.heading("status", text="Status")
        self.order_tree.heading("ordered_at", text="Ordonat la")
        self.order_tree.heading("text", text="Descriere")
        self.order_tree.column("admission", width=100, anchor="w")
        self.order_tree.column("type", width=100, anchor="w")
        self.order_tree.column("priority", width=90, anchor="w")
        self.order_tree.column("status", width=90, anchor="w")
        self.order_tree.column("ordered_at", width=150, anchor="w")
        self.order_tree.column("text", width=560, anchor="w")
        self.order_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

        status_actions = ttk.Frame(list_wrap)
        status_actions.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(status_actions, text="Seteaza In lucru", command=lambda: self.update_selected_order("in_progress")).pack(
            side=LEFT
        )
        ttk.Button(status_actions, text="Seteaza Finalizat", command=lambda: self.update_selected_order("done")).pack(
            side=LEFT, padx=6
        )
        ttk.Button(status_actions, text="Seteaza Anulat", command=lambda: self.update_selected_order("cancelled")).pack(
            side=LEFT, padx=6
        )

    def _build_vitals_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.vital_vars = {
            "recorded_at": tk.StringVar(value=now_ts()),
            "temperature_c": tk.StringVar(),
            "systolic_bp": tk.StringVar(),
            "diastolic_bp": tk.StringVar(),
            "pulse": tk.StringVar(),
            "respiratory_rate": tk.StringVar(),
            "spo2": tk.StringVar(),
            "pain_score": tk.StringVar(),
        }

        form = ttk.LabelFrame(frame, text="Semne vitale")
        form.pack(fill="x")

        ttk.Label(form, text="Timestamp").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["recorded_at"], width=20).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Temp C").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["temperature_c"], width=10).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="TA sist").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["systolic_bp"], width=8).grid(row=0, column=5, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="TA diast").grid(row=0, column=6, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["diastolic_bp"], width=8).grid(row=0, column=7, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Puls").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["pulse"], width=10).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Resp/min").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["respiratory_rate"], width=10).grid(row=1, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="SpO2 %").grid(row=1, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["spo2"], width=10).grid(row=1, column=5, sticky="w", padx=6, pady=4)
        ttk.Label(form, text="Durere 0-10").grid(row=1, column=6, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.vital_vars["pain_score"], width=8).grid(row=1, column=7, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Note").grid(row=2, column=0, sticky="nw", padx=6, pady=4)
        self.vital_notes = ScrolledText(form, height=3, wrap="word")
        self.vital_notes.grid(row=2, column=1, columnspan=7, sticky="ew", padx=6, pady=4)
        for idx in range(1, 8):
            form.grid_columnconfigure(idx, weight=1 if idx % 2 == 1 else 0)

        actions = ttk.Frame(form)
        actions.grid(row=3, column=0, columnspan=8, sticky="e", padx=6, pady=(0, 6))
        ttk.Button(actions, text="Adauga vitale", command=self.add_vital).pack(side=LEFT)
        ttk.Button(actions, text="Reincarca", command=self.refresh_vitals).pack(side=LEFT, padx=6)

        list_wrap = ttk.LabelFrame(frame, text="Istoric vitale")
        list_wrap.pack(fill=BOTH, expand=True, pady=(10, 0))
        cols = ("time", "temp", "bp", "pulse", "resp", "spo2", "pain", "notes")
        self.vitals_tree = ttk.Treeview(list_wrap, columns=cols, show="headings", height=10)
        self.vitals_tree.heading("time", text="Timestamp")
        self.vitals_tree.heading("temp", text="Temp C")
        self.vitals_tree.heading("bp", text="TA")
        self.vitals_tree.heading("pulse", text="Puls")
        self.vitals_tree.heading("resp", text="Resp")
        self.vitals_tree.heading("spo2", text="SpO2")
        self.vitals_tree.heading("pain", text="Durere")
        self.vitals_tree.heading("notes", text="Note")
        self.vitals_tree.column("time", width=150, anchor="w")
        self.vitals_tree.column("temp", width=80, anchor="w")
        self.vitals_tree.column("bp", width=90, anchor="w")
        self.vitals_tree.column("pulse", width=80, anchor="w")
        self.vitals_tree.column("resp", width=80, anchor="w")
        self.vitals_tree.column("spo2", width=80, anchor="w")
        self.vitals_tree.column("pain", width=80, anchor="w")
        self.vitals_tree.column("notes", width=560, anchor="w")
        self.vitals_tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def _build_ai_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        self.ai_status_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.ai_status_var, foreground="#1d4ed8").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "Atentie: datele trimise la AI merg catre API extern. "
                "Evita detalii sensibile care nu sunt necesare."
            ),
        ).pack(anchor="w", pady=(2, 8))

        self.chat_box = ScrolledText(frame, height=22, wrap="word", state="disabled")
        self.chat_box.pack(fill=BOTH, expand=True)

        ttk.Label(frame, text="Mesaj catre asistent").pack(anchor="w", pady=(8, 4))
        self.ai_prompt = ScrolledText(frame, height=6, wrap="word")
        self.ai_prompt.pack(fill="x")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(8, 0))
        self.send_btn = ttk.Button(actions, text="Trimite", command=self.send_ai_message)
        self.send_btn.pack(side=LEFT)
        self.summary_btn = ttk.Button(actions, text="Genereaza rezumat", command=self.generate_summary_prompt)
        self.summary_btn.pack(side=LEFT, padx=8)
        self.plan24_btn = ttk.Button(actions, text="Plan 24h", command=self.generate_plan_24h_prompt)
        self.plan24_btn.pack(side=LEFT, padx=8)
        self.discharge_btn = ttk.Button(actions, text="Draft externare", command=self.generate_discharge_draft_prompt)
        self.discharge_btn.pack(side=LEFT, padx=8)
        self.alert_explain_btn = ttk.Button(actions, text="Explica alerta", command=self.explain_latest_alert_prompt)
        self.alert_explain_btn.pack(side=LEFT, padx=8)
        ttk.Button(actions, text="Curata mesaj", command=lambda: self.ai_prompt.delete("1.0", END)).pack(side=LEFT)

        self.ai_template_key: Optional[str] = None

    def refresh_ai_status(self) -> None:
        if not getattr(self, "ai_enabled", True):
            self.ai_status_var.set("AI dezactivat din Setari.")
            return
        if not self._ai_role_allowed():
            self.ai_status_var.set("AI indisponibil pentru rolul curent.")
            return
        if self.ai.is_available():
            self.ai_status_var.set(f"AI conectat. Model: {self.ai.model}; temp={self.ai_temperature}")
        else:
            self.ai_status_var.set(f"AI indisponibil. {self.ai.unavailable_reason()}")

    def _get_ai_template(self, key: str, fallback: str) -> str:
        setting_key = f"AI_TEMPLATE_{key.upper()}"
        text = self.db.get_setting(setting_key, fallback)
        return (text or fallback).strip() or fallback

    def _set_ai_template_prompt(self, template_key: str, fallback: str) -> None:
        self.ai_template_key = template_key
        prompt = self._get_ai_template(template_key, fallback)
        self.ai_prompt.delete("1.0", END)
        self.ai_prompt.insert("1.0", prompt)

    def _latest_patient_alert_summary(self) -> str:
        if self.current_patient_id is None:
            return "Nu exista pacient selectat."
        alerts = self.db.list_vital_alerts_dashboard(department="", hours=24, limit=300)
        patient_alerts = [a for a in alerts if int(a.get("patient_id") or 0) == int(self.current_patient_id)]
        if not patient_alerts:
            return "Nu exista alerte vitale recente pentru pacientul curent."
        newest = sorted(patient_alerts, key=lambda r: str(r.get("recorded_at") or ""), reverse=True)[0]
        return (
            f"Ultima alerta la {newest.get('recorded_at')}: {newest.get('reasons')} | "
            f"note: {newest.get('notes') or '-'}"
        )

    @staticmethod
    def _format_ai_structured_reply(structured: Dict[str, str]) -> str:
        lines = [
            f"Situatie: {structured.get('situatie', '-')}",
            f"Risc: {structured.get('risc', '-')}",
            f"Recomandare: {structured.get('recomandare', '-')}",
            f"Monitorizare: {structured.get('monitorizare', '-')}",
        ]
        missing = (structured.get("informatii_lipsa") or "").strip()
        if missing:
            lines.append(f"Informatii lipsa: {missing}")
        disclaimer = (structured.get("disclaimer") or "").strip()
        if disclaimer:
            lines.append(disclaimer)
        return "\n".join(lines).strip()

    @staticmethod
    def _safety_finalize_ai_text(ai_text: str) -> str:
        text = (ai_text or "").strip()
        if not text:
            return "Nu am primit un raspuns valid de la AI."
        mandatory_disclaimer = "Acest output este informativ si nu inlocuieste decizia medicala."
        if mandatory_disclaimer.lower() not in text.lower():
            text = f"{text}\n\n{mandatory_disclaimer}"
        return text

    def refresh_patients(self) -> None:
        selected = self._selected_patient_iid()
        for iid in self.patient_tree.get_children():
            self.patient_tree.delete(iid)
        status_filter, status_date = self._resolve_patient_filters(persist=True)
        rows = self.db.list_patients(
            self.search_var.get().strip(),
            status_filter=status_filter,
            status_date=status_date,
        )
        for row in rows:
            full_name = f"{row['last_name']} {row['first_name']}".strip()
            self.patient_tree.insert(
                "",
                END,
                iid=str(row["id"]),
                values=(full_name, row.get("reception_flag", "-") or "-", row["phone"], row["email"]),
            )
        if selected and self.patient_tree.exists(selected):
            self.patient_tree.selection_set(selected)
            self.patient_tree.focus(selected)

    def _selected_patient_iid(self) -> Optional[str]:
        selected = self.patient_tree.selection()
        return selected[0] if selected else None

    def on_patient_select(self, _event: Any = None) -> None:
        iid = self._selected_patient_iid()
        if not iid:
            return
        patient_id = int(iid)
        patient = self.db.get_patient(patient_id)
        if not patient:
            return
        self.current_patient_id = patient_id
        self._load_patient_into_form(patient)
        self.refresh_visits()
        self.refresh_admissions()
        self.refresh_orders()
        self.refresh_vitals()
        self.refresh_bookings()
        self.refresh_transfers()
        self.refresh_billing_records()
        self.load_chat_history()

    def new_patient(self) -> None:
        self.current_patient_id = None
        for var in self.patient_vars.values():
            var.set("")
        for widget in self.patient_text_widgets.values():
            widget.delete("1.0", END)
        self.visit_vars["visit_date"].set(datetime.now().strftime("%Y-%m-%d"))
        self.visit_vars["reason"].set("")
        self.visit_vars["diagnosis"].set("")
        self.visit_vars["treatment"].set("")
        self.visit_notes.delete("1.0", END)
        self.admission_vars["admitted_at"].set(now_ts())
        self.admission_vars["admission_type"].set("inpatient")
        self.admission_vars["triage_level"].set("3")
        for key in ("department", "ward", "bed", "attending_clinician", "chief_complaint"):
            self.admission_vars[key].set("")
        self.order_type_var.set("lab")
        self.order_priority_var.set("normal")
        for iid in self.visit_tree.get_children():
            self.visit_tree.delete(iid)
        for iid in self.admission_tree.get_children():
            self.admission_tree.delete(iid)
        for iid in self.order_tree.get_children():
            self.order_tree.delete(iid)
        for iid in self.vitals_tree.get_children():
            self.vitals_tree.delete(iid)
        for iid in self.booking_tree.get_children():
            self.booking_tree.delete(iid)
        for iid in self.transfer_tree.get_children():
            self.transfer_tree.delete(iid)
        for iid in self.billing_tree.get_children():
            self.billing_tree.delete(iid)
        self.active_admission_var.set("Fara internare activa.")
        self.discharge_summary_box.delete("1.0", END)
        if hasattr(self, "admission_diag_vars"):
            for key in (
                "referral_diagnosis",
                "admission_diagnosis",
                "discharge_diagnosis",
                "secondary_diagnoses",
                "dietary_regimen",
                "admission_criteria",
                "discharge_criteria",
            ):
                self.admission_diag_vars[key].set("")
        self.order_text.delete("1.0", END)
        self.vital_notes.delete("1.0", END)
        self.vital_vars["recorded_at"].set(now_ts())
        self.booking_vars["starts_at"].set(now_ts())
        self.booking_vars["ends_at"].set((datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        for key in ("department", "ward", "bed", "operating_room", "attending_clinician"):
            self.booking_vars[key].set("")
        if hasattr(self, "booking_show_conflicts_only_var"):
            self.booking_show_conflicts_only_var.set(False)
        self.booking_notes_box.delete("1.0", END)
        self.transfer_vars["transferred_at"].set(now_ts())
        for key in ("to_department", "to_ward", "to_bed"):
            self.transfer_vars[key].set("")
        self.transfer_notes_box.delete("1.0", END)
        self.billing_amount_var.set("0")
        self.billing_notes_box.delete("1.0", END)
        self._set_visit_details("")
        self._set_chat_text("")

    def _collect_patient_payload(self) -> Dict[str, str]:
        payload: Dict[str, str] = {k: v.get().strip() for k, v in self.patient_vars.items()}
        for key, widget in self.patient_text_widgets.items():
            payload[key] = widget.get("1.0", END).strip()
        return payload

    def _validate_patient_payload(self, payload: Dict[str, str]) -> Optional[str]:
        if not payload["first_name"] or not payload["last_name"]:
            return "Prenume si nume sunt obligatorii."

        cnp = payload.get("cnp", "")
        if cnp and (len(cnp) != 13 or not cnp.isdigit()):
            return "CNP trebuie sa aiba exact 13 cifre."

        if payload.get("birth_date"):
            try:
                datetime.strptime(payload["birth_date"], "%Y-%m-%d")
            except ValueError:
                return "Data nasterii are format invalid. Foloseste YYYY-MM-DD."

        email = payload.get("email", "")
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return "Email invalid."

        for field_name, label in (("height_cm", "Inaltime"), ("weight_kg", "Greutate")):
            value = payload.get(field_name, "")
            if not value:
                continue
            normalized = value.replace(",", ".")
            try:
                parsed = float(normalized)
            except ValueError:
                return f"{label} trebuie sa fie numar."
            if parsed <= 0:
                return f"{label} trebuie sa fie mai mare decat 0."
            payload[field_name] = normalized

        return None

    def save_patient(self) -> None:
        if not self._require_role("Salveaza pacient", "admin", "medic", "receptie"):
            return
        payload = self._collect_patient_payload()
        validation_error = self._validate_patient_payload(payload)
        if validation_error:
            messagebox.showerror("Date invalide", validation_error)
            return

        is_new = self.current_patient_id is None
        if self.current_patient_id is None:
            new_id = self.db.create_patient(payload)
            self.current_patient_id = new_id
        else:
            self.db.update_patient(self.current_patient_id, payload)

        self._audit_current_patient("create_patient" if is_new else "update_patient", "")
        self.refresh_patients()
        self.refresh_operational_views()
        self._focus_patient(self.current_patient_id)
        messagebox.showinfo("Succes", "Pacientul a fost salvat.")

    def _focus_patient(self, patient_id: Optional[int]) -> None:
        if not patient_id:
            return
        iid = str(patient_id)
        if self.patient_tree.exists(iid):
            self.patient_tree.selection_set(iid)
            self.patient_tree.focus(iid)
            self.patient_tree.see(iid)
            self.on_patient_select()

    def _load_patient_into_form(self, patient: sqlite3.Row) -> None:
        for key, var in self.patient_vars.items():
            var.set(patient[key] or "")
        for key, widget in self.patient_text_widgets.items():
            widget.delete("1.0", END)
            widget.insert("1.0", patient[key] or "")

    def delete_current_patient(self) -> None:
        if not self._require_role("Sterge pacient", "admin"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Neselectat", "Selecteaza un pacient.")
            return
        confirm = messagebox.askyesno(
            "Confirmare stergere",
            "Stergi pacientul selectat?\nSe vor sterge si consultatiile/conversatiile asociate.",
        )
        if not confirm:
            return
        patient_id = self.current_patient_id
        self.db.delete_patient(self.current_patient_id)
        self._audit(
            "delete_patient",
            self._audit_details_from_pairs(("operation", "user_delete")),
            patient_id,
        )
        self.current_patient_id = None
        self.refresh_patients()
        self.refresh_operational_views()
        self.new_patient()

    def add_visit(self) -> None:
        if not self._require_role("Adauga nota clinica", "admin", "medic", "asistent"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Salveaza sau selecteaza mai intai un pacient.")
            return
        visit_date = self.visit_vars["visit_date"].get().strip() or datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(visit_date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Data invalida", "Format data acceptat: YYYY-MM-DD.")
            return

        reason = self.visit_vars["reason"].get().strip()
        diagnosis = self.visit_vars["diagnosis"].get().strip()
        treatment = self.visit_vars["treatment"].get().strip()
        notes = self.visit_notes.get("1.0", END).strip()

        self.db.add_visit(self.current_patient_id, visit_date, reason, diagnosis, treatment, notes)
        self._audit_current_patient("add_note", "")
        self.visit_vars["reason"].set("")
        self.visit_vars["diagnosis"].set("")
        self.visit_vars["treatment"].set("")
        self.visit_notes.delete("1.0", END)
        self.refresh_visits()

    def refresh_visits(self) -> None:
        for iid in self.visit_tree.get_children():
            self.visit_tree.delete(iid)
        self.visit_map.clear()
        if self.current_patient_id is None:
            self._set_visit_details("")
            return

        rows = self.db.list_visits(self.current_patient_id)
        for row in rows:
            notes_preview = (row["notes"] or "").replace("\n", " ").strip()
            if len(notes_preview) > 70:
                notes_preview = notes_preview[:67] + "..."
            iid = str(row["id"])
            self.visit_map[iid] = dict(row)
            self.visit_tree.insert(
                "",
                END,
                iid=iid,
                values=(row["visit_date"], row["reason"], row["diagnosis"], row["treatment"], notes_preview),
            )
        self._set_visit_details("")

    def on_visit_select(self, _event: Any = None) -> None:
        selected = self.visit_tree.selection()
        if not selected:
            self._set_visit_details("")
            return
        iid = selected[0]
        visit = self.visit_map.get(iid)
        if not visit:
            self._set_visit_details("")
            return

        details = (
            f"Data: {visit.get('visit_date', '')}\n"
            f"Motiv: {visit.get('reason', '')}\n"
            f"Diagnostic: {visit.get('diagnosis', '')}\n"
            f"Tratament: {visit.get('treatment', '')}\n\n"
            f"Note:\n{visit.get('notes', '')}"
        )
        self._set_visit_details(details)

    def _set_visit_details(self, text: str) -> None:
        self.visit_details.configure(state="normal")
        self.visit_details.delete("1.0", END)
        if text:
            self.visit_details.insert("1.0", text)
        self.visit_details.configure(state="disabled")

    def delete_selected_visit(self) -> None:
        if not self._require_role("Sterge nota clinica", "admin", "medic"):
            return
        selected = self.visit_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza o consultatie.")
            return
        visit_id = int(selected[0])
        if not messagebox.askyesno("Confirmare", "Stergi consultatia selectata?"):
            return
        self.db.delete_visit(visit_id)
        self._audit_current_patient(
            "delete_note",
            self._audit_details_from_pairs(("note", "Stergere nota clinica")),
        )
        self.refresh_visits()

    def create_admission(self) -> None:
        if not self._require_role("Creeaza internare", "admin", "medic", "receptie"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return

        admitted_at = self.admission_vars["admitted_at"].get().strip() or now_ts()
        try:
            datetime.strptime(admitted_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("Data invalida", "Format admis la: YYYY-MM-DD HH:MM:SS")
            return

        triage = self.admission_vars["triage_level"].get().strip()
        if triage not in {"1", "2", "3", "4", "5"}:
            messagebox.showerror("Triage invalid", "Triage trebuie intre 1 si 5.")
            return

        payload = {
            "patient_id": str(self.current_patient_id),
            "admission_type": self.admission_vars["admission_type"].get().strip() or "inpatient",
            "triage_level": triage,
            "department": self.admission_vars["department"].get().strip(),
            "ward": self.admission_vars["ward"].get().strip(),
            "bed": self.admission_vars["bed"].get().strip(),
            "attending_clinician": self.admission_vars["attending_clinician"].get().strip(),
            "chief_complaint": self.admission_vars["chief_complaint"].get().strip(),
            "admitted_at": admitted_at,
        }

        if self.db.has_active_bed_conflict(payload["department"], payload["ward"], payload["bed"]):
            messagebox.showerror(
                "Conflict internare",
                "Patul selectat este deja ocupat de o internare activa. Alege alta combinatie sectie/salon/pat.",
            )
            return

        active = self.db.get_active_admission(self.current_patient_id)
        if active:
            proceed = messagebox.askyesno(
                "Internare activa existenta",
                f"Pacientul are deja internare activa ({active['mrn']}). Continui cu o internare noua?",
            )
            if not proceed:
                return

        admission_id, completed_booking_id = self.db.create_admission(payload, self.current_user.get("id"))
        self._audit(
            "create_admission",
            self._audit_details_from_pairs(
                ("admission_id", admission_id),
                ("booking_id", completed_booking_id or "-"),
                ("transition", "scheduled_admission->active" if completed_booking_id else "direct->active"),
            ),
            self.current_patient_id,
        )
        self.admission_vars["admitted_at"].set(now_ts())
        self.admission_vars["chief_complaint"].set("")
        self.refresh_admissions()
        self.refresh_orders()
        self.refresh_vitals()
        self.refresh_bookings()
        self.refresh_operational_views()

    def _selected_admission_id(self) -> Optional[int]:
        selected = self.admission_tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except Exception:
            return None

    def refresh_admissions(self) -> None:
        for iid in self.admission_tree.get_children():
            self.admission_tree.delete(iid)
        self.admission_map.clear()

        if self.current_patient_id is None:
            self.active_admission_var.set("Fara internare activa.")
            self.case_finalization_var.set("Finalizare caz: -")
            self._refresh_discharge_rules_state()
            self.refresh_transfers()
            self.refresh_billing_records()
            return

        rows = self.db.list_admissions(self.current_patient_id, include_closed=True)
        for row in rows:
            iid = str(row["id"])
            self.admission_map[iid] = dict(row)
            display_status = row["status"]
            if (row["status"] or "") == "discharged" and (row["case_finalized_at"] or "").strip():
                display_status = "finalized"
            self.admission_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["mrn"],
                    row["admission_type"],
                    row["triage_level"],
                    row["department"],
                    row["ward"],
                    row["bed"],
                    display_status,
                    row["admitted_at"],
                    row["discharged_at"],
                ),
            )

        active = self.db.get_active_admission(self.current_patient_id)
        if active:
            self.active_admission_var.set(
                f"Internare activa: {active['mrn']} | Sectie {active['department']} | Salon {active['ward']} Pat {active['bed']}"
            )
        else:
            self.active_admission_var.set("Fara internare activa.")
        self._refresh_case_finalization_state()
        self._refresh_discharge_rules_state()
        self.refresh_transfers()
        self.refresh_billing_records()

    def on_admission_select(self, _event: Any = None) -> None:
        selected_id = self._selected_admission_id()
        if not selected_id:
            self.case_finalization_var.set("Finalizare caz: -")
            self._refresh_discharge_rules_state()
            self.refresh_transfers()
            self.refresh_billing_records()
            return
        row = self.admission_map.get(str(selected_id))
        if not row:
            self.case_finalization_var.set("Finalizare caz: -")
            self._refresh_discharge_rules_state()
            self.refresh_transfers()
            self.refresh_billing_records()
            return
        self.discharge_summary_box.delete("1.0", END)
        if row.get("discharge_summary"):
            self.discharge_summary_box.insert("1.0", row["discharge_summary"])
        self._load_selected_admission_diagnoses(selected_id)
        self.transfer_vars["to_department"].set(row.get("department", "") or "")
        self.transfer_vars["to_ward"].set(row.get("ward", "") or "")
        self.transfer_vars["to_bed"].set(row.get("bed", "") or "")
        self._refresh_case_finalization_state()
        self._refresh_discharge_rules_state()
        self.refresh_transfers()
        self.refresh_billing_records()

    def _refresh_discharge_rules_state(self) -> None:
        if not hasattr(self, "discharge_rules_var"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            self.discharge_rules_var.set("Reguli externare: selecteaza o internare pentru evaluare.")
            if hasattr(self, "discharge_rules_label"):
                try:
                    self.discharge_rules_label.configure(foreground="#475569")
                except Exception:
                    pass
            return

        row = self.admission_map.get(str(admission_id)) or {}
        has_final_decont = self.db.has_final_decont(admission_id)
        summary_text = ""
        if hasattr(self, "discharge_summary_box"):
            try:
                summary_text = (self.discharge_summary_box.get("1.0", END) or "").strip()
            except Exception:
                summary_text = ""
        has_summary = bool(summary_text or (row.get("discharge_summary") or "").strip())

        active_rules = 0
        missing_rules = 0

        if bool(getattr(self, "discharge_require_final_decont", False)):
            active_rules += 1
            if not has_final_decont:
                missing_rules += 1
            final_part = f"decont final=ON ({'OK' if has_final_decont else 'LIPSA'})"
        else:
            final_part = "decont final=OFF"

        if bool(getattr(self, "discharge_require_summary", False)):
            active_rules += 1
            if not has_summary:
                missing_rules += 1
            summary_part = f"rezumat=ON ({'OK' if has_summary else 'LIPSA'})"
        else:
            summary_part = "rezumat=OFF"

        self.discharge_rules_var.set(f"Reguli externare: {final_part} | {summary_part}")
        if hasattr(self, "discharge_rules_label"):
            try:
                if active_rules == 0:
                    color = "#475569"
                elif missing_rules == 0:
                    color = "#166534"
                elif missing_rules == active_rules:
                    color = "#b91c1c"
                else:
                    color = "#b45309"
                self.discharge_rules_label.configure(foreground=color)
            except Exception:
                pass

    def _load_selected_admission_diagnoses(self, admission_id: Optional[int]) -> None:
        if not hasattr(self, "admission_diag_vars"):
            return
        for key in (
            "referral_diagnosis",
            "admission_diagnosis",
            "discharge_diagnosis",
            "secondary_diagnoses",
            "dietary_regimen",
            "admission_criteria",
            "discharge_criteria",
        ):
            self.admission_diag_vars[key].set("")
        if not admission_id:
            return
        row = self.db.get_admission_diagnoses(admission_id)
        if not row:
            return
        self.admission_diag_vars["referral_diagnosis"].set(row.get("referral_diagnosis") or "")
        self.admission_diag_vars["admission_diagnosis"].set(row.get("admission_diagnosis") or "")
        self.admission_diag_vars["discharge_diagnosis"].set(row.get("discharge_diagnosis") or "")
        self.admission_diag_vars["secondary_diagnoses"].set(row.get("secondary_diagnoses") or "")
        self.admission_diag_vars["dietary_regimen"].set(row.get("dietary_regimen") or "")
        self.admission_diag_vars["admission_criteria"].set(row.get("admission_criteria") or "")
        self.admission_diag_vars["discharge_criteria"].set(row.get("discharge_criteria") or "")

    def _refresh_case_finalization_state(self) -> None:
        admission_id = self._selected_admission_id()
        if not admission_id:
            self.case_finalization_var.set("Finalizare caz: -")
            self._refresh_discharge_rules_state()
            return
        closure = self.db.get_admission_case_closure(admission_id)
        if closure:
            self.case_finalization_var.set(f"Finalizare caz: DA ({closure['finalized_at']})")
            self._refresh_discharge_rules_state()
            return
        errors = self.db.validate_admission_case(admission_id)
        if not errors:
            self.case_finalization_var.set("Finalizare caz: eligibil pentru finalizare")
            self._refresh_discharge_rules_state()
            return
        self.case_finalization_var.set(f"Finalizare caz: lipsuri ({len(errors)})")
        self._refresh_discharge_rules_state()

    def validate_selected_admission_case(self) -> None:
        if not self._require_role("Valideaza caz", "admin", "medic", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Validare caz", "Selecteaza o internare.")
            return
        errors = self.db.validate_admission_case(admission_id)
        if errors:
            messagebox.showwarning("Validare caz", "Caz neeligibil:\n- " + "\n- ".join(errors))
        else:
            messagebox.showinfo("Validare caz", "Caz eligibil pentru finalizare.")
        self._refresh_case_finalization_state()

    def finalize_selected_admission_case(self) -> None:
        if not self._require_role("Finalizeaza caz", "admin", "medic"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Finalizare caz", "Selecteaza o internare.")
            return
        try:
            self.db.finalize_admission_case(admission_id, self.current_user.get("id"))
        except ValueError as exc:
            messagebox.showerror("Finalizare caz", str(exc))
            return
        self._audit_current_patient(
            "finalize_admission_case",
            self._audit_details_from_pairs(("admission_id", admission_id)),
        )
        self.refresh_admissions()
        self.refresh_patients()

    def refresh_transfers(self) -> None:
        for iid in self.transfer_tree.get_children():
            self.transfer_tree.delete(iid)
        self.transfer_map.clear()
        admission_id = self._selected_admission_id()
        if not admission_id:
            return
        rows = self.db.list_admission_transfers(admission_id, limit=400)
        for row in rows:
            iid = str(row["id"])
            self.transfer_map[iid] = dict(row)
            src = f"{row.get('from_department') or '-'} / {row.get('from_ward') or '-'} / {row.get('from_bed') or '-'}"
            dst = f"{row.get('to_department') or '-'} / {row.get('to_ward') or '-'} / {row.get('to_bed') or '-'}"
            self.transfer_tree.insert(
                "",
                END,
                iid=iid,
                values=(row.get("transferred_at") or "", row.get("action_type") or "", src, dst, row.get("notes") or ""),
            )

    def add_transfer_for_selected_admission(self) -> None:
        if not self._require_role("Transfer internare", "admin", "medic", "asistent"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Transfer", "Selecteaza o internare activa.")
            return
        row = self.admission_map.get(str(admission_id)) or {}
        if (row.get("status") or "") != "active":
            messagebox.showwarning("Transfer", "Transferul se poate inregistra doar pe internari active.")
            return
        transferred_at = (self.transfer_vars["transferred_at"].get() or "").strip() or now_ts()
        try:
            datetime.strptime(transferred_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            messagebox.showerror("Transfer", "Moment transfer invalid. Format: YYYY-MM-DD HH:MM:SS")
            return

        to_department = (self.transfer_vars["to_department"].get() or "").strip()
        to_ward = (self.transfer_vars["to_ward"].get() or "").strip()
        to_bed = (self.transfer_vars["to_bed"].get() or "").strip()
        notes = self.transfer_notes_box.get("1.0", END).strip()
        if not (to_department and to_ward and to_bed):
            messagebox.showerror("Transfer", "Completeaza sectie/salon/pat tinta.")
            return

        try:
            self.db.transfer_admission(
                admission_id,
                to_department=to_department,
                to_ward=to_ward,
                to_bed=to_bed,
                transferred_at=transferred_at,
                notes=notes,
                user_id=self.current_user.get("id"),
            )
        except ValueError as exc:
            messagebox.showerror("Transfer", str(exc))
            return

        self._audit_current_patient(
            "transfer_admission",
            self._audit_details_from_pairs(
                ("admission_id", admission_id),
                ("to", f"{to_department}/{to_ward}/{to_bed}"),
            ),
        )
        self.transfer_notes_box.delete("1.0", END)
        self.transfer_vars["transferred_at"].set(now_ts())
        self.refresh_admissions()
        self.refresh_patients()

    def save_selected_admission_diagnoses(self) -> None:
        if not self._require_role("Salveaza diagnostice FO", "admin", "medic"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Diagnostice", "Selecteaza o internare.")
            return
        payload = {
            "referral_diagnosis": (self.admission_diag_vars["referral_diagnosis"].get() or "").strip(),
            "admission_diagnosis": (self.admission_diag_vars["admission_diagnosis"].get() or "").strip(),
            "discharge_diagnosis": (self.admission_diag_vars["discharge_diagnosis"].get() or "").strip(),
            "secondary_diagnoses": (self.admission_diag_vars["secondary_diagnoses"].get() or "").strip(),
            "dietary_regimen": (self.admission_diag_vars["dietary_regimen"].get() or "").strip(),
            "admission_criteria": (self.admission_diag_vars["admission_criteria"].get() or "").strip(),
            "discharge_criteria": (self.admission_diag_vars["discharge_criteria"].get() or "").strip(),
        }
        try:
            self.db.upsert_admission_diagnoses(admission_id, payload, self.current_user.get("id"))
        except ValueError as exc:
            messagebox.showerror("Diagnostice", str(exc))
            return
        self._audit_current_patient(
            "save_admission_diagnoses",
            self._audit_details_from_pairs(("admission_id", admission_id)),
        )
        messagebox.showinfo("Diagnostice", "Diagnosticele FO au fost salvate.")
        self._refresh_case_finalization_state()

    def refresh_billing_records(self) -> None:
        for iid in self.billing_tree.get_children():
            self.billing_tree.delete(iid)
        self.billing_map.clear()
        admission_id = self._selected_admission_id()
        if not admission_id:
            return
        rows = self.db.list_billing_records(admission_id, limit=300)
        for row in rows:
            iid = str(row["id"])
            self.billing_map[iid] = dict(row)
            self.billing_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row.get("issued_at") or "",
                    row.get("record_type") or "",
                    f"{float(row.get('amount') or 0):.2f}",
                    row.get("currency") or "RON",
                    row.get("status") or "",
                    row.get("notes") or "",
                ),
            )

    def issue_billing_record(self) -> None:
        if not self._require_role("Emite decont", "admin", "medic", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Decont", "Selecteaza o internare.")
            return
        record_type = (self.billing_type_var.get() or "partial").strip().lower()
        issued_at = (self.billing_issued_at_var.get() or "").strip() or now_ts()
        try:
            datetime.strptime(issued_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            messagebox.showerror("Decont", "Data emitere invalida. Format: YYYY-MM-DD HH:MM:SS")
            return
        try:
            amount = float((self.billing_amount_var.get() or "0").strip().replace(",", "."))
        except Exception:
            messagebox.showerror("Decont", "Valoare decont invalida.")
            return
        notes = self.billing_notes_box.get("1.0", END).strip()
        try:
            billing_id = self.db.create_billing_record(
                admission_id=admission_id,
                record_type=record_type,
                amount=amount,
                issued_at=issued_at,
                notes=notes,
                user_id=self.current_user.get("id"),
            )
        except ValueError as exc:
            messagebox.showerror("Decont", str(exc))
            return

        self._audit_current_patient(
            "issue_billing_record",
            self._audit_details_from_pairs(
                ("billing_id", billing_id),
                ("admission_id", admission_id),
                ("type", record_type),
            ),
        )
        self.billing_amount_var.set("0")
        self.billing_notes_box.delete("1.0", END)
        self.refresh_billing_records()
        self.refresh_patients()

    def discharge_selected_admission(self) -> None:
        if not self._require_role("Externeaza internare", "admin", "medic"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Neselectat", "Selecteaza internarea.")
            return
        row = self.admission_map.get(str(admission_id))
        if not row:
            return
        if row.get("status") != "active":
            messagebox.showinfo("Info", "Internarea selectata nu este activa.")
            return
        if bool(getattr(self, "discharge_require_final_decont", False)) and not self.db.has_final_decont(admission_id):
            messagebox.showerror(
                "Externare",
                "Externarea este blocata: lipseste decontul final (regula activa in Setari).",
            )
            return
        summary = self.discharge_summary_box.get("1.0", END).strip()
        if bool(getattr(self, "discharge_require_summary", False)) and not summary:
            messagebox.showerror(
                "Externare",
                "Externarea este blocata: rezumatul externarii este obligatoriu (regula activa in Setari).",
            )
            return
        if not summary:
            if not messagebox.askyesno("Confirmare", "Externezi fara rezumat?"):
                return
        try:
            discharge_booking_id = self.db.discharge_admission(admission_id, summary)
        except ValueError as exc:
            messagebox.showerror("Externare", str(exc))
            return
        self._audit(
            "discharge_admission",
            self._audit_details_from_pairs(
                ("admission_id", admission_id),
                ("transition", "active->scheduled_discharge->discharged"),
                ("booking_id", discharge_booking_id),
            ),
            self.current_patient_id,
        )
        self.refresh_admissions()
        self.refresh_orders()
        self.refresh_vitals()
        self.refresh_bookings()
        self.refresh_transfers()
        self.refresh_billing_records()
        self.refresh_operational_views()

    def _selected_booking_id(self) -> Optional[int]:
        selected = self.booking_tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except Exception:
            return None

    def create_care_booking(self) -> None:
        if not self._require_role("Adauga programare", "admin", "medic", "receptie"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return

        booking_type = (self.booking_vars["booking_type"].get() or "admission").strip().lower()
        starts_at = (self.booking_vars["starts_at"].get() or "").strip()
        ends_at = (self.booking_vars["ends_at"].get() or "").strip()
        try:
            start_dt = datetime.strptime(starts_at, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(ends_at, "%Y-%m-%d %H:%M:%S")
            if end_dt <= start_dt:
                raise ValueError()
        except Exception:
            messagebox.showerror("Programare", "Interval invalid. Format: YYYY-MM-DD HH:MM:SS si end > start.")
            return

        payload = {
            "patient_id": str(self.current_patient_id),
            "booking_type": booking_type,
            "department": (self.booking_vars["department"].get() or "").strip(),
            "ward": (self.booking_vars["ward"].get() or "").strip(),
            "bed": (self.booking_vars["bed"].get() or "").strip(),
            "operating_room": (self.booking_vars["operating_room"].get() or "").strip(),
            "attending_clinician": (self.booking_vars["attending_clinician"].get() or "").strip(),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "notes": self.booking_notes_box.get("1.0", END).strip(),
        }

        if booking_type == "admission":
            if not payload["department"] or not payload["ward"]:
                messagebox.showerror("Programare", "Pentru internare, completeaza Sectie si Salon.")
                return
        elif booking_type == "operation":
            if not payload["operating_room"] or not payload["attending_clinician"]:
                messagebox.showerror("Programare", "Pentru operatie, completeaza Sala operatie si Medic.")
                return
        elif booking_type == "discharge":
            if not payload["attending_clinician"]:
                messagebox.showerror("Programare", "Pentru externare, completeaza Medic.")
                return

        try:
            booking_id = self.db.create_care_booking(payload, self.current_user.get("id"))
        except ValueError as exc:
            messagebox.showerror("Programare", str(exc))
            return

        self._audit_current_patient(
            "create_booking",
            self._audit_details_from_pairs(
                ("booking_id", booking_id),
                ("type", booking_type),
            ),
        )
        self.refresh_bookings()
        self.refresh_patients()

    def refresh_bookings(self) -> None:
        for iid in self.booking_tree.get_children():
            self.booking_tree.delete(iid)
        self.booking_map.clear()
        self._refresh_booking_operation_preview()
        if self.current_patient_id is None:
            return
        rows = self.db.list_care_bookings(self.current_patient_id, limit=400)
        operation_conflict_ids = self._collect_operation_conflict_booking_ids(rows)
        only_conflicts = bool(getattr(self, "booking_show_conflicts_only_var", None) and self.booking_show_conflicts_only_var.get())
        for row in rows:
            if only_conflicts and int(row["id"]) not in operation_conflict_ids:
                continue
            iid = str(row["id"])
            self.booking_map[iid] = dict(row)
            tags = ("operation_conflict",) if int(row["id"]) in operation_conflict_ids else ()
            self.booking_tree.insert(
                "",
                END,
                iid=iid,
                tags=tags,
                values=(
                    row["booking_type"],
                    row["starts_at"],
                    row["ends_at"],
                    row["department"],
                    row["ward"],
                    row["bed"],
                    row["operating_room"],
                    row["attending_clinician"],
                    row["status"],
                ),
            )

        if only_conflicts and hasattr(self, "booking_operation_preview_var"):
            try:
                visible_count = len(self.booking_tree.get_children())
            except Exception:
                visible_count = 0
            current_text = (self.booking_operation_preview_var.get() or "").strip()
            suffix = f" Conflicte afisate: {visible_count}."
            if current_text:
                self.booking_operation_preview_var.set(f"{current_text}{suffix}")
            else:
                self.booking_operation_preview_var.set(f"Conflicte afisate: {visible_count}.")

    def _collect_operation_conflict_booking_ids(self, rows: List[sqlite3.Row]) -> set[int]:
        scheduled_ops: List[Tuple[int, datetime, datetime, str, str]] = []
        for row in rows:
            if (row["booking_type"] or "").strip().lower() != "operation":
                continue
            if (row["status"] or "").strip().lower() != "scheduled":
                continue
            starts_at = (row["starts_at"] or "").strip()
            ends_at = (row["ends_at"] or "").strip()
            try:
                start_dt = datetime.strptime(starts_at, "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(ends_at, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if end_dt <= start_dt:
                continue
            scheduled_ops.append(
                (
                    int(row["id"]),
                    start_dt,
                    end_dt,
                    (row["operating_room"] or "").strip().lower(),
                    (row["attending_clinician"] or "").strip().lower(),
                )
            )

        conflicts: set[int] = set()
        total = len(scheduled_ops)
        for left_idx in range(total):
            left_id, left_start, left_end, left_room, left_clinician = scheduled_ops[left_idx]
            for right_idx in range(left_idx + 1, total):
                right_id, right_start, right_end, right_room, right_clinician = scheduled_ops[right_idx]
                overlaps = left_start < right_end and left_end > right_start
                if not overlaps:
                    continue
                same_room = bool(left_room and right_room and left_room == right_room)
                same_clinician = bool(left_clinician and right_clinician and left_clinician == right_clinician)
                if not (same_room or same_clinician):
                    continue
                conflicts.add(left_id)
                conflicts.add(right_id)
        return conflicts

    def _refresh_booking_operation_preview(self) -> None:
        if not hasattr(self, "booking_operation_preview_var"):
            return

        booking_type = (self.booking_vars["booking_type"].get() or "").strip().lower()
        if booking_type != "operation":
            self.booking_operation_preview_var.set("Previzualizare operatie: activa doar pentru tip=operation.")
            if hasattr(self, "booking_operation_preview_label"):
                self.booking_operation_preview_label.configure(foreground="#475569")
            return

        starts_at = (self.booking_vars["starts_at"].get() or "").strip()
        ends_at = (self.booking_vars["ends_at"].get() or "").strip()
        room = (self.booking_vars["operating_room"].get() or "").strip()
        clinician = (self.booking_vars["attending_clinician"].get() or "").strip()

        if not room and not clinician:
            self.booking_operation_preview_var.set("Previzualizare operatie: completeaza Sala operatie sau Medic pentru verificare ocupare.")
            if hasattr(self, "booking_operation_preview_label"):
                self.booking_operation_preview_label.configure(foreground="#475569")
            return

        try:
            overlaps = self.db.list_operation_booking_overlaps(
                starts_at=starts_at,
                ends_at=ends_at,
                operating_room=room,
                attending_clinician=clinician,
                limit=4,
            )
        except ValueError:
            self.booking_operation_preview_var.set("Previzualizare operatie: interval invalid (format YYYY-MM-DD HH:MM:SS, end > start).")
            if hasattr(self, "booking_operation_preview_label"):
                self.booking_operation_preview_label.configure(foreground="#b45309")
            return
        except Exception:
            self.booking_operation_preview_var.set("Previzualizare operatie: indisponibila momentan.")
            if hasattr(self, "booking_operation_preview_label"):
                self.booking_operation_preview_label.configure(foreground="#b91c1c")
            return

        if not overlaps:
            checks = []
            if room:
                checks.append(f"sala={room}")
            if clinician:
                checks.append(f"medic={clinician}")
            checks_text = " | ".join(checks) if checks else "criterii minime"
            self.booking_operation_preview_var.set(
                f"Previzualizare operatie: fara ocupare detectata pe interval ({checks_text})."
            )
            if hasattr(self, "booking_operation_preview_label"):
                self.booking_operation_preview_label.configure(foreground="#166534")
            return

        items: List[str] = []
        for row in overlaps:
            patient_name = f"{(row['last_name'] or '').strip()} {(row['first_name'] or '').strip()}".strip()
            patient_name = patient_name or "Pacient"
            items.append(
                f"{row['starts_at']} - {row['ends_at']} | sala={row['operating_room'] or '-'} | medic={row['attending_clinician'] or '-'} | {patient_name}"
            )
        details = " || ".join(items)
        self.booking_operation_preview_var.set(
            f"Previzualizare operatie: ocupare detectata ({len(overlaps)}): {details}"
        )
        if hasattr(self, "booking_operation_preview_label"):
            self.booking_operation_preview_label.configure(foreground="#b91c1c")

    def _set_booking_status(self, status: str) -> None:
        if not self._require_role("Actualizeaza programare", "admin", "medic", "receptie"):
            return
        booking_id = self._selected_booking_id()
        if not booking_id:
            messagebox.showwarning("Programare", "Selecteaza o programare.")
            return
        try:
            self.db.update_care_booking_status(booking_id, status)
        except ValueError as exc:
            messagebox.showerror("Programare", str(exc))
            return
        self._audit_current_patient(
            "update_booking_status",
            self._audit_details_from_pairs(
                ("booking_id", booking_id),
                ("status", status),
            ),
        )
        self.refresh_bookings()
        self.refresh_patients()

    def cancel_selected_booking(self) -> None:
        self._set_booking_status("cancelled")

    def complete_selected_booking(self) -> None:
        self._set_booking_status("completed")

    def _active_admission_id(self) -> Optional[int]:
        if self.current_patient_id is None:
            return None
        active = self.db.get_active_admission(self.current_patient_id)
        if not active:
            return None
        return int(active["id"])

    def add_order(self) -> None:
        if not self._require_role("Adauga ordin", "admin", "medic"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return
        order_text = self.order_text.get("1.0", END).strip()
        if not order_text:
            messagebox.showwarning("Gol", "Descriere ordin obligatorie.")
            return
        order_id = self.db.add_order(
            patient_id=self.current_patient_id,
            admission_id=self._active_admission_id(),
            order_type=self.order_type_var.get().strip() or "lab",
            priority=self.order_priority_var.get().strip() or "normal",
            order_text=order_text,
            user_id=self.current_user.get("id"),
        )
        self._audit_current_patient(
            "add_order",
            self._audit_details_from_pairs(("order_id", order_id)),
        )
        self.order_text.delete("1.0", END)
        self.refresh_orders()
        self.refresh_operational_views()

    def refresh_orders(self) -> None:
        for iid in self.order_tree.get_children():
            self.order_tree.delete(iid)
        self.order_map.clear()
        if self.current_patient_id is None:
            return
        rows = self.db.list_orders(self.current_patient_id)
        for row in rows:
            iid = str(row["id"])
            self.order_map[iid] = dict(row)
            text_preview = (row["order_text"] or "").replace("\n", " ").strip()
            if len(text_preview) > 100:
                text_preview = text_preview[:97] + "..."
            self.order_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["admission_id"] or "-",
                    row["order_type"],
                    row["priority"],
                    row["status"],
                    row["ordered_at"],
                    text_preview,
                ),
            )

    def update_selected_order(self, new_status: str) -> None:
        if not self._require_role("Update status ordin", "admin", "medic", "asistent"):
            return
        selected = self.order_tree.selection()
        if not selected:
            messagebox.showwarning("Neselectat", "Selecteaza un ordin.")
            return
        order_id = int(selected[0])
        try:
            self.db.update_order_status(order_id, new_status)
        except ValueError as exc:
            messagebox.showerror("Eroare", str(exc))
            return
        self._audit_current_patient(
            "order_status",
            self._audit_details_from_pairs(
                ("order_id", order_id),
                ("status", new_status),
            ),
        )
        self.refresh_orders()
        self.refresh_operational_views()

    def add_vital(self) -> None:
        if not self._require_role("Adauga vitale", "admin", "medic", "asistent"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return
        recorded_at = self.vital_vars["recorded_at"].get().strip() or now_ts()
        try:
            datetime.strptime(recorded_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("Data invalida", "Format timestamp: YYYY-MM-DD HH:MM:SS")
            return
        payload = {
            "recorded_at": recorded_at,
            "temperature_c": self.vital_vars["temperature_c"].get().strip(),
            "systolic_bp": self.vital_vars["systolic_bp"].get().strip(),
            "diastolic_bp": self.vital_vars["diastolic_bp"].get().strip(),
            "pulse": self.vital_vars["pulse"].get().strip(),
            "respiratory_rate": self.vital_vars["respiratory_rate"].get().strip(),
            "spo2": self.vital_vars["spo2"].get().strip(),
            "pain_score": self.vital_vars["pain_score"].get().strip(),
            "notes": self.vital_notes.get("1.0", END).strip(),
        }
        vital_id = self.db.add_vital(
            patient_id=self.current_patient_id,
            admission_id=self._active_admission_id(),
            payload=payload,
            user_id=self.current_user.get("id"),
        )
        self._audit_current_patient(
            "add_vitals",
            self._audit_details_from_pairs(("vital_id", vital_id)),
        )
        self.vital_vars["recorded_at"].set(now_ts())
        for key in ("temperature_c", "systolic_bp", "diastolic_bp", "pulse", "respiratory_rate", "spo2", "pain_score"):
            self.vital_vars[key].set("")
        self.vital_notes.delete("1.0", END)
        self.refresh_vitals()
        self.refresh_operational_views()
        self.check_new_critical_alerts(show_popup=True)

    def refresh_vitals(self) -> None:
        for iid in self.vitals_tree.get_children():
            self.vitals_tree.delete(iid)
        self.vitals_map.clear()
        if self.current_patient_id is None:
            return
        rows = self.db.list_vitals(self.current_patient_id)
        for row in rows:
            iid = str(row["id"])
            self.vitals_map[iid] = dict(row)
            bp = ""
            if row["systolic_bp"] or row["diastolic_bp"]:
                bp = f"{row['systolic_bp']}/{row['diastolic_bp']}"
            notes_preview = (row["notes"] or "").replace("\n", " ").strip()
            if len(notes_preview) > 90:
                notes_preview = notes_preview[:87] + "..."
            self.vitals_tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["recorded_at"],
                    row["temperature_c"],
                    bp,
                    row["pulse"],
                    row["respiratory_rate"],
                    row["spo2"],
                    row["pain_score"],
                    notes_preview,
                ),
            )

    def _ensure_pdf_backend(self) -> bool:
        if canvas is None or A4 is None:
            messagebox.showerror(
                "PDF indisponibil",
                "Lipseste pachetul reportlab. Ruleaza: pip install reportlab",
            )
            return False
        return True

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "")
        return cleaned.strip("_") or "document"

    def _pdf_draw_block(
        self,
        pdf: Any,
        y: float,
        title: str,
        body: str,
        *,
        left_margin: float = 40,
        top_reset: float = 800,
        line_height: float = 14,
        wrap_chars: int = 110,
    ) -> float:
        if y < 80:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = top_reset
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(left_margin, y, title)
        y -= line_height
        pdf.setFont("Helvetica", 10)
        text = body or "-"
        for paragraph in text.splitlines() or ["-"]:
            wrapped = textwrap.wrap(paragraph, width=wrap_chars) or [""]
            for line in wrapped:
                if y < 60:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 10)
                    y = top_reset
                pdf.drawString(left_margin, y, line)
                y -= line_height
        y -= 6
        return y

    def _build_document_signature(self, doc_type: str, context: str) -> Dict[str, str]:
        timestamp = now_ts()
        username = str(self.current_user.get("username", "unknown"))
        user_id = str(self.current_user.get("id", ""))
        base = f"{doc_type}|{context}|{timestamp}|{username}|{user_id}"
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
        return {
            "doc_type": doc_type,
            "timestamp": timestamp,
            "username": username,
            "user_id": user_id,
            "hash": digest,
        }

    def export_patient_sheet_pdf(self) -> None:
        if not self._require_role("Export fisa PDF", "admin", "medic", "asistent", "receptie"):
            return
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient.")
            return
        if not self._ensure_pdf_backend():
            return
        patient = self.db.get_patient(self.current_patient_id)
        if not patient:
            messagebox.showerror("Eroare", "Pacientul selectat nu exista.")
            return

        admissions = self.db.list_admissions(self.current_patient_id, include_closed=True, limit=12)
        visits = self.db.list_visits(self.current_patient_id, limit=25)
        orders = self.db.list_orders(self.current_patient_id, limit=25)
        vitals = self.db.list_vitals(self.current_patient_id, limit=25)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fisa_pacient_{self.current_patient_id}_{stamp}.pdf"
        out_path = EXPORTS_DIR / self._safe_filename(filename)

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Fisa pacient")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Generat la: {now_ts()}")
        y -= 18

        identity = (
            f"Nume: {patient['last_name']} {patient['first_name']}\n"
            f"CNP: {patient['cnp']}\n"
            f"Data nasterii: {patient['birth_date']}  Sex: {patient['gender']}\n"
            f"Telefon: {patient['phone']}  Email: {patient['email']}\n"
            f"Adresa: {patient['address']}\n"
            f"Asigurator: {patient['insurance_provider']}  Numar: {patient['insurance_id']}"
        )
        y = self._pdf_draw_block(pdf, y, "Date identificare", identity)

        profile = (
            f"Alergii: {patient['allergies']}\n"
            f"Afectiuni cronice: {patient['chronic_conditions']}\n"
            f"Tratament curent: {patient['current_medication']}\n"
            f"Istoric medical: {patient['medical_history']}\n"
            f"Interventii/chirurgii: {patient['surgeries']}\n"
            f"Antecedente familiale: {patient['family_history']}\n"
            f"Stil de viata: {patient['lifestyle_notes']}\n"
            f"Grupa sanguina: {patient['blood_type']}  Inaltime: {patient['height_cm']} cm  Greutate: {patient['weight_kg']} kg\n"
            f"Contact urgenta: {patient['emergency_contact_name']} ({patient['emergency_contact_phone']})"
        )
        y = self._pdf_draw_block(pdf, y, "Date medicale", profile)

        admissions_lines: List[str] = []
        for item in admissions:
            admissions_lines.append(
                f"{item['admitted_at']} | {item['mrn']} | {item['status']} | "
                f"{item['department']} {item['ward']}/{item['bed']} | triage {item['triage_level']} | motiv: {item['chief_complaint']}"
            )
        y = self._pdf_draw_block(pdf, y, "Internari", "\n".join(admissions_lines) if admissions_lines else "-")

        visit_lines: List[str] = []
        for item in visits:
            visit_lines.append(
                f"{item['visit_date']} | motiv: {item['reason']} | diagnostic: {item['diagnosis']} | tratament: {item['treatment']}"
            )
        y = self._pdf_draw_block(pdf, y, "Note clinice", "\n".join(visit_lines) if visit_lines else "-")

        order_lines: List[str] = []
        for item in orders:
            order_lines.append(
                f"{item['ordered_at']} | {item['order_type']} ({item['priority']}) | {item['status']} | {item['order_text']}"
            )
        y = self._pdf_draw_block(pdf, y, "Ordine medicale", "\n".join(order_lines) if order_lines else "-")

        vital_lines: List[str] = []
        for item in vitals:
            vital_lines.append(
                f"{item['recorded_at']} | temp {item['temperature_c']} | TA {item['systolic_bp']}/{item['diastolic_bp']} "
                f"| puls {item['pulse']} | resp {item['respiratory_rate']} | SpO2 {item['spo2']} | durere {item['pain_score']}"
            )
        y = self._pdf_draw_block(pdf, y, "Vitale internare", "\n".join(vital_lines) if vital_lines else "-")

        signature = self._build_document_signature(
            "fisa_pacient",
            f"patient_id={self.current_patient_id}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        y = self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)

        pdf.save()
        self._audit_current_patient(
            "export_patient_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Export PDF", f"Fisa pacient exportata:\n{out_path}")

    def export_selected_admission_pdf(self, silent: bool = False) -> Optional[Path]:
        if not self._require_role("Export internare PDF", "admin", "medic", "asistent"):
            return None
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Neselectat", "Selecteaza internarea.")
            return None
        if not self._ensure_pdf_backend():
            return None

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Eroare", "Internarea nu a fost gasita.")
            return None

        orders = self.db.list_orders_for_admission(admission_id, limit=200)
        vitals = self.db.list_vitals_for_admission(admission_id, limit=300)
        transfers = self.db.list_admission_transfers(admission_id, limit=500)
        notes = self.db.list_visits(int(row["patient_id"]), limit=30)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"internare_{row['mrn']}_{stamp}.pdf"
        out_path = EXPORTS_DIR / self._safe_filename(filename)

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Raport internare")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Generat la: {now_ts()}  |  MRN: {row['mrn']}")
        y -= 18

        patient_info = (
            f"Pacient: {row['last_name']} {row['first_name']}\n"
            f"CNP: {row['cnp']}  Nastere: {row['birth_date']}  Sex: {row['gender']}\n"
            f"Telefon: {row['phone']}\n"
            f"Adresa: {row['address']}\n"
            f"Asigurator: {row['insurance_provider']}  Nr: {row['insurance_id']}"
        )
        y = self._pdf_draw_block(pdf, y, "Pacient", patient_info)

        admission_info = (
            f"Tip: {row['admission_type']}  Triage: {row['triage_level']}\n"
            f"Sectie: {row['department']}  Salon: {row['ward']}  Pat: {row['bed']}\n"
            f"Medic curant: {row['attending_clinician']}\n"
            f"Motiv prezentare: {row['chief_complaint']}\n"
            f"Status: {row['status']}\n"
            f"Admis la: {row['admitted_at']}\n"
            f"Externat la: {row['discharged_at']}"
        )
        y = self._pdf_draw_block(pdf, y, "Internare", admission_info)
        diagnosis_info = (
            f"Trimitere: {row.get('referral_diagnosis') or '-'}\n"
            f"Internare: {row.get('admission_diagnosis') or '-'}\n"
            f"Externare: {row.get('discharge_diagnosis') or '-'}\n"
            f"Secundare: {row.get('secondary_diagnoses') or '-'}\n"
            f"Regim alimentar: {row.get('dietary_regimen') or '-'}\n"
            f"Criterii internare: {row.get('admission_criteria') or '-'}\n"
            f"Criterii externare: {row.get('discharge_criteria') or '-'}"
        )
        y = self._pdf_draw_block(pdf, y, "Diagnostice FO", diagnosis_info)
        y = self._pdf_draw_block(pdf, y, "Rezumat externare", row["discharge_summary"] or "-")

        order_lines = [
            f"{o['ordered_at']} | {o['priority']} | {o['last_name']} {o['first_name']} | "
            f"{o['order_type']} | {o['status']} | {o['order_text']}"
            for o in orders
        ]
        y = self._pdf_draw_block(pdf, y, "Ordine internare", "\n".join(order_lines) if order_lines else "-")

        vital_lines = [
            f"{v['recorded_at']} | temp {v['temperature_c']} | TA {v['systolic_bp']}/{v['diastolic_bp']} | "
            f"puls {v['pulse']} | resp {v['respiratory_rate']} | SpO2 {v['spo2']} | durere {v['pain_score']}"
            for v in vitals
        ]
        y = self._pdf_draw_block(pdf, y, "Vitale internare", "\n".join(vital_lines) if vital_lines else "-")

        transfer_lines = []
        for t in transfers:
            src = f"{t['from_department'] or '-'} / {t['from_ward'] or '-'} / {t['from_bed'] or '-'}"
            dst = f"{t['to_department'] or '-'} / {t['to_ward'] or '-'} / {t['to_bed'] or '-'}"
            transfer_lines.append(
                f"{t['transferred_at']} | {t['action_type']} | {src} -> {dst} | {t['notes'] or '-'}"
            )
        y = self._pdf_draw_block(
            pdf,
            y,
            "Jurnal transferuri (cronologic)",
            "\n".join(transfer_lines) if transfer_lines else "-",
        )

        note_lines = [
            f"{n['visit_date']} | {n['reason']} | {n['diagnosis']} | {n['treatment']}"
            for n in notes
        ]
        y = self._pdf_draw_block(pdf, y, "Note clinice asociate pacientului", "\n".join(note_lines) if note_lines else "-")

        signature = self._build_document_signature(
            "raport_internare",
            f"admission_id={admission_id}|mrn={row['mrn']}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        y = self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)

        pdf.save()
        self._audit(
            "export_admission_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
            int(row["patient_id"]),
        )
        if not silent:
            messagebox.showinfo("Export PDF", f"Raport internare exportat:\n{out_path}")
        return out_path

    def _build_admission_reporting_checklist(self, admission_id: int) -> Dict[str, Any]:
        row = self.db.get_admission_for_export(admission_id)
        if not row:
            return {
                "ok": False,
                "lines": ["âś— Internare inexistenta."],
                "errors": ["Internare inexistenta."],
            }

        errors = self.db.validate_admission_case(admission_id)
        billing = self.db.list_billing_records(admission_id, limit=500)
        partial_total = sum(float(item["amount"] or 0) for item in billing if (item["record_type"] or "") == "partial")
        final_total = sum(float(item["amount"] or 0) for item in billing if (item["record_type"] or "") == "final")
        transfers = self.db.list_admission_transfers(admission_id, limit=500)
        closure = self.db.get_admission_case_closure(admission_id)

        checks = [
            ("Internare externata", (row["status"] or "") == "discharged"),
            ("Data/ora externare completata", bool((row["discharged_at"] or "").strip())),
            ("Rezumat externare completat", bool((row["discharge_summary"] or "").strip())),
            ("Diagnostic internare completat", bool((row.get("admission_diagnosis") or "").strip())),
            ("Diagnostic externare completat", bool((row.get("discharge_diagnosis") or "").strip())),
            ("Regim alimentar completat", bool((row.get("dietary_regimen") or "").strip())),
            ("Criterii internare completate", bool((row.get("admission_criteria") or "").strip())),
            ("Criterii externare completate", bool((row.get("discharge_criteria") or "").strip())),
            ("Decont final emis", self.db.has_final_decont(admission_id)),
            ("Caz finalizat", closure is not None),
        ]
        doc_checks = [
            (
                "Raport internare PDF: date minime complete",
                bool((row["first_name"] or "").strip())
                and bool((row["last_name"] or "").strip())
                and bool((row["admitted_at"] or "").strip())
                and bool((row["department"] or "").strip())
                and bool((row["attending_clinician"] or "").strip()),
            ),
            (
                "Bilet externare PDF: eligibil emitere",
                (row["status"] or "") == "discharged"
                and bool((row["discharged_at"] or "").strip())
                and bool((row["discharge_summary"] or "").strip())
                and bool((row.get("discharge_diagnosis") or "").strip())
                and bool((row.get("discharge_criteria") or "").strip()),
            ),
        ]
        lines = [f"{'âś“' if ok else 'âś—'} {label}" for label, ok in checks]
        lines.append("Documente FO obligatorii:")
        lines.extend([f"{'âś“' if ok else 'âś—'} {label}" for label, ok in doc_checks])
        lines.append(f"Info: transferuri inregistrate = {len(transfers)}")
        lines.append(f"Info: decont partial total = {partial_total:.2f} RON")
        lines.append(f"Info: decont final total = {final_total:.2f} RON")
        if errors:
            lines.append("Lipsuri detectate:")
            lines.extend([f"- {item}" for item in errors])
        return {
            "ok": len(errors) == 0,
            "lines": lines,
            "errors": errors,
            "row": row,
            "partial_total": partial_total,
            "final_total": final_total,
        }

    def show_selected_admission_reporting_checklist(self) -> None:
        if not self._require_role("Checklist raportare", "admin", "medic", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Checklist raportare", "Selecteaza internarea.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        title = "Checklist raportare - OK" if report.get("ok") else "Checklist raportare - Incomplet"
        messagebox.showinfo(title, "\n".join(report.get("lines", [])))

    def export_selected_discharge_ticket_pdf(self, silent: bool = False) -> Optional[Path]:
        if not self._require_role("Bilet externare PDF", "admin", "medic", "asistent"):
            return None
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Neselectat", "Selecteaza internarea.")
            return None
        if not self._ensure_pdf_backend():
            return None

        report = self._build_admission_reporting_checklist(admission_id)
        row = report.get("row")
        if not row:
            messagebox.showerror("Eroare", "Internarea nu a fost gasita.")
            return None
        if (row["status"] or "") != "discharged":
            messagebox.showwarning("Bilet externare", "Biletul de externare se exporta doar pentru caz externat.")
            return None

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bilet_externare_{row['mrn']}_{stamp}.pdf"
        out_path = EXPORTS_DIR / self._safe_filename(filename)
        transfers = self.db.list_admission_transfers(admission_id, limit=500)

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Bilet de externare")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Generat la: {now_ts()}  |  MRN: {row['mrn']}")
        y -= 16

        patient_info = (
            f"Pacient: {row['last_name']} {row['first_name']}\n"
            f"CNP: {row['cnp']}  Nastere: {row['birth_date']}  Sex: {row['gender']}\n"
            f"Telefon: {row['phone']}\n"
            f"Asigurator: {row['insurance_provider']}  Nr: {row['insurance_id']}"
        )
        y = self._pdf_draw_block(pdf, y, "Identificare pacient", patient_info)

        discharge_info = (
            f"Internare: {row['admitted_at']}\n"
            f"Externare: {row['discharged_at']}\n"
            f"Sectie/Salon/Pat: {row['department']} / {row['ward']} / {row['bed']}\n"
            f"Medic curant: {row['attending_clinician']}\n"
            f"Tip internare: {row['admission_type']}  |  Triage: {row['triage_level']}"
        )
        y = self._pdf_draw_block(pdf, y, "Detalii externare", discharge_info)
        diagnosis_info = (
            f"Trimitere: {row.get('referral_diagnosis') or '-'}\n"
            f"Internare: {row.get('admission_diagnosis') or '-'}\n"
            f"Externare: {row.get('discharge_diagnosis') or '-'}\n"
            f"Secundare: {row.get('secondary_diagnoses') or '-'}\n"
            f"Regim alimentar: {row.get('dietary_regimen') or '-'}\n"
            f"Criterii internare: {row.get('admission_criteria') or '-'}\n"
            f"Criterii externare: {row.get('discharge_criteria') or '-'}"
        )
        y = self._pdf_draw_block(pdf, y, "FO tipizat", diagnosis_info)
        y = self._pdf_draw_block(pdf, y, "Rezumat externare", row["discharge_summary"] or "-")

        billing_summary = (
            f"Decont partial total: {float(report.get('partial_total', 0)):.2f} RON\n"
            f"Decont final total: {float(report.get('final_total', 0)):.2f} RON\n"
            f"Finalizare caz: {'DA' if report.get('ok') else 'NU'}"
        )
        y = self._pdf_draw_block(pdf, y, "Sumar financiar", billing_summary)
        checklist_lines = list(report.get("lines", []))
        fo_compliance_lines = [
            line for line in checklist_lines if any(
                token in line for token in (
                    "Diagnostic internare",
                    "Diagnostic externare",
                    "Regim alimentar",
                    "Criterii internare",
                    "Criterii externare",
                )
            )
        ]
        if fo_compliance_lines:
            y = self._pdf_draw_block(pdf, y, "Conformitate FO", "\n".join(fo_compliance_lines))

        transfer_lines = []
        for t in transfers[-8:]:
            src = f"{t['from_department'] or '-'} / {t['from_ward'] or '-'} / {t['from_bed'] or '-'}"
            dst = f"{t['to_department'] or '-'} / {t['to_ward'] or '-'} / {t['to_bed'] or '-'}"
            transfer_lines.append(f"{t['transferred_at']} | {t['action_type']} | {src} -> {dst}")
        y = self._pdf_draw_block(
            pdf,
            y,
            "Jurnal transferuri (compact)",
            "\n".join(transfer_lines) if transfer_lines else "-",
        )
        y = self._pdf_draw_block(pdf, y, "Checklist raportare", "\n".join(report.get("lines", [])))

        signature = self._build_document_signature(
            "bilet_externare",
            f"admission_id={admission_id}|mrn={row['mrn']}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        y = self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)

        pdf.save()
        self._audit(
            "export_discharge_ticket_pdf",
            self._audit_details_from_pairs(
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
            int(row["patient_id"]),
        )
        if not silent:
            messagebox.showinfo("Export PDF", f"Bilet de externare exportat:\n{out_path}")
        return out_path

    def _export_selected_fo_package_core(self) -> Optional[Tuple[Path, Path]]:
        if not self._require_role("Pachet FO PDF", "admin", "medic", "asistent"):
            return None
        admission_path = self.export_selected_admission_pdf(silent=True)
        if not admission_path:
            return None
        discharge_path = self.export_selected_discharge_ticket_pdf(silent=True)
        if not discharge_path:
            return None
        return admission_path, discharge_path

    def export_selected_fo_package_pdf(self) -> None:
        pack = self._export_selected_fo_package_core()
        if not pack:
            return
        admission_path, discharge_path = pack
        self._audit(
            "export_fo_package_pdf",
            self._audit_details_from_pairs(
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
            ),
            self.current_patient_id,
        )
        messagebox.showinfo(
            "Export pachet FO",
            f"Pachet FO exportat:\n- {admission_path}\n- {discharge_path}",
        )

    def export_selected_fo_package_with_checklist(self) -> None:
        if not self._require_role("Pachet FO + checklist", "admin", "medic", "asistent"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        row = report.get("row")
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return

        pack = self._export_selected_fo_package_core()
        if not pack:
            return
        admission_path, discharge_path = pack

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checklist_name = self._safe_filename(f"fo_checklist_{row['mrn']}_{stamp}.txt")
        checklist_path = EXPORTS_DIR / checklist_name
        lines = list(report.get("lines", []))
        content = [
            f"{DEFAULT_HOSPITAL_NAME} - Checklist raportare FO",
            f"Generat la: {now_ts()}",
            f"MRN: {row['mrn']}",
            f"Pacient: {row['last_name']} {row['first_name']}",
            "",
            *lines,
        ]
        checklist_path.write_text("\n".join(content), encoding="utf-8")

        self._audit(
            "export_fo_package_with_checklist",
            self._audit_details_from_pairs(
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
            ),
            self.current_patient_id,
        )
        messagebox.showinfo(
            "Export pachet FO",
            f"Pachet FO + checklist exportat:\n- {admission_path}\n- {discharge_path}\n- {checklist_path}",
        )

    def _build_selected_fo_package_zip_core(self) -> Optional[Tuple[Path, Path, Path, Path, int]]:
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO ZIP", "Selecteaza internarea.")
            return None
        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO ZIP", "Internarea nu a fost gasita.")
            return None

        pack = self._export_selected_fo_package_core()
        if not pack:
            return None
        admission_path, discharge_path = pack

        report = self._build_admission_reporting_checklist(admission_id)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checklist_name = self._safe_filename(f"fo_checklist_{row['mrn']}_{stamp}.txt")
        checklist_path = EXPORTS_DIR / checklist_name
        lines = list(report.get("lines", []))
        content = [
            f"{DEFAULT_HOSPITAL_NAME} - Checklist raportare FO",
            f"Generat la: {now_ts()}",
            f"MRN: {row['mrn']}",
            f"Pacient: {row['last_name']} {row['first_name']}",
            "",
            *lines,
        ]
        checklist_path.write_text("\n".join(content), encoding="utf-8")

        zip_name = self._safe_filename(f"fo_pachet_{row['mrn']}_{stamp}.zip")
        zip_path = EXPORTS_DIR / zip_name
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(admission_path, arcname=admission_path.name)
            archive.write(discharge_path, arcname=discharge_path.name)
            archive.write(checklist_path, arcname=checklist_path.name)

        return admission_path, discharge_path, checklist_path, zip_path, int(row["patient_id"])

    def export_selected_fo_package_zip(self) -> None:
        if not self._require_role("Pachet FO ZIP", "admin", "medic", "asistent"):
            return
        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        admission_path, discharge_path, checklist_path, zip_path, patient_id = generated

        self._audit(
            "export_fo_package_zip",
            self._audit_details_from_pairs(
                ("zip", zip_path.name),
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
            ),
            patient_id,
        )
        messagebox.showinfo(
            "Export pachet FO ZIP",
            f"Arhiva FO exportata:\n- {zip_path}\n\nInclude:\n- {admission_path.name}\n- {discharge_path.name}\n- {checklist_path.name}",
        )

    def regenerate_and_open_fo_full_package(self) -> None:
        if not self._require_role("Regenereaza + deschide pachet FO complet", "admin", "medic", "asistent"):
            return
        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        admission_path, discharge_path, checklist_path, zip_path, patient_id = generated

        artifacts = [admission_path, discharge_path, checklist_path, zip_path]
        opened: List[str] = []
        for item in artifacts:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(item))
                else:
                    os.system(f'explorer "{str(item)}"')
                opened.append(item.name)
            except Exception:
                continue

        if not opened:
            messagebox.showerror("Pachet FO", "Artefactele au fost regenerate, dar nu au putut fi deschise automat.")
            return

        self._audit(
            "regenerate_open_fo_full_package",
            self._audit_details_from_pairs(
                ("zip", zip_path.name),
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
                ("opened", ",".join(opened)),
            ),
            patient_id,
        )
        messagebox.showinfo(
            "Pachet FO",
            "Pachetul FO complet a fost regenerat si deschis automat.",
        )

    def copy_fo_package_summary_to_clipboard(self) -> None:
        if not self._require_role("Copiaza sumar pachet FO", "admin", "medic", "asistent"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        admission_path, discharge_path, checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        report = self._build_admission_reporting_checklist(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return

        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))
        payload_lines = [
            f"{DEFAULT_HOSPITAL_NAME} - Sumar pachet FO",
            f"Generat la: {now_ts()}",
            f"MRN: {row.get('mrn') or '-'}",
            f"Pacient: {(row.get('last_name') or '').strip()} {(row.get('first_name') or '').strip()}".strip(),
            f"Status checklist: {status_text}",
            "",
            f"Raport internare PDF: {admission_path}",
            f"Bilet externare PDF: {discharge_path}",
            f"Checklist FO TXT: {checklist_path}",
            f"Arhiva FO ZIP: {zip_path}",
        ]
        if errors:
            payload_lines.append("")
            payload_lines.append("Lipsuri checklist:")
            payload_lines.extend([f"- {item}" for item in errors])

        payload = "\n".join(payload_lines)
        self._set_clipboard_text(payload)

        self._audit(
            "copy_fo_package_summary",
            self._audit_details_from_pairs(
                ("zip", zip_path.name),
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
                ("status", status_text),
                ("errors", len(errors)),
            ),
            patient_id,
        )
        messagebox.showinfo("Pachet FO", "Sumarul pachetului FO a fost copiat in clipboard.")

    def copy_fo_package_summary_and_open_email_draft(self) -> None:
        if not self._require_role("Copiaza sumar + draft e-mail", "admin", "medic", "asistent"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        admission_path, discharge_path, checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        report = self._build_admission_reporting_checklist(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return

        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))
        payload_lines = [
            f"{DEFAULT_HOSPITAL_NAME} - Sumar pachet FO",
            f"Generat la: {now_ts()}",
            f"MRN: {row.get('mrn') or '-'}",
            f"Pacient: {(row.get('last_name') or '').strip()} {(row.get('first_name') or '').strip()}".strip(),
            f"Status checklist: {status_text}",
            "",
            f"Raport internare PDF: {admission_path}",
            f"Bilet externare PDF: {discharge_path}",
            f"Checklist FO TXT: {checklist_path}",
            f"Arhiva FO ZIP: {zip_path}",
        ]
        if errors:
            payload_lines.append("")
            payload_lines.append("Lipsuri checklist:")
            payload_lines.extend([f"- {item}" for item in errors])
        payload = "\n".join(payload_lines)

        self._set_clipboard_text(payload)

        recipients = ",".join(self.notify_email_to) if getattr(self, "notify_email_to", None) else ""
        subject = f"Handoff FO - MRN {row.get('mrn') or admission_id} - {status_text}"
        mailto = (
            f"mailto:{urllib_parse.quote(recipients)}"
            f"?subject={urllib_parse.quote(subject)}"
            f"&body={urllib_parse.quote(payload)}"
        )

        draft_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(mailto)
                draft_opened = True
            else:
                os.system(f'start "" "{mailto}"')
                draft_opened = True
        except Exception:
            draft_opened = False

        self._audit(
            "copy_fo_package_summary_open_email_draft",
            self._audit_details_from_pairs(
                ("zip", zip_path.name),
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
                ("status", status_text),
                ("errors", len(errors)),
                ("draft_opened", draft_opened),
            ),
            patient_id,
        )

        if draft_opened:
            messagebox.showinfo("Pachet FO", "Sumarul FO a fost copiat in clipboard si draftul de e-mail a fost deschis.")
        else:
            messagebox.showinfo("Pachet FO", "Sumarul FO a fost copiat in clipboard. Nu am putut deschide draftul de e-mail automat.")

    def copy_fo_short_summary_to_clipboard(self) -> None:
        if not self._require_role("Copiere sumar scurt FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_zip = self._latest_export_artifact(f"fo_pachet_{mrn_tag}_*.zip")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{latest_zip.name if latest_zip else '-'}",
            f"TXT:{latest_checklist.name if latest_checklist else '-'}",
            f"Ts:{now_ts()}",
        ])

        self._set_clipboard_text(short_line)

        self._audit(
            "copy_fo_short_summary",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", latest_zip.name if latest_zip else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
            ),
            int(row["patient_id"]),
        )
        messagebox.showinfo("Pachet FO", "Sumarul scurt FO a fost copiat in clipboard.")

    def copy_fo_short_summary_with_paths_to_clipboard(self) -> None:
        if not self._require_role("Copiere sumar scurt FO + cai", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")
        latest_zip = self._latest_export_artifact(f"fo_pachet_{mrn_tag}_*.zip")

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{latest_zip.name if latest_zip else '-'}",
            f"TXT:{latest_checklist.name if latest_checklist else '-'}",
            f"Ts:{now_ts()}",
        ])

        lines = [
            short_line,
            "",
            "Cai absolute:",
            f"Raport internare PDF: {str(latest_admission) if latest_admission else '-'}",
            f"Bilet externare PDF: {str(latest_discharge) if latest_discharge else '-'}",
            f"Checklist FO TXT: {str(latest_checklist) if latest_checklist else '-'}",
            f"Arhiva FO ZIP: {str(latest_zip) if latest_zip else '-'}",
        ]
        payload = "\n".join(lines)

        self._set_clipboard_text(payload)

        self._audit(
            "copy_fo_short_summary_with_paths",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
                ("zip", latest_zip.name if latest_zip else "-"),
            ),
            int(row["patient_id"]),
        )
        messagebox.showinfo("Pachet FO", "Sumarul scurt FO + caile fisierelor au fost copiate in clipboard.")

    def copy_fo_short_summary_with_paths_and_ps_to_clipboard(self) -> None:
        if not self._require_role("Copiere sumar scurt FO + cai + PS", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")
        latest_zip = self._latest_export_artifact(f"fo_pachet_{mrn_tag}_*.zip")

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{latest_zip.name if latest_zip else '-'}",
            f"TXT:{latest_checklist.name if latest_checklist else '-'}",
            f"Ts:{now_ts()}",
        ])

        available = [item for item in (latest_admission, latest_discharge, latest_checklist, latest_zip) if item]
        if available:
            ps_parts: List[str] = []
            for item in available:
                escaped = str(item).replace("'", "''")
                ps_parts.append(f"Start-Process -FilePath '{escaped}'")
            ps_command = "; ".join(ps_parts)
        else:
            ps_command = "# Nicio cale disponibila pentru deschidere"

        lines = [
            short_line,
            "",
            "Cai absolute:",
            f"Raport internare PDF: {str(latest_admission) if latest_admission else '-'}",
            f"Bilet externare PDF: {str(latest_discharge) if latest_discharge else '-'}",
            f"Checklist FO TXT: {str(latest_checklist) if latest_checklist else '-'}",
            f"Arhiva FO ZIP: {str(latest_zip) if latest_zip else '-'}",
            "",
            "PowerShell rapid open:",
            ps_command,
        ]
        payload = "\n".join(lines)

        self._set_clipboard_text(payload)

        self._audit(
            "copy_fo_short_summary_with_paths_ps",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
                ("zip", latest_zip.name if latest_zip else "-"),
            ),
            int(row["patient_id"]),
        )
        messagebox.showinfo("Pachet FO", "Sumarul scurt FO + caile + comanda PowerShell au fost copiate in clipboard.")

    def regenerate_silent_and_copy_fo_short_summary_with_paths_and_ps(self) -> None:
        if not self._require_role("Regenerare silent + sumar FO + cai + PS", "admin", "medic", "asistent"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        admission_path, discharge_path, checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"TXT:{checklist_path.name}",
            f"Ts:{now_ts()}",
        ])

        artifacts = [admission_path, discharge_path, checklist_path, zip_path]
        ps_parts: List[str] = []
        for item in artifacts:
            escaped = str(item).replace("'", "''")
            ps_parts.append(f"Start-Process -FilePath '{escaped}'")
        ps_command = "; ".join(ps_parts)

        lines = [
            short_line,
            "",
            "Cai absolute:",
            f"Raport internare PDF: {admission_path}",
            f"Bilet externare PDF: {discharge_path}",
            f"Checklist FO TXT: {checklist_path}",
            f"Arhiva FO ZIP: {zip_path}",
            "",
            "PowerShell rapid open:",
            ps_command,
        ]
        payload = "\n".join(lines)

        self._set_clipboard_text(payload)

        self._audit(
            "regenerate_silent_copy_fo_short_summary_with_paths_ps",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("admission_pdf", admission_path.name),
                ("discharge_pdf", discharge_path.name),
                ("checklist", checklist_path.name),
                ("zip", zip_path.name),
            ),
            patient_id,
        )
        messagebox.showinfo("Pachet FO", "Pachet FO regenerat silent si sumarul scurt + cai + PS au fost copiate in clipboard.")

    def regenerate_silent_and_copy_fo_minimal_handoff(self) -> None:
        if not self._require_role("Handoff minim", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        _admission_path, _discharge_path, _checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"Ts:{now_ts()}",
        ])
        payload = "\n".join([
            short_line,
            f"ZIP_PATH: {zip_path}",
        ])

        self._set_clipboard_text(payload)

        self._audit(
            "regenerate_silent_copy_fo_minimal_handoff",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", zip_path.name),
            ),
            patient_id,
        )
        messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard (linie scurta + ZIP).")

    def regenerate_silent_copy_fo_minimal_handoff_and_open_zip(self) -> None:
        if not self._require_role("Handoff minim + deschide ZIP", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        _admission_path, _discharge_path, _checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"Ts:{now_ts()}",
        ])
        payload = "\n".join([
            short_line,
            f"ZIP_PATH: {zip_path}",
        ])

        self._set_clipboard_text(payload)

        zip_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(zip_path))
                zip_opened = True
            else:
                os.system(f'explorer "{str(zip_path)}"')
                zip_opened = True
        except Exception:
            zip_opened = False

        self._audit(
            "regenerate_silent_copy_fo_minimal_handoff_open_zip",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", zip_path.name),
                ("zip_opened", zip_opened),
            ),
            patient_id,
        )
        if zip_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard si arhiva ZIP a fost deschisa.")
        else:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard. Arhiva ZIP nu a putut fi deschisa automat.")

    def regenerate_silent_copy_fo_minimal_handoff_open_zip_and_email(self) -> None:
        if not self._require_role("Handoff minim + ZIP + e-mail", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        _admission_path, _discharge_path, _checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"Ts:{now_ts()}",
        ])
        payload = "\n".join([
            short_line,
            f"ZIP_PATH: {zip_path}",
        ])

        self._set_clipboard_text(payload)

        zip_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(zip_path))
                zip_opened = True
            else:
                os.system(f'explorer "{str(zip_path)}"')
                zip_opened = True
        except Exception:
            zip_opened = False

        recipients = ",".join(self.notify_email_to) if getattr(self, "notify_email_to", None) else ""
        subject = f"Handoff minim FO - MRN {row.get('mrn') or admission_id} - {status_text}"
        mailto = (
            f"mailto:{urllib_parse.quote(recipients)}"
            f"?subject={urllib_parse.quote(subject)}"
            f"&body={urllib_parse.quote(payload)}"
        )
        draft_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(mailto)
                draft_opened = True
            else:
                os.system(f'start "" "{mailto}"')
                draft_opened = True
        except Exception:
            draft_opened = False

        self._audit(
            "regenerate_silent_copy_fo_minimal_handoff_open_zip_email",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", zip_path.name),
                ("zip_opened", zip_opened),
                ("draft_opened", draft_opened),
            ),
            patient_id,
        )

        if zip_opened and draft_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard, ZIP deschis si draft e-mail lansat.")
        elif zip_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard si ZIP deschis. Draftul e-mail nu a putut fi lansat automat.")
        elif draft_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard si draft e-mail lansat. ZIP nu a putut fi deschis automat.")
        else:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard. ZIP si draftul e-mail nu au putut fi deschise automat.")

    def regenerate_silent_copy_fo_minimal_handoff_open_zip_email_and_checklist(self) -> None:
        if not self._require_role("Handoff minim + ZIP + e-mail + checklist", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        _admission_path, _discharge_path, checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"Ts:{now_ts()}",
        ])
        payload = "\n".join([
            short_line,
            f"ZIP_PATH: {zip_path}",
            f"CHECKLIST_PATH: {checklist_path}",
        ])

        self._set_clipboard_text(payload)

        zip_opened = False
        checklist_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(zip_path))
                zip_opened = True
            else:
                os.system(f'explorer "{str(zip_path)}"')
                zip_opened = True
        except Exception:
            zip_opened = False

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(checklist_path))
                checklist_opened = True
            else:
                os.system(f'explorer "{str(checklist_path)}"')
                checklist_opened = True
        except Exception:
            checklist_opened = False

        recipients = ",".join(self.notify_email_to) if getattr(self, "notify_email_to", None) else ""
        subject = f"Handoff minim FO - MRN {row.get('mrn') or admission_id} - {status_text}"
        mailto = (
            f"mailto:{urllib_parse.quote(recipients)}"
            f"?subject={urllib_parse.quote(subject)}"
            f"&body={urllib_parse.quote(payload)}"
        )
        draft_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(mailto)
                draft_opened = True
            else:
                os.system(f'start "" "{mailto}"')
                draft_opened = True
        except Exception:
            draft_opened = False

        self._audit(
            "regenerate_silent_copy_fo_minimal_handoff_open_zip_email_checklist",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", zip_path.name),
                ("checklist", checklist_path.name),
                ("zip_opened", zip_opened),
                ("checklist_opened", checklist_opened),
                ("draft_opened", draft_opened),
            ),
            patient_id,
        )

        if zip_opened and checklist_opened and draft_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim copiat in clipboard, ZIP + checklist deschise si draft e-mail lansat.")
        else:
            messagebox.showinfo(
                "Pachet FO",
                "Handoff minim executat partial: clipboard OK; verificati deschiderea ZIP/checklist/draft e-mail.",
            )

    def regenerate_silent_copy_fo_minimal_all_in(self) -> None:
        if not self._require_role("Handoff minim all-in", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Pachet FO", "Selecteaza internarea.")
            return

        generated = self._build_selected_fo_package_zip_core()
        if not generated:
            return
        _admission_path, _discharge_path, checklist_path, zip_path, patient_id = generated

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Pachet FO", "Internarea nu a fost gasita.")
            return
        report = self._build_admission_reporting_checklist(admission_id)
        status_text = "OK" if report.get("ok") else "INCOMPLET"
        errors = list(report.get("errors", []))

        short_line = " | ".join([
            f"MRN:{row.get('mrn') or '-'}",
            f"Pacient:{((row.get('last_name') or '').strip() + ' ' + (row.get('first_name') or '').strip()).strip() or '-'}",
            f"Checklist:{status_text}",
            f"Lipsuri:{len(errors)}",
            f"ZIP:{zip_path.name}",
            f"Ts:{now_ts()}",
        ])
        payload = "\n".join([
            short_line,
            f"ZIP_PATH: {zip_path}",
            f"CHECKLIST_PATH: {checklist_path}",
        ])

        self._set_clipboard_text(payload)

        zip_opened = False
        checklist_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(zip_path))
                zip_opened = True
            else:
                os.system(f'explorer "{str(zip_path)}"')
                zip_opened = True
        except Exception:
            zip_opened = False

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(checklist_path))
                checklist_opened = True
            else:
                os.system(f'explorer "{str(checklist_path)}"')
                checklist_opened = True
        except Exception:
            checklist_opened = False

        recipients = ",".join(self.notify_email_to) if getattr(self, "notify_email_to", None) else ""
        subject = f"Handoff minim FO all-in - MRN {row.get('mrn') or admission_id} - {status_text}"
        mailto = (
            f"mailto:{urllib_parse.quote(recipients)}"
            f"?subject={urllib_parse.quote(subject)}"
            f"&body={urllib_parse.quote(payload)}"
        )
        draft_opened = False
        try:
            if hasattr(os, "startfile"):
                os.startfile(mailto)
                draft_opened = True
            else:
                os.system(f'start "" "{mailto}"')
                draft_opened = True
        except Exception:
            draft_opened = False

        self._audit(
            "regenerate_silent_copy_fo_minimal_all_in",
            self._audit_details_from_pairs(
                ("mrn", row.get("mrn") or "-"),
                ("status", status_text),
                ("errors", len(errors)),
                ("zip", zip_path.name),
                ("checklist", checklist_path.name),
                ("zip_opened", zip_opened),
                ("checklist_opened", checklist_opened),
                ("draft_opened", draft_opened),
            ),
            patient_id,
        )

        if zip_opened and checklist_opened and draft_opened:
            messagebox.showinfo("Pachet FO", "Handoff minim all-in executat: clipboard + ZIP + checklist + draft e-mail.")
        else:
            messagebox.showinfo(
                "Pachet FO",
                "Handoff minim all-in partial: clipboard OK; verificati deschiderea ZIP/checklist/draft e-mail.",
            )

    def reset_fo_handoff_block(self) -> None:
        if not self._require_role("Reseteaza blocul Handoff FO", "admin", "medic", "asistent", "receptie"):
            return
        self._set_clipboard_text("")
        self._track_handoff_status_after_action("fo_handoff_reset")
        self._audit_current_patient(
            "reset_fo_handoff_block",
            self._audit_details_from_pairs(("clipboard", "cleared")),
        )
        messagebox.showinfo(
            "Handoff FO resetat",
            "Clipboard golit. Pentru reluare rapida foloseste:\n- Handoff minim\n- Handoff minim + deschide ZIP\n- Handoff minim all-in",
        )

    def _build_handoff_status_lines(self, filter_mode: str = "all") -> List[str]:
        compact = "ON" if bool(getattr(self, "handoff_compact_mode", False)) else "OFF"
        compact_mode_value = 1 if bool(getattr(self, "handoff_compact_mode", False)) else 0
        generated_at = now_ts()
        generated_at_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        session_date = datetime.now().strftime("%Y-%m-%d")
        weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        session_day_of_week = weekday_names[datetime.now().weekday()]
        generated_at_unix = int(time.time())
        last_key = str(getattr(self, "handoff_last_action_key", "") or "")
        last_ts = str(getattr(self, "handoff_last_action_ts", "") or "")
        history = list(getattr(self, "handoff_recent_actions", []) or [])[:5]
        mode = self._normalize_handoff_status_filter_mode(filter_mode)
        last_label = self._handoff_action_label(last_key) if last_key else "-"
        last_action_unix: Any = "-"
        last_action_iso = "-"
        try:
            if last_ts:
                parsed_last_ts = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                last_action_unix = int(parsed_last_ts.timestamp())
                last_action_iso = parsed_last_ts.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            last_action_unix = "-"
            last_action_iso = "-"
        if not last_ts:
            last_ts = "-"
        selected = self._selected_admission_id()

        def _keep_item(item_key: str) -> bool:
            key = str(item_key or "").strip().lower()
            if mode == "minimal":
                return "handoff_minimal" in key and "all_in" not in key
            if mode == "all_in":
                return "all_in" in key
            return True

        filtered_history = []
        for item in history:
            item_key = str(item.get("key") or "").strip() if isinstance(item, dict) else ""
            if not _keep_item(item_key):
                continue
            filtered_history.append(item)
        history_limit = STATUS_HISTORY_LIMIT
        history_hidden_count = max(history_limit - len(filtered_history), 0)
        history_window_saturated = 1 if len(filtered_history) >= history_limit else 0
        history_window_utilization_pct = int(round((len(filtered_history) / history_limit) * 100.0)) if history_limit > 0 else 0
        history_metrics_consistent = 1
        if (len(filtered_history) + history_hidden_count) != history_limit:
            history_metrics_consistent = 0
        if history_window_saturated not in (0, 1):
            history_metrics_consistent = 0
        if history_window_utilization_pct < 0 or history_window_utilization_pct > 100:
            history_metrics_consistent = 0

        scope_label = "toate" if mode == "all" else self._handoff_status_filter_label(mode)

        metadata = self._build_handoff_status_metadata_dict(
            compact=compact,
            compact_mode_value=compact_mode_value,
            mode=mode,
            scope_label=scope_label,
            generated_at=generated_at,
            generated_at_iso=generated_at_iso,
            generated_at_unix=generated_at_unix,
            session_date=session_date,
            session_day_of_week=session_day_of_week,
            selected=selected,
            history_limit=history_limit,
            filtered_history=filtered_history,
            history_hidden_count=history_hidden_count,
            history_window_saturated=history_window_saturated,
            history_window_utilization_pct=history_window_utilization_pct,
            history_metrics_consistent=history_metrics_consistent,
            last_key=last_key,
            last_label=last_label,
            last_ts=last_ts,
            last_action_iso=last_action_iso,
            last_action_unix=last_action_unix,
        )

        lines = [
            *STATUS_HEADER_STATIC_LINES,
            *[f"{key}: {value}" for key, value in metadata.items()],
        ]
        lines.append(STATUS_SECTION_SEPARATOR)
        if filtered_history:
            lines.append("Istoric ultimele 5 actiuni:")
            for idx, item in enumerate(filtered_history, start=1):
                item_key = str(item.get("key") or "").strip() if isinstance(item, dict) else ""
                item_ts = str(item.get("ts") or "").strip() if isinstance(item, dict) else ""
                item_label = self._handoff_action_label(item_key) if item_key else "-"
                lines.append(f"{idx}. {item_label} | {item_ts if item_ts else '-'}")
        else:
            lines.append("Istoric ultimele 5 actiuni: fara intrari pentru filtrul selectat.")
        status_line_count = len(lines) + 2
        lines.append(f"StatusLineCount: {status_line_count}")
        checksum_payload = "\n".join(lines)
        status_checksum = hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest()[:16]
        lines.append(f"StatusChecksum: {status_checksum}")
        return lines

    def _build_handoff_status_metadata_dict(
        self,
        *,
        compact: str,
        compact_mode_value: int,
        mode: str,
        scope_label: str,
        generated_at: str,
        generated_at_iso: str,
        generated_at_unix: int,
        session_date: str,
        session_day_of_week: str,
        selected: Optional[int],
        history_limit: int,
        filtered_history: List[Dict[str, str]],
        history_hidden_count: int,
        history_window_saturated: int,
        history_window_utilization_pct: int,
        history_metrics_consistent: int,
        last_key: str,
        last_label: str,
        last_ts: str,
        last_action_iso: str,
        last_action_unix: Any,
    ) -> Dict[str, Any]:
        selected_value = selected if selected else "-"
        metadata: Dict[str, Any] = {
            "CompactMode": compact_mode_value,
            "Handoff compact": compact,
            "FilterMode": mode,
            "FilterModeLabel": self._handoff_status_filter_label(mode),
            "Filtru status": scope_label,
            "Generat la": generated_at,
            "GeneratedAtIso": generated_at_iso,
            "GeneratedAtUnix": generated_at_unix,
            "SessionDate": session_date,
            "SessionDayOfWeek": session_day_of_week,
            "AdmissionID": selected_value,
            "HistoryLimit": history_limit,
            "HistoryOrder": "newest_first",
            "HistoryFiltered": 1 if mode != "all" else 0,
            "HistoryCount": len(filtered_history),
            "HistoryVisibleCount": len(filtered_history),
            "HistoryHiddenCount": history_hidden_count,
            "HistoryWindowSaturated": history_window_saturated,
            "HistoryWindowUtilizationPct": history_window_utilization_pct,
            "HistoryWindowRemaining": history_hidden_count,
            "HistoryMetricsConsistent": history_metrics_consistent,
            "HasHistory": 1 if filtered_history else 0,
            "LastActionKey": last_key if last_key else "-",
            "Ultima actiune": last_label,
            "Timestamp ultima actiune": last_ts,
            "LastActionIso": last_action_iso,
            "LastActionUnix": last_action_unix,
            "Internare selectata": selected_value,
        }
        return metadata

    def _resolve_and_persist_handoff_status_mode(self, filter_mode: Optional[str] = None) -> str:
        raw_mode = filter_mode if filter_mode is not None else getattr(self, "handoff_status_filter_mode", "all")
        mode = self._normalize_handoff_status_filter_mode(raw_mode)
        self.handoff_status_filter_mode = mode
        try:
            self.db.set_setting("HANDOFF_STATUS_FILTER_MODE", mode)
        except Exception:
            pass
        return mode

    def show_handoff_status_popup(self, filter_mode: str = "all") -> None:
        if not self._require_role("Status Handoff FO", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)
        lines = self._build_handoff_status_lines(mode)
        messagebox.showinfo("Status Handoff FO", "\n".join(lines))

    def copy_handoff_status_to_clipboard(self, filter_mode: Optional[str] = None) -> None:
        if not self._require_role("Copiaza status Handoff FO", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)
        lines = self._build_handoff_status_lines(mode)
        payload = "\n".join(lines)
        self._set_clipboard_text(payload)
        mode_label, audit_action = self._handoff_status_mode_audit_context("copy_handoff_status_to_clipboard", mode)
        status_checksum = self._handoff_status_checksum_from_lines(lines)
        self._audit_current_patient(
            audit_action,
            self._handoff_status_audit_details(
                mode=mode,
                mode_label=mode_label,
                line_count=len(lines),
                status_checksum=status_checksum,
            ),
        )
        messagebox.showinfo(
            "Status Handoff FO",
            (
                f"Statusul handoff a fost copiat in clipboard ({mode_label}).\n"
                f"{self._handoff_status_feedback_note(line_count=len(lines), status_checksum=status_checksum)}"
            ),
        )

    def _build_handoff_status_json_payload(self, filter_mode: str = "all") -> Dict[str, Any]:
        mode = self._normalize_handoff_status_filter_mode(filter_mode)
        lines = self._build_handoff_status_lines(mode)
        header_len = len(STATUS_HEADER_STATIC_LINES)

        metadata: Dict[str, Any] = {}
        history: List[Dict[str, Any]] = []
        footer: Dict[str, Any] = {}
        in_history = False

        for line in lines[header_len:]:
            if line == STATUS_SECTION_SEPARATOR:
                in_history = True
                continue

            if in_history:
                if line == "Istoric ultimele 5 actiuni:" or line.startswith("Istoric ultimele 5 actiuni: fara"):
                    continue
                if line.startswith("StatusLineCount:") or line.startswith("StatusChecksum:"):
                    key, value = line.split(":", 1)
                    footer[key.strip()] = value.strip()
                    continue
                match = re.match(r"^(\\d+)\\.\\s+(.*?)\\s+\\|\\s+(.*)$", line)
                if match:
                    history.append(
                        {
                            "index": int(match.group(1)),
                            "actionLabel": match.group(2).strip(),
                            "timestamp": match.group(3).strip(),
                        }
                    )
                continue

            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        return {
            "schema": "handoff_status_json_v1",
            "header": list(STATUS_HEADER_STATIC_LINES),
            "metadata": metadata,
            "sectionSeparator": STATUS_SECTION_SEPARATOR,
            "history": history,
            "footer": footer,
            "lineCount": len(lines),
        }

    def copy_handoff_status_as_json(self, filter_mode: Optional[str] = None) -> None:
        if not self._require_role("Copiaza status Handoff JSON", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)

        payload = self._build_handoff_status_json_payload(mode)
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        self._set_clipboard_text(payload_json)
        mode_label, audit_action = self._handoff_status_mode_audit_context("copy_handoff_status_as_json", mode)
        status_checksum = self._handoff_status_checksum_from_payload(payload)
        line_count = self._handoff_status_line_count_from_payload(payload)
        self._audit_current_patient(
            audit_action,
            self._handoff_status_audit_details(
                mode=mode,
                mode_label=mode_label,
                line_count=line_count,
                status_checksum=status_checksum,
            ),
        )
        messagebox.showinfo(
            "Status Handoff FO",
            (
                f"Statusul handoff JSON a fost copiat in clipboard ({mode_label}).\n"
                f"{self._handoff_status_feedback_note(line_count=line_count, status_checksum=status_checksum)}"
            ),
        )

    def export_handoff_status_json_file(self, filter_mode: Optional[str] = None) -> None:
        if not self._require_role("Export status Handoff JSON", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)

        payload = self._build_handoff_status_json_payload(mode)
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        admission_value = "-"
        if isinstance(metadata, dict):
            admission_value = str(metadata.get("AdmissionID") or "-")
        admission_tag = self._safe_filename(admission_value)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self._safe_filename(f"handoff_status_{mode}_{admission_tag}_{stamp}.json")
        out_path = EXPORTS_DIR / filename
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        mode_label, audit_action = self._handoff_status_mode_audit_context("export_handoff_status_json_file", mode)
        status_checksum = self._handoff_status_checksum_from_payload(payload)
        line_count = self._handoff_status_line_count_from_payload(payload)
        self._audit_current_patient(
            audit_action,
            (
                f"{self._handoff_status_audit_details(mode=mode, mode_label=mode_label, line_count=line_count, status_checksum=status_checksum)}; "
                f"file={out_path.name}"
            ),
        )
        messagebox.showinfo(
            "Status Handoff FO",
            (
                f"Export JSON handoff finalizat ({mode_label}).\n"
                f"Fisier: {out_path.name}\n"
                f"Locatie: {out_path}\n"
                f"{self._handoff_status_feedback_note(line_count=line_count, status_checksum=status_checksum)}"
            ),
        )

    def show_and_copy_handoff_status_json(self, filter_mode: Optional[str] = None) -> None:
        if not self._require_role("Status + Copiaza Handoff JSON", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)

        text_payload = "\n".join(self._build_handoff_status_lines(mode))
        json_payload = self._build_handoff_status_json_payload(mode)
        json_payload_text = json.dumps(json_payload, ensure_ascii=False, indent=2)
        self._set_clipboard_text(json_payload_text)
        mode_label, audit_action = self._handoff_status_mode_audit_context("show_and_copy_handoff_status_json", mode)
        status_checksum = self._handoff_status_checksum_from_payload(json_payload)
        line_count = self._handoff_status_line_count_from_payload(json_payload)
        self._audit_current_patient(
            audit_action,
            self._handoff_status_audit_details(
                mode=mode,
                mode_label=mode_label,
                line_count=line_count,
                status_checksum=status_checksum,
            ),
        )
        messagebox.showinfo(
            "Status Handoff FO",
            (
                f"Clipboard JSON: {mode_label}\n"
                f"{self._handoff_status_feedback_note(line_count=line_count, status_checksum=status_checksum)}\n\n"
                f"{text_payload}"
            ),
        )

    def show_and_copy_handoff_status(self, filter_mode: Optional[str] = None) -> None:
        if not self._require_role("Status + Copiaza Handoff FO", "admin", "medic", "asistent", "receptie"):
            return
        mode = self._resolve_and_persist_handoff_status_mode(filter_mode)
        lines = self._build_handoff_status_lines(mode)
        payload = "\n".join(lines)
        self._set_clipboard_text(payload)
        mode_label, audit_action = self._handoff_status_mode_audit_context("show_and_copy_handoff_status", mode)
        status_checksum = self._handoff_status_checksum_from_lines(lines)
        self._audit_current_patient(
            audit_action,
            self._handoff_status_audit_details(
                mode=mode,
                mode_label=mode_label,
                line_count=len(lines),
                status_checksum=status_checksum,
            ),
        )
        messagebox.showinfo(
            "Status Handoff FO",
            (
                f"Clipboard text: {mode_label}\n"
                f"{self._handoff_status_feedback_note(line_count=len(lines), status_checksum=status_checksum)}\n\n"
                f"{payload}"
            ),
        )

    def _apply_handoff_compact_mode(self) -> None:
        if not hasattr(self, "discharge_actions"):
            return
        managed = getattr(self, "handoff_managed_labels", set())
        keep_enabled = getattr(self, "handoff_compact_keep_enabled", set())
        compact = bool(getattr(self, "handoff_compact_mode", False))
        for widget in self.discharge_actions.winfo_children():
            if not isinstance(widget, ttk.Button):
                continue
            text = str(widget.cget("text") or "")
            if text not in managed:
                continue
            if compact and text not in keep_enabled:
                widget.configure(state="disabled")
            else:
                widget.configure(state="normal")
        if hasattr(self, "handoff_compact_toggle_btn"):
            self.handoff_compact_toggle_btn.configure(
                text=f"Handoff compact: {'ON' if compact else 'OFF'}"
            )

    def toggle_handoff_compact_mode(self) -> None:
        if not self._require_role("Toggle Handoff compact", "admin", "medic", "asistent", "receptie"):
            return
        self.handoff_compact_mode = not bool(getattr(self, "handoff_compact_mode", False))
        self.handoff_compact_mode_default = self.handoff_compact_mode
        self.db.set_setting("HANDOFF_COMPACT_MODE", "1" if self.handoff_compact_mode else "0")
        self._apply_handoff_compact_mode()
        self._audit_current_patient(
            "toggle_handoff_compact_mode",
            self._audit_details_from_pairs(("compact", "on" if self.handoff_compact_mode else "off")),
        )

    def open_exports_folder(self) -> None:
        if not self._require_role("Deschide folder exporturi", "admin", "medic", "asistent", "receptie"):
            return
        try:
            folder = str(EXPORTS_DIR)
            if hasattr(os, "startfile"):
                os.startfile(folder)
            else:
                os.system(f'explorer "{folder}"')
        except Exception as exc:
            messagebox.showerror("Exporturi", f"Nu am putut deschide folderul de exporturi.\n{exc}")
            return
        self._audit_current_patient(
            "open_exports_folder",
            self._audit_details_from_pairs(("folder", EXPORTS_DIR)),
        )

    def _latest_export_artifact(self, pattern: str) -> Optional[Path]:
        candidates = sorted(
            EXPORTS_DIR.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def show_latest_fo_artifacts(self) -> None:
        if not self._require_role("Ultimele artefacte FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Artefacte FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Artefacte FO", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")

        lines = [
            f"MRN: {row.get('mrn') or '-'}",
            f"Pacient: {(row.get('last_name') or '').strip()} {(row.get('first_name') or '').strip()}".strip(),
            "",
        ]

        def _append(label: str, item: Optional[Path]) -> None:
            if not item:
                lines.append(f"- {label}: lipsa")
                return
            stamp = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"- {label}: {item} ({stamp})")

        _append("Raport internare PDF", latest_admission)
        _append("Bilet externare PDF", latest_discharge)
        _append("Checklist FO TXT", latest_checklist)

        found = [p for p in (latest_admission, latest_discharge, latest_checklist) if p]
        if not found:
            messagebox.showinfo("Artefacte FO", "Nu exista artefacte FO exportate pentru internarea selectata.")
            return

        self._audit(
            "view_latest_fo_artifacts",
            self._audit_details_from_pairs(
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
            ),
            int(row["patient_id"]),
        )
        messagebox.showinfo("Ultimele artefacte FO", "\n".join(lines))

    def copy_latest_fo_artifacts_paths(self) -> None:
        if not self._require_role("Copiaza cai artefacte FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Artefacte FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Artefacte FO", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")

        found = [p for p in (latest_admission, latest_discharge, latest_checklist) if p]
        if not found:
            messagebox.showinfo("Artefacte FO", "Nu exista artefacte FO exportate pentru internarea selectata.")
            return

        lines: List[str] = [
            f"MRN: {row.get('mrn') or '-'}",
            f"Pacient: {(row.get('last_name') or '').strip()} {(row.get('first_name') or '').strip()}".strip(),
            "",
        ]
        lines.append(f"Raport internare PDF: {str(latest_admission) if latest_admission else '-'}")
        lines.append(f"Bilet externare PDF: {str(latest_discharge) if latest_discharge else '-'}")
        lines.append(f"Checklist FO TXT: {str(latest_checklist) if latest_checklist else '-'}")

        payload = "\n".join(lines)
        self._set_clipboard_text(payload)

        self._audit(
            "copy_latest_fo_artifacts_paths",
            self._audit_details_from_pairs(
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
            ),
            int(row["patient_id"]),
        )
        messagebox.showinfo("Artefacte FO", "Caile ultimelor artefacte FO au fost copiate in clipboard.")

    def open_latest_fo_zip(self) -> None:
        if not self._require_role("Deschide ultimul FO ZIP", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("FO ZIP", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("FO ZIP", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_zip = self._latest_export_artifact(f"fo_pachet_{mrn_tag}_*.zip")
        if not latest_zip:
            messagebox.showinfo("FO ZIP", "Nu exista arhiva FO ZIP pentru internarea selectata.")
            return

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(latest_zip))
            else:
                os.system(f'explorer "{str(latest_zip)}"')
        except Exception as exc:
            messagebox.showerror("FO ZIP", f"Nu am putut deschide arhiva FO ZIP.\n{exc}")
            return

        self._audit(
            "open_latest_fo_zip",
            self._audit_details_from_pairs(("zip", latest_zip.name)),
            int(row["patient_id"]),
        )

    def open_latest_fo_checklist(self) -> None:
        if not self._require_role("Deschide ultimul checklist FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Checklist FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Checklist FO", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")
        if not latest_checklist:
            messagebox.showinfo("Checklist FO", "Nu exista checklist FO TXT pentru internarea selectata.")
            return

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(latest_checklist))
            else:
                os.system(f'explorer "{str(latest_checklist)}"')
        except Exception as exc:
            messagebox.showerror("Checklist FO", f"Nu am putut deschide checklist-ul FO.\n{exc}")
            return

        self._audit(
            "open_latest_fo_checklist",
            self._audit_details_from_pairs(("checklist", latest_checklist.name)),
            int(row["patient_id"]),
        )

    def open_latest_fo_triplet(self) -> None:
        if not self._require_role("Deschide ultimele 3 artefacte FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Artefacte FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Artefacte FO", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")
        artifacts: List[Tuple[str, Optional[Path]]] = [
            ("admission_pdf", latest_admission),
            ("discharge_pdf", latest_discharge),
            ("checklist", latest_checklist),
        ]
        available = [item for _label, item in artifacts if item is not None]
        if not available:
            messagebox.showinfo("Artefacte FO", "Nu exista artefacte FO exportate pentru internarea selectata.")
            return

        opened: List[str] = []
        for _label, item in artifacts:
            if not item:
                continue
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(item))
                else:
                    os.system(f'explorer "{str(item)}"')
                opened.append(item.name)
            except Exception:
                continue

        if not opened:
            messagebox.showerror("Artefacte FO", "Nu am putut deschide artefactele FO disponibile.")
            return

        self._audit(
            "open_latest_fo_triplet",
            self._audit_details_from_pairs(
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
                ("opened", ",".join(opened)),
            ),
            int(row["patient_id"]),
        )

        missing: List[str] = []
        if not latest_admission:
            missing.append("Raport internare PDF")
        if not latest_discharge:
            missing.append("Bilet externare PDF")
        if not latest_checklist:
            missing.append("Checklist FO TXT")

        if missing:
            messagebox.showinfo(
                "Artefacte FO",
                "Am deschis artefactele disponibile. Lipsesc:\n- " + "\n- ".join(missing),
            )

    def open_latest_fo_all_artifacts(self) -> None:
        if not self._require_role("Deschide toate artefactele FO", "admin", "medic", "asistent", "receptie"):
            return
        admission_id = self._selected_admission_id()
        if not admission_id:
            messagebox.showwarning("Artefacte FO", "Selecteaza internarea.")
            return

        row = self.db.get_admission_for_export(admission_id)
        if not row:
            messagebox.showerror("Artefacte FO", "Internarea nu a fost gasita.")
            return

        mrn_tag = self._safe_filename(str(row.get("mrn") or admission_id))
        latest_admission = self._latest_export_artifact(f"internare_{mrn_tag}_*.pdf")
        latest_discharge = self._latest_export_artifact(f"bilet_externare_{mrn_tag}_*.pdf")
        latest_checklist = self._latest_export_artifact(f"fo_checklist_{mrn_tag}_*.txt")
        latest_zip = self._latest_export_artifact(f"fo_pachet_{mrn_tag}_*.zip")

        artifacts: List[Tuple[str, Optional[Path]]] = [
            ("admission_pdf", latest_admission),
            ("discharge_pdf", latest_discharge),
            ("checklist", latest_checklist),
            ("zip", latest_zip),
        ]
        available = [item for _label, item in artifacts if item is not None]
        if not available:
            messagebox.showinfo("Artefacte FO", "Nu exista artefacte FO exportate pentru internarea selectata.")
            return

        opened: List[str] = []
        for _label, item in artifacts:
            if not item:
                continue
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(item))
                else:
                    os.system(f'explorer "{str(item)}"')
                opened.append(item.name)
            except Exception:
                continue

        if not opened:
            messagebox.showerror("Artefacte FO", "Nu am putut deschide artefactele FO disponibile.")
            return

        self._audit(
            "open_latest_fo_all_artifacts",
            self._audit_details_from_pairs(
                ("admission_pdf", latest_admission.name if latest_admission else "-"),
                ("discharge_pdf", latest_discharge.name if latest_discharge else "-"),
                ("checklist", latest_checklist.name if latest_checklist else "-"),
                ("zip", latest_zip.name if latest_zip else "-"),
                ("opened", ",".join(opened)),
            ),
            int(row["patient_id"]),
        )

        missing: List[str] = []
        if not latest_admission:
            missing.append("Raport internare PDF")
        if not latest_discharge:
            missing.append("Bilet externare PDF")
        if not latest_checklist:
            missing.append("Checklist FO TXT")
        if not latest_zip:
            missing.append("Arhiva FO ZIP")

        if missing:
            messagebox.showinfo(
                "Artefacte FO",
                "Am deschis artefactele disponibile. Lipsesc:\n- " + "\n- ".join(missing),
            )

    def export_dashboard_report_pdf(self) -> None:
        if not self._require_role("Export raport garda PDF", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        kpi = self.db.get_dashboard_kpis(department=department)
        admissions = self.db.list_active_admissions_dashboard(department=department, limit=1000)
        orders = self.db.list_urgent_orders_dashboard(department=department, limit=1000)
        alerts = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=1000)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"raport_garda_{dept_tag}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        section_name = department if department else "Toate sectiile"
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Raport de garda ({section_name})")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Generat la: {now_ts()}")
        y -= 16

        kpi_text = (
            f"Internari active: {kpi['active_admissions']}\n"
            f"Triage 1-2: {kpi['triage_1_2']}\n"
            f"Ordine urgente active: {kpi['urgent_orders']}\n"
            f"Alerte vitale 24h: {kpi['vital_alerts_24h']}"
        )
        y = self._pdf_draw_block(pdf, y, "Indicatori", kpi_text)

        adm_lines = [
            f"{a['mrn']} | {a['last_name']} {a['first_name']} | triage {a['triage_level']} | "
            f"{a['department']} {a['ward']}/{a['bed']} | medic {a['attending_clinician']} | {a['admitted_at']}"
            for a in admissions
        ]
        y = self._pdf_draw_block(pdf, y, "Internari active", "\n".join(adm_lines) if adm_lines else "-")

        ord_lines = [
            f"{o['ordered_at']} | {o['priority']} | {o['last_name']} {o['first_name']} | "
            f"{o['order_type']} | {o['status']} | {o['order_text']}"
            for o in orders
        ]
        y = self._pdf_draw_block(pdf, y, "Ordine urgente", "\n".join(ord_lines) if ord_lines else "-")

        alert_lines = [
            f"{a['recorded_at']} | {a['last_name']} {a['first_name']} | {a.get('mrn') or '-'} | {a['reasons']} | {a.get('notes') or ''}"
            for a in alerts
        ]
        y = self._pdf_draw_block(pdf, y, "Alerte vitale (24h)", "\n".join(alert_lines) if alert_lines else "-")

        signature = self._build_document_signature(
            "raport_garda",
            f"department={section_name}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        y = self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)

        pdf.save()
        self._audit(
            "export_dashboard_pdf",
            self._audit_details_from_pairs(
                ("department", section_name),
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Export PDF", f"Raport de garda exportat:\n{out_path}")

    def export_dashboard_morning_briefing_pdf(self) -> None:
        if not self._require_role("Export Morning Briefing PDF", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        department, on_date = self._resolve_dashboard_filters(persist=True)

        section_name = department or "Toate sectiile"
        kpi = self.db.get_dashboard_kpis(department=department)
        operational_by_dept = self.db.get_operational_by_department(
            date_from=on_date,
            date_to=on_date,
            department=department,
        )
        scheduled_adm = self.db.list_operational_scheduled_bookings(
            booking_type="admission",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        scheduled_dis = self.db.list_operational_scheduled_bookings(
            booking_type="discharge",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        discharged_unbilled = self.db.list_discharged_without_final_decont(
            on_date=on_date,
            department=department,
            limit=5000,
        )

        alert_threshold = max(1, int(getattr(self, "operational_backlog_alert_threshold", 5)))
        warning_threshold = max(1, alert_threshold - 1)

        def _row_status(backlog_value: int) -> str:
            if backlog_value >= alert_threshold:
                return "ALERTA"
            if backlog_value >= warning_threshold:
                return "WARNING"
            return "OK"

        sections_ranked = sorted(
            operational_by_dept,
            key=lambda item: int(item["total"]),
            reverse=True,
        )
        sections_alert = [
            str(row["department"])
            for row in sections_ranked
            if int(row["discharged_without_final_decont"]) >= alert_threshold
        ]

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"morning_briefing_{dept_tag}_{on_date}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Morning Briefing")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Data operationala: {on_date} | Generat la: {now_ts()}")
        y -= 16

        kpi_text = (
            f"Internari active: {kpi['active_admissions']}\n"
            f"Triage 1-2: {kpi['triage_1_2']}\n"
            f"Ordine urgente active: {kpi['urgent_orders']}\n"
            f"Alerte vitale 24h: {kpi['vital_alerts_24h']}\n"
            f"Internari programate azi: {len(scheduled_adm)}\n"
            f"Externari programate azi: {len(scheduled_dis)}\n"
            f"Externati fara decont final azi: {len(discharged_unbilled)}"
        )
        y = self._pdf_draw_block(pdf, y, "KPI briefing", kpi_text)

        if sections_alert:
            summary_text = "Secii in ALERTA backlog: " + ", ".join(sections_alert)
        else:
            summary_text = f"Nu exista sectii in ALERTA backlog (prag {alert_threshold})."
        y = self._pdf_draw_block(
            pdf,
            y,
            "Stare backlog decont final",
            summary_text + f"\nPraguri: ALERTA >= {alert_threshold}, WARNING >= {warning_threshold}",
        )

        section_lines = [
            f"{row['department']} | internari programate {row['scheduled_admissions']} | "
            f"externari programate {row['scheduled_discharges']} | "
            f"externati fara decont final {row['discharged_without_final_decont']} | "
            f"total {row['total']} | status {_row_status(int(row['discharged_without_final_decont']))}"
            for row in sections_ranked
        ]
        y = self._pdf_draw_block(pdf, y, "Top sectii operational", "\n".join(section_lines) if section_lines else "-")

        adm_lines = [
            f"{row['starts_at']} | {row['last_name']} {row['first_name']} | CNP {row['cnp']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']}"
            for row in scheduled_adm
        ]
        y = self._pdf_draw_block(pdf, y, "Internari programate", "\n".join(adm_lines) if adm_lines else "-")

        dis_lines = [
            f"{row['starts_at']} | {row['last_name']} {row['first_name']} | CNP {row['cnp']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']}"
            for row in scheduled_dis
        ]
        y = self._pdf_draw_block(pdf, y, "Externari programate", "\n".join(dis_lines) if dis_lines else "-")

        unbilled_lines = [
            f"{row['discharged_at']} | MRN {row['mrn']} | {row['last_name']} {row['first_name']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']}"
            for row in discharged_unbilled
        ]
        y = self._pdf_draw_block(
            pdf,
            y,
            "Externati fara decont final",
            "\n".join(unbilled_lines) if unbilled_lines else "-",
        )

        signature = self._build_document_signature(
            "morning_briefing",
            f"department={section_name}|date={on_date}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_dashboard_morning_briefing_pdf",
            self._audit_details_from_pairs(
                ("date", on_date),
                ("department", department or "toate"),
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Export PDF", f"Morning Briefing exportat:\n{out_path}")

    def export_dashboard_morning_briefing_csv_bundle(self) -> None:
        if not self._require_role("Export Morning Briefing CSV", "admin", "medic", "asistent", "receptie"):
            return

        department, on_date = self._resolve_dashboard_filters(persist=True)

        section_name = department or "Toate sectiile"
        kpi = self.db.get_dashboard_kpis(department=department)
        operational_by_dept = self.db.get_operational_by_department(
            date_from=on_date,
            date_to=on_date,
            department=department,
        )
        scheduled_adm = self.db.list_operational_scheduled_bookings(
            booking_type="admission",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        scheduled_dis = self.db.list_operational_scheduled_bookings(
            booking_type="discharge",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        discharged_unbilled = self.db.list_discharged_without_final_decont(
            on_date=on_date,
            department=department,
            limit=5000,
        )

        alert_threshold = max(1, int(getattr(self, "operational_backlog_alert_threshold", 5)))
        warning_threshold = max(1, alert_threshold - 1)

        def _row_status(backlog_value: int) -> str:
            if backlog_value >= alert_threshold:
                return "ALERTA"
            if backlog_value >= warning_threshold:
                return "WARNING"
            return "OK"

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        prefix = f"morning_briefing_{dept_tag}_{on_date}_{stamp}"

        index_path = EXPORTS_DIR / f"{prefix}_index.csv"
        kpi_path = EXPORTS_DIR / f"{prefix}_kpi.csv"
        sections_path = EXPORTS_DIR / f"{prefix}_sectii.csv"
        adm_path = EXPORTS_DIR / f"{prefix}_internari_programate.csv"
        dis_path = EXPORTS_DIR / f"{prefix}_externari_programate.csv"
        unbilled_path = EXPORTS_DIR / f"{prefix}_externati_fara_decont_final.csv"

        with index_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["bundle_prefix", "section", "operational_date", "generated_at", "files_count"])
            writer.writerow([prefix, section_name, on_date, now_ts(), "6"])
            writer.writerow([])
            writer.writerow(["file_label", "file_name"])
            writer.writerow(["kpi", kpi_path.name])
            writer.writerow(["sectii", sections_path.name])
            writer.writerow(["internari_programate", adm_path.name])
            writer.writerow(["externari_programate", dis_path.name])
            writer.writerow(["externati_fara_decont_final", unbilled_path.name])

        with kpi_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "section",
                "operational_date",
                "active_admissions",
                "triage_1_2",
                "urgent_orders",
                "vital_alerts_24h",
                "scheduled_admissions_today",
                "scheduled_discharges_today",
                "discharged_without_final_decont_today",
            ])
            writer.writerow([
                section_name,
                on_date,
                int(kpi["active_admissions"]),
                int(kpi["triage_1_2"]),
                int(kpi["urgent_orders"]),
                int(kpi["vital_alerts_24h"]),
                len(scheduled_adm),
                len(scheduled_dis),
                len(discharged_unbilled),
            ])

        with sections_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "department",
                    "scheduled_admissions",
                    "scheduled_discharges",
                    "discharged_without_final_decont",
                    "total",
                    "backlog_status",
                    "backlog_threshold",
                ]
            )
            for row in sorted(operational_by_dept, key=lambda item: int(item["total"]), reverse=True):
                backlog = int(row["discharged_without_final_decont"])
                writer.writerow(
                    [
                        row["department"],
                        row["scheduled_admissions"],
                        row["scheduled_discharges"],
                        backlog,
                        row["total"],
                        _row_status(backlog),
                        alert_threshold,
                    ]
                )

        with adm_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "booking_id",
                    "starts_at",
                    "ends_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                    "notes",
                ]
            )
            for row in scheduled_adm:
                writer.writerow(
                    [
                        row["id"],
                        row["starts_at"],
                        row["ends_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                        row["notes"],
                    ]
                )

        with dis_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "booking_id",
                    "starts_at",
                    "ends_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                    "notes",
                ]
            )
            for row in scheduled_dis:
                writer.writerow(
                    [
                        row["id"],
                        row["starts_at"],
                        row["ends_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                        row["notes"],
                    ]
                )

        with unbilled_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "admission_id",
                    "mrn",
                    "discharged_at",
                    "admitted_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                ]
            )
            for row in discharged_unbilled:
                writer.writerow(
                    [
                        row["admission_id"],
                        row["mrn"],
                        row["discharged_at"],
                        row["admitted_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                    ]
                )

        self._audit(
            "export_dashboard_morning_briefing_csv",
            self._audit_details_from_pairs(
                ("date", on_date),
                ("department", department or "toate"),
                ("index", index_path),
                ("kpi", kpi_path),
                ("sections", sections_path),
                ("admissions", adm_path),
                ("discharges", dis_path),
                ("unbilled", unbilled_path),
            ),
        )
        messagebox.showinfo(
            "Export CSV",
            "Morning Briefing CSV exportat:\n"
            f"{index_path}\n"
            f"{kpi_path}\n"
            f"{sections_path}\n"
            f"{adm_path}\n"
            f"{dis_path}\n"
            f"{unbilled_path}",
        )

    def export_dashboard_handover_shift_pdf(self) -> None:
        if not self._require_role("Export Handover Shift PDF", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        section_name = department or "Toate sectiile"

        active_admissions = self.db.list_active_admissions_dashboard(department=department, limit=5000)
        critical_rows: List[sqlite3.Row] = []
        for row in active_admissions:
            try:
                triage_level = int(row["triage_level"])
            except Exception:
                triage_level = 99
            if triage_level in (1, 2):
                critical_rows.append(row)

        alerts_24h = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=5000)
        vital_ids = [int(item["id"]) for item in alerts_24h if item.get("id") is not None]
        acknowledged_ids = self.db.get_acknowledged_vital_ids(vital_ids) if vital_ids else set()
        unack_alerts = [item for item in alerts_24h if int(item["id"]) not in acknowledged_ids]
        orders = self.db.list_urgent_orders_dashboard(department=department, limit=5000)
        watchlist_rows = self._compute_watchlist_rows(active_admissions, orders, alerts_24h, acknowledged_ids)
        snapshot_ts = self._apply_watchlist_trend(watchlist_rows, department)
        watchlist_by_admission = {int(item["admission_id"]): item for item in watchlist_rows}
        saved_snapshot_rows = self._persist_watchlist_snapshot(watchlist_rows, department, snapshot_ts)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"handover_shift_{dept_tag}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Handover Shift")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Generat la: {now_ts()}")
        y -= 16

        kpi_text = (
            f"Pacienti critici activi (triage 1-2): {len(critical_rows)}\n"
            f"Alerte vitale 24h neconfirmate: {len(unack_alerts)}"
        )
        y = self._pdf_draw_block(pdf, y, "KPI predare tura", kpi_text)

        critical_lines = [
            f"MRN {row['mrn']} | {row['last_name']} {row['first_name']} | triage {row['triage_level']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']} | "
            f"admis {row['admitted_at']} | scor {watchlist_by_admission.get(int(row['id']), {}).get('score', 0)} | "
            f"trend {watchlist_by_admission.get(int(row['id']), {}).get('trend_label', 'NOU')} | "
            f"breakdown {watchlist_by_admission.get(int(row['id']), {}).get('score_breakdown', '-') }"
            for row in critical_rows
        ]
        y = self._pdf_draw_block(
            pdf,
            y,
            "Pacienti critici activi (triage 1-2)",
            "\n".join(critical_lines) if critical_lines else "-",
        )

        alert_lines = [
            f"{item['recorded_at']} | {item['last_name']} {item['first_name']} | {item.get('mrn') or '-'} | "
            f"{item['reasons']} | {item.get('notes') or ''}"
            for item in unack_alerts
        ]
        y = self._pdf_draw_block(
            pdf,
            y,
            "Alerte vitale neconfirmate (24h)",
            "\n".join(alert_lines) if alert_lines else "-",
        )

        signature = self._build_document_signature(
            "handover_shift",
            f"department={section_name}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_dashboard_handover_shift_pdf",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("snapshot_rows", saved_snapshot_rows),
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Export PDF", f"Handover Shift exportat:\n{out_path}")

    def export_dashboard_handover_shift_csv_bundle(self) -> None:
        if not self._require_role("Export Handover Shift CSV", "admin", "medic", "asistent", "receptie"):
            return

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        section_name = department or "Toate sectiile"

        active_admissions = self.db.list_active_admissions_dashboard(department=department, limit=5000)
        critical_rows: List[sqlite3.Row] = []
        for row in active_admissions:
            try:
                triage_level = int(row["triage_level"])
            except Exception:
                triage_level = 99
            if triage_level in (1, 2):
                critical_rows.append(row)

        alerts_24h = self.db.list_vital_alerts_dashboard(department=department, hours=24, limit=5000)
        vital_ids = [int(item["id"]) for item in alerts_24h if item.get("id") is not None]
        acknowledged_ids = self.db.get_acknowledged_vital_ids(vital_ids) if vital_ids else set()
        unack_alerts = [item for item in alerts_24h if int(item["id"]) not in acknowledged_ids]
        orders = self.db.list_urgent_orders_dashboard(department=department, limit=5000)
        watchlist_rows = self._compute_watchlist_rows(active_admissions, orders, alerts_24h, acknowledged_ids)
        snapshot_ts = self._apply_watchlist_trend(watchlist_rows, department)
        watchlist_by_admission = {int(item["admission_id"]): item for item in watchlist_rows}
        saved_snapshot_rows = self._persist_watchlist_snapshot(watchlist_rows, department, snapshot_ts)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        prefix = f"handover_shift_{dept_tag}_{stamp}"

        index_path = EXPORTS_DIR / f"{prefix}_index.csv"
        kpi_path = EXPORTS_DIR / f"{prefix}_kpi.csv"
        critical_path = EXPORTS_DIR / f"{prefix}_pacienti_critici.csv"
        alerts_path = EXPORTS_DIR / f"{prefix}_alerte_neconfirmate.csv"

        with index_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["bundle_prefix", "section", "generated_at", "files_count"])
            writer.writerow([prefix, section_name, now_ts(), "4"])
            writer.writerow([])
            writer.writerow(["file_label", "file_name"])
            writer.writerow(["kpi", kpi_path.name])
            writer.writerow(["pacienti_critici", critical_path.name])
            writer.writerow(["alerte_neconfirmate", alerts_path.name])

        with kpi_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["section", "critical_triage_1_2", "unack_vital_alerts_24h"])
            writer.writerow([section_name, len(critical_rows), len(unack_alerts)])

        with critical_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "admission_id",
                    "patient_id",
                    "mrn",
                    "patient_name",
                    "triage_level",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "watchlist_score",
                    "watchlist_trend",
                    "watchlist_delta",
                    "score_breakdown",
                    "admitted_at",
                ]
            )
            for row in critical_rows:
                score_row = watchlist_by_admission.get(int(row["id"]), {})
                writer.writerow(
                    [
                        row["id"],
                        row["patient_id"],
                        row["mrn"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["triage_level"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        score_row.get("score", 0),
                        score_row.get("trend_label", "NOU"),
                        score_row.get("trend_delta", 0),
                        score_row.get("score_breakdown", ""),
                        row["admitted_at"],
                    ]
                )

        with alerts_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "vital_id",
                    "patient_id",
                    "admission_id",
                    "recorded_at",
                    "patient_name",
                    "mrn",
                    "department",
                    "reasons",
                    "notes",
                ]
            )
            for item in unack_alerts:
                writer.writerow(
                    [
                        item.get("id"),
                        item.get("patient_id"),
                        item.get("admission_id"),
                        item.get("recorded_at"),
                        f"{item.get('last_name', '')} {item.get('first_name', '')}".strip(),
                        item.get("mrn") or "",
                        item.get("department") or "",
                        item.get("reasons") or "",
                        item.get("notes") or "",
                    ]
                )

        self._audit(
            "export_dashboard_handover_shift_csv",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("snapshot_rows", saved_snapshot_rows),
                ("index", index_path),
                ("kpi", kpi_path),
                ("critical", critical_path),
                ("alerts", alerts_path),
            ),
        )
        messagebox.showinfo(
            "Export CSV",
            "Handover Shift CSV exportat:\n"
            f"{index_path}\n"
            f"{kpi_path}\n"
            f"{critical_path}\n"
            f"{alerts_path}",
        )

    def export_dashboard_watchlist_csv(self) -> None:
        if not self._require_role("Export Watchlist CSV", "admin", "medic", "asistent", "receptie"):
            return
        if not self.dashboard_watchlist_map:
            self.refresh_dashboard()
        rows = sorted(
            list(self.dashboard_watchlist_map.values()),
            key=self._watchlist_sort_key,
        )
        if not rows:
            messagebox.showinfo("Watchlist", "Nu exista date in watchlist pentru export.")
            return

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"watchlist_top10_{dept_tag}_{stamp}.csv"
        snapshot_ts = self.dashboard_watchlist_snapshot_ts or now_ts()
        saved_snapshot_rows = self._persist_watchlist_snapshot(rows, department, snapshot_ts)

        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "rank",
                    "score",
                    "admission_id",
                    "patient_id",
                    "mrn",
                    "patient_name",
                    "triage_level",
                    "department",
                    "signals",
                    "score_breakdown",
                    "previous_score",
                    "trend_label",
                    "trend_delta",
                    "admitted_at",
                ]
            )
            for rank, row in enumerate(rows, start=1):
                writer.writerow(
                    [
                        rank,
                        row["score"],
                        row["admission_id"],
                        row["patient_id"],
                        row["mrn"],
                        row["patient_name"],
                        row["triage_level"],
                        row["department"],
                        row["signals"],
                        row.get("score_breakdown", ""),
                        row.get("previous_score", ""),
                        row.get("trend_label", "NOU"),
                        row.get("trend_delta", 0),
                        row["admitted_at"],
                    ]
                )

        self._audit(
            "export_dashboard_watchlist_csv",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("snapshot_rows", saved_snapshot_rows),
                ("file", out_path),
            ),
        )
        messagebox.showinfo("Export CSV", f"Watchlist exportat:\n{out_path}")

    def export_dashboard_watchlist_pdf(self) -> None:
        if not self._require_role("Export Watchlist PDF", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return
        if not self.dashboard_watchlist_map:
            self.refresh_dashboard()
        rows = sorted(
            list(self.dashboard_watchlist_map.values()),
            key=self._watchlist_sort_key,
        )
        if not rows:
            messagebox.showinfo("Watchlist", "Nu exista date in watchlist pentru export.")
            return

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        section_name = department or "Toate sectiile"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"watchlist_top10_{dept_tag}_{stamp}.pdf"
        snapshot_ts = self.dashboard_watchlist_snapshot_ts or now_ts()
        saved_snapshot_rows = self._persist_watchlist_snapshot(rows, department, snapshot_ts)

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Watchlist Top 10 risc")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Generat la: {now_ts()}")
        y -= 16

        lines = [
            f"#{idx} | scor {row['score']} | {row['patient_name']} | MRN {row['mrn']} | "
            f"triage {row['triage_level']} | trend {row.get('trend_label', 'NOU')} | {row['department']} | {row['signals']} | "
            f"breakdown {row.get('score_breakdown', '-') }"
            for idx, row in enumerate(rows, start=1)
        ]
        y = self._pdf_draw_block(pdf, y, "Clasament risc", "\n".join(lines) if lines else "-")

        signature = self._build_document_signature(
            "watchlist_top10",
            f"department={section_name}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_dashboard_watchlist_pdf",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("snapshot_rows", saved_snapshot_rows),
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        messagebox.showinfo("Export PDF", f"Watchlist exportat:\n{out_path}")

    def export_dashboard_watchlist_history_csv(self, *, show_dialog: bool = True) -> Optional[List[Path]]:
        if not self._require_role("Export istoric watchlist CSV", "admin", "medic", "asistent", "receptie"):
            return None

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        section_name = department or "Toate sectiile"
        hours = self._watchlist_history_hours()
        positive_only = self._watchlist_history_positive_only()
        mode_slug = "up" if positive_only else "all"
        mode_text = "Doar cresteri" if positive_only else "Toate"
        snapshots = self.db.list_watchlist_snapshot_runs(department=department, limit=100)
        trends_raw = self.db.get_watchlist_trend_top(department=department, hours=hours, limit=400)
        trends = [row for row in trends_raw if int(row["delta"] or 0) > 0] if positive_only else list(trends_raw)

        if not snapshots and not trends:
            messagebox.showinfo("Istoric watchlist", "Nu exista date de istoric pentru filtrele curente.")
            return None

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        prefix = f"watchlist_istoric_{dept_tag}_{hours}h_{mode_slug}_{stamp}"

        index_path = EXPORTS_DIR / f"{prefix}_index.csv"
        snapshots_path = EXPORTS_DIR / f"{prefix}_snapshot_runs.csv"
        trends_path = EXPORTS_DIR / f"{prefix}_trend_top.csv"

        with index_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["bundle_prefix", "section", "interval_hours", "trend_mode", "generated_at", "files_count"])
            writer.writerow([prefix, section_name, hours, mode_text, now_ts(), "3"])
            writer.writerow([])
            writer.writerow(["file_label", "file_name"])
            writer.writerow(["snapshot_runs", snapshots_path.name])
            writer.writerow(["trend_top", trends_path.name])

        with snapshots_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["snapshot_ts", "rows_count", "max_score", "avg_score"])
            for row in snapshots:
                writer.writerow(
                    [
                        row["snapshot_ts"],
                        row["rows_count"],
                        row["max_score"],
                        row["avg_score"],
                    ]
                )

        with trends_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "admission_id",
                    "patient_id",
                    "mrn",
                    "patient_name",
                    "score_then",
                    "score_now",
                    "delta",
                    "first_ts",
                    "last_ts",
                ]
            )
            for row in trends:
                writer.writerow(
                    [
                        row["admission_id"],
                        row["patient_id"],
                        row["mrn"],
                        f"{(row['last_name'] or '').strip()} {(row['first_name'] or '').strip()}".strip(),
                        row["score_then"],
                        row["score_now"],
                        row["delta"],
                        row["first_ts"],
                        row["last_ts"],
                    ]
                )

        self._audit(
            "export_dashboard_watchlist_history_csv",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("hours", hours),
                ("mode", mode_slug),
                ("index", index_path),
                ("snapshots", snapshots_path),
                ("trends", trends_path),
            ),
        )
        if show_dialog:
            messagebox.showinfo(
                "Export CSV",
                "Istoric watchlist exportat:\n"
                f"{index_path}\n"
                f"{snapshots_path}\n"
                f"{trends_path}",
            )
        return [index_path, snapshots_path, trends_path]

    def export_dashboard_watchlist_history_pdf(self, *, show_dialog: bool = True) -> Optional[Path]:
        if not self._require_role("Export istoric watchlist PDF", "admin", "medic", "asistent", "receptie"):
            return None
        if not self._ensure_pdf_backend():
            return None

        department, _on_date = self._resolve_dashboard_filters(persist=True)
        section_name = department or "Toate sectiile"
        hours = self._watchlist_history_hours()
        positive_only = self._watchlist_history_positive_only()
        mode_slug = "up" if positive_only else "all"
        mode_text = "Doar cresteri" if positive_only else "Toate"
        snapshots = self.db.list_watchlist_snapshot_runs(department=department, limit=100)
        trends_raw = self.db.get_watchlist_trend_top(department=department, hours=hours, limit=400)
        trends = [row for row in trends_raw if int(row["delta"] or 0) > 0] if positive_only else list(trends_raw)

        if not snapshots and not trends:
            messagebox.showinfo("Istoric watchlist", "Nu exista date de istoric pentru filtrele curente.")
            return None

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        out_path = EXPORTS_DIR / f"watchlist_istoric_{dept_tag}_{hours}h_{mode_slug}_{stamp}.pdf"

        pdf = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - Istoric Watchlist")
        y -= 22
        pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"Sectie: {section_name} | Interval: ultimele {hours}h | Trend: {mode_text} | Generat la: {now_ts()}")
        y -= 16

        snapshot_lines = [
            f"{row['snapshot_ts']} | randuri {row['rows_count']} | scor_max {row['max_score']} | scor_mediu {row['avg_score']}"
            for row in snapshots
        ]
        y = self._pdf_draw_block(pdf, y, "Ultime snapshot-uri", "\n".join(snapshot_lines) if snapshot_lines else "-")

        trend_lines = [
            f"delta {row['delta']} | scor {row['score_then']} -> {row['score_now']} | "
            f"MRN {row['mrn']} | {((row['last_name'] or '').strip() + ' ' + (row['first_name'] or '').strip()).strip() or '-'} | "
            f"{row['first_ts']} -> {row['last_ts']}"
            for row in trends
        ]
        y = self._pdf_draw_block(pdf, y, "Trend Top risc", "\n".join(trend_lines) if trend_lines else "-")

        signature = self._build_document_signature(
            "watchlist_history",
            f"department={section_name}|hours={hours}|file={out_path.name}",
        )
        sig_text = (
            f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
            f"Timestamp: {signature['timestamp']}\n"
            f"Hash SHA-256: {signature['hash']}"
        )
        self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
        pdf.save()

        self._audit(
            "export_dashboard_watchlist_history_pdf",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("hours", hours),
                ("mode", mode_slug),
                ("file", out_path),
                ("hash", signature["hash"]),
            ),
        )
        if show_dialog:
            messagebox.showinfo("Export PDF", f"Istoric watchlist exportat:\n{out_path}")
        return out_path

    def export_dashboard_watchlist_history_quick(self) -> None:
        if not self._require_role("Export rapid istoric watchlist", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        started_at = datetime.now()
        department, _on_date = self._resolve_dashboard_filters(persist=True)
        hours = self._watchlist_history_hours()
        positive_only = self._watchlist_history_positive_only()
        mode_slug = "up" if positive_only else "all"
        snapshots = self.db.list_watchlist_snapshot_runs(department=department, limit=100)
        trends_raw = self.db.get_watchlist_trend_top(department=department, hours=hours, limit=400)
        trends = [row for row in trends_raw if int(row["delta"] or 0) > 0] if positive_only else list(trends_raw)

        csv_paths = self.export_dashboard_watchlist_history_csv(show_dialog=False)
        pdf_path = self.export_dashboard_watchlist_history_pdf(show_dialog=False)
        if not csv_paths and not pdf_path:
            return
        elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        files_count = (len(csv_paths) if csv_paths else 0) + (1 if pdf_path else 0)
        self._audit(
            "export_dashboard_watchlist_history_quick",
            self._audit_details_from_pairs(
                ("department", department or "toate"),
                ("hours", hours),
                ("mode", mode_slug),
                ("snapshot_runs", len(snapshots)),
                ("trend_rows", len(trends)),
                ("files", files_count),
                ("duration_ms", elapsed_ms),
            ),
        )
        lines: List[str] = ["Export rapid istoric watchlist finalizat:"]
        if csv_paths:
            lines.append("CSV:")
            lines.extend(str(path) for path in csv_paths)
        if pdf_path:
            lines.append("PDF:")
            lines.append(str(pdf_path))
        lines.append(f"Durata: {elapsed_ms} ms | Snapshot-uri: {len(snapshots)} | Trenduri: {len(trends)}")
        messagebox.showinfo("Export rapid", "\n".join(lines))

    def export_dashboard_operational_lists_csv(self) -> None:
        if not self._require_role("Export liste operationale CSV", "admin", "medic", "asistent", "receptie"):
            return

        department, on_date = self._resolve_dashboard_filters(persist=True)

        scheduled_adm = self.db.list_operational_scheduled_bookings(
            booking_type="admission",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        scheduled_dis = self.db.list_operational_scheduled_bookings(
            booking_type="discharge",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        discharged_unbilled = self.db.list_discharged_without_final_decont(
            on_date=on_date,
            department=department,
            limit=5000,
        )

        if not scheduled_adm and not scheduled_dis and not discharged_unbilled:
            messagebox.showinfo("Export operational", "Nu exista date pentru filtrele selectate.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        adm_path = EXPORTS_DIR / f"operational_internari_programate_{dept_tag}_{on_date}_{stamp}.csv"
        dis_path = EXPORTS_DIR / f"operational_externari_programate_{dept_tag}_{on_date}_{stamp}.csv"
        unbilled_path = EXPORTS_DIR / f"operational_externati_fara_decont_final_{dept_tag}_{on_date}_{stamp}.csv"

        with adm_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "booking_id",
                    "booking_type",
                    "starts_at",
                    "ends_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                    "notes",
                ]
            )
            for row in scheduled_adm:
                writer.writerow(
                    [
                        row["id"],
                        row["booking_type"],
                        row["starts_at"],
                        row["ends_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                        row["notes"],
                    ]
                )

        with dis_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "booking_id",
                    "booking_type",
                    "starts_at",
                    "ends_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                    "notes",
                ]
            )
            for row in scheduled_dis:
                writer.writerow(
                    [
                        row["id"],
                        row["booking_type"],
                        row["starts_at"],
                        row["ends_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                        row["notes"],
                    ]
                )

        with unbilled_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "admission_id",
                    "mrn",
                    "discharged_at",
                    "admitted_at",
                    "department",
                    "ward",
                    "bed",
                    "attending_clinician",
                    "patient_id",
                    "patient_name",
                    "cnp",
                    "phone",
                ]
            )
            for row in discharged_unbilled:
                writer.writerow(
                    [
                        row["admission_id"],
                        row["mrn"],
                        row["discharged_at"],
                        row["admitted_at"],
                        row["department"],
                        row["ward"],
                        row["bed"],
                        row["attending_clinician"],
                        row["patient_id"],
                        f"{row['last_name']} {row['first_name']}".strip(),
                        row["cnp"],
                        row["phone"],
                    ]
                )

        self._audit(
            "export_dashboard_operational_csv",
            self._audit_details_from_pairs(
                ("date", on_date),
                ("department", department or "toate"),
                ("admissions", adm_path),
                ("discharges", dis_path),
                ("unbilled", unbilled_path),
            ),
        )
        messagebox.showinfo(
            "Export operational",
            "Export liste operationale finalizat:\n"
            f"{adm_path}\n"
            f"{dis_path}\n"
            f"{unbilled_path}",
        )

    def export_dashboard_operational_lists_pdf(self) -> None:
        if not self._require_role("Export liste operationale PDF", "admin", "medic", "asistent", "receptie"):
            return
        if not self._ensure_pdf_backend():
            return

        department, on_date = self._resolve_dashboard_filters(persist=True)

        scheduled_adm = self.db.list_operational_scheduled_bookings(
            booking_type="admission",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        scheduled_dis = self.db.list_operational_scheduled_bookings(
            booking_type="discharge",
            on_date=on_date,
            department=department,
            limit=5000,
        )
        discharged_unbilled = self.db.list_discharged_without_final_decont(
            on_date=on_date,
            department=department,
            limit=5000,
        )

        if not scheduled_adm and not scheduled_dis and not discharged_unbilled:
            messagebox.showinfo("Export operational", "Nu exista date pentru filtrele selectate.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dept_tag = self._safe_filename(department or "toate_sectiile")
        section_name = department or "Toate sectiile"
        generated_paths: List[Path] = []

        def _write_pdf(path: Path, title: str, lines: List[str], sig_type: str) -> None:
            pdf = canvas.Canvas(str(path), pagesize=A4)
            width, height = A4
            y = height - 40
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(40, y, f"{DEFAULT_HOSPITAL_NAME} - {title}")
            y -= 22
            pdf.setFont("Helvetica", 10)
            pdf.drawString(40, y, f"Sectie: {section_name}  |  Data: {on_date}  |  Generat la: {now_ts()}")
            y -= 16

            y = self._pdf_draw_block(pdf, y, "Inregistrari", "\n".join(lines) if lines else "-")
            signature = self._build_document_signature(
                sig_type,
                f"department={section_name}|date={on_date}|file={path.name}",
            )
            sig_text = (
                f"Utilizator: {signature['username']} (id {signature['user_id']})\n"
                f"Timestamp: {signature['timestamp']}\n"
                f"Hash SHA-256: {signature['hash']}"
            )
            self._pdf_draw_block(pdf, y, "Semnatura digitala simpla", sig_text, wrap_chars=100)
            pdf.save()
            generated_paths.append(path)

        adm_lines = [
            f"{row['starts_at']} | {row['last_name']} {row['first_name']} | CNP {row['cnp']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']} | "
            f"tel {row['phone']} | {row['notes'] or ''}"
            for row in scheduled_adm
        ]
        adm_path = EXPORTS_DIR / f"operational_internari_programate_{dept_tag}_{on_date}_{stamp}.pdf"
        _write_pdf(adm_path, "Lista internari programate", adm_lines, "operational_internari_programate")

        dis_lines = [
            f"{row['starts_at']} | {row['last_name']} {row['first_name']} | CNP {row['cnp']} | "
            f"{row['department']} {row['ward']}/{row['bed']} | medic {row['attending_clinician']} | "
            f"tel {row['phone']} | {row['notes'] or ''}"
            for row in scheduled_dis
        ]
        dis_path = EXPORTS_DIR / f"operational_externari_programate_{dept_tag}_{on_date}_{stamp}.pdf"
        _write_pdf(dis_path, "Lista externari programate", dis_lines, "operational_externari_programate")

        unbilled_lines = [
            f"{row['discharged_at']} | MRN {row['mrn']} | {row['last_name']} {row['first_name']} | "
            f"CNP {row['cnp']} | {row['department']} {row['ward']}/{row['bed']} | "
            f"medic {row['attending_clinician']} | tel {row['phone']}"
            for row in discharged_unbilled
        ]
        unbilled_path = EXPORTS_DIR / f"operational_externati_fara_decont_final_{dept_tag}_{on_date}_{stamp}.pdf"
        _write_pdf(
            unbilled_path,
            "Lista externati fara decont final",
            unbilled_lines,
            "operational_externati_fara_decont_final",
        )

        self._audit(
            "export_dashboard_operational_pdf",
            self._audit_details_from_pairs(
                ("date", on_date),
                ("department", department or "toate"),
                ("files", ",".join(str(path) for path in generated_paths)),
            ),
        )
        messagebox.showinfo(
            "Export operational",
            "Export liste operationale PDF finalizat:\n" + "\n".join(str(path) for path in generated_paths),
        )

    def _set_chat_text(self, value: str) -> None:
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", END)
        if value:
            self.chat_box.insert("1.0", value)
        self.chat_box.configure(state="disabled")

    def load_chat_history(self) -> None:
        if self.current_patient_id is None:
            self._set_chat_text("")
            return
        rows = self.db.list_ai_messages(self.current_patient_id)
        self._set_chat_text("")
        for row in rows:
            self._append_chat(row["role"], row["content"], row["created_at"])

    def _append_chat(self, role: str, content: str, created_at: Optional[str] = None) -> None:
        stamp = created_at or now_ts()
        role_label = "Tu" if role == "user" else "Asistent"
        self.chat_box.configure(state="normal")
        self.chat_box.insert(END, f"[{stamp}] {role_label}\n{content}\n\n")
        self.chat_box.see(END)
        self.chat_box.configure(state="disabled")

    def _build_patient_context(self, patient: sqlite3.Row, visits: List[sqlite3.Row]) -> str:
        lines = [
            f"Nume: {patient['first_name']} {patient['last_name']}".strip(),
            f"Sex: {patient['gender']}",
            f"Telefon: {patient['phone']}",
            f"Email: {patient['email']}",
            f"Data nasterii: {patient['birth_date']}",
            f"Ocupatie: {patient['occupation']}",
            f"Asigurator: {patient['insurance_provider']}",
            f"Numar asigurare: {patient['insurance_id']}",
            f"Contact urgenta: {patient['emergency_contact_name']} ({patient['emergency_contact_phone']})",
            f"Grupa sanguina: {patient['blood_type']}",
            f"Inaltime: {patient['height_cm']} cm",
            f"Greutate: {patient['weight_kg']} kg",
            f"Istoric medical: {patient['medical_history']}",
            f"Alergii: {patient['allergies']}",
            f"Afectiuni cronice: {patient['chronic_conditions']}",
            f"Tratament curent: {patient['current_medication']}",
            f"Interventii/chirurgii: {patient['surgeries']}",
            f"Antecedente familiale: {patient['family_history']}",
            f"Stil de viata: {patient['lifestyle_notes']}",
        ]

        active_admission = None
        if self.current_patient_id is not None:
            active_admission = self.db.get_active_admission(self.current_patient_id)
        if active_admission:
            lines.append(
                "Internare activa: "
                f"MRN {active_admission['mrn']}, tip {active_admission['admission_type']}, "
                f"triage {active_admission['triage_level']}, sectie {active_admission['department']}, "
                f"salon {active_admission['ward']}, pat {active_admission['bed']}, "
                f"medic curant {active_admission['attending_clinician']}, "
                f"motiv {active_admission['chief_complaint']}"
            )
        else:
            lines.append("Internare activa: NU")

        if self.current_patient_id is not None:
            vitals = self.db.list_vitals(self.current_patient_id, limit=3)
            orders = self.db.list_orders(self.current_patient_id, limit=6)
        else:
            vitals = []
            orders = []

        if vitals:
            lines.append("Vitale recente:")
            for item in vitals:
                lines.append(
                    f"- {item['recorded_at']}: temp {item['temperature_c']} C, "
                    f"TA {item['systolic_bp']}/{item['diastolic_bp']}, puls {item['pulse']}, "
                    f"resp {item['respiratory_rate']}, SpO2 {item['spo2']}, durere {item['pain_score']}"
                )
        if orders:
            lines.append("Ordine medicale recente:")
            for item in orders:
                lines.append(
                    f"- {item['ordered_at']}: {item['order_type']} ({item['priority']}), "
                    f"status {item['status']}, text {item['order_text']}"
                )

        if visits:
            lines.append("Consultatii recente:")
            for idx, visit in enumerate(visits[:5], start=1):
                lines.append(
                    f"{idx}. Data {visit['visit_date']}; motiv: {visit['reason']}; "
                    f"diagnostic: {visit['diagnosis']}; tratament: {visit['treatment']}; "
                    f"note: {visit['notes']}"
                )
        else:
            lines.append("Nu exista consultatii inregistrate.")
        return "\n".join(lines)

    def send_ai_message(self) -> None:
        if self.current_patient_id is None:
            messagebox.showwarning("Fara pacient", "Selecteaza un pacient pentru chat.")
            return
        if self.ai_busy:
            messagebox.showinfo("In lucru", "Un raspuns este deja in procesare.")
            return
        if not self.ai_enabled:
            messagebox.showerror("AI dezactivat", "AI este dezactivat din Setari.")
            return
        if not self._ai_role_allowed():
            messagebox.showerror("AI restrictionat", "Rolul curent nu are acces la AI.")
            return
        if not self.ai.is_available():
            messagebox.showerror("AI indisponibil", self.ai.unavailable_reason())
            return

        user_text = self.ai_prompt.get("1.0", END).strip()
        if not user_text:
            messagebox.showwarning("Mesaj gol", "Scrie un mesaj.")
            return

        patient = self.db.get_patient(self.current_patient_id)
        if not patient:
            messagebox.showerror("Eroare", "Pacientul selectat nu mai exista.")
            return
        visits = self.db.list_visits(self.current_patient_id, limit=10)

        self.db.add_ai_message(self.current_patient_id, "user", user_text)
        self._audit(
            "ai_prompt",
            self._audit_details_from_pairs(
                ("len", len(user_text)),
                ("template", self.ai_template_key or "custom"),
            ),
            self.current_patient_id,
        )
        self._append_chat("user", user_text)
        self.ai_prompt.delete("1.0", END)

        history = self.db.list_ai_messages(self.current_patient_id, limit=self.ai_history_messages)
        context = self._build_patient_context(patient, visits)
        if len(context) > self.ai_context_max_chars:
            context = context[: self.ai_context_max_chars] + "\n[context trunchiat pentru limita de tokeni]"

        self.ai_busy = True
        self.send_btn.configure(state="disabled")
        self.summary_btn.configure(state="disabled")
        self.plan24_btn.configure(state="disabled")
        self.discharge_btn.configure(state="disabled")
        self.alert_explain_btn.configure(state="disabled")

        thread = threading.Thread(
            target=self._ai_worker,
            args=(self.current_patient_id, context, history, user_text),
            daemon=True,
        )
        thread.start()

    def _ai_worker(
        self,
        patient_id: int,
        context: str,
        history: List[sqlite3.Row],
        user_text: str,
    ) -> None:
        try:
            structured = self.ai.generate_structured_reply(context, history, user_text)
            self.root.after(0, lambda: self._on_ai_success(patient_id, structured))
        except Exception as exc:
            self.root.after(0, lambda: self._on_ai_error(str(exc)))

    def _on_ai_success(self, patient_id: int, structured: Dict[str, str]) -> None:
        self.ai_busy = False
        self.send_btn.configure(state="normal")
        self.summary_btn.configure(state="normal")
        self.plan24_btn.configure(state="normal")
        self.discharge_btn.configure(state="normal")
        self.alert_explain_btn.configure(state="normal")

        reply = self._safety_finalize_ai_text(self._format_ai_structured_reply(structured))
        self.db.add_ai_message(patient_id, "assistant", reply)
        self._audit(
            "ai_reply",
            self._audit_details_from_pairs(
                ("len", len(reply)),
                ("template", self.ai_template_key or "custom"),
            ),
            patient_id,
        )
        self.ai_template_key = None
        if self.current_patient_id == patient_id:
            self._append_chat("assistant", reply)

    def _on_ai_error(self, error_text: str) -> None:
        self.ai_busy = False
        self.send_btn.configure(state="normal")
        self.summary_btn.configure(state="normal")
        self.plan24_btn.configure(state="normal")
        self.discharge_btn.configure(state="normal")
        self.alert_explain_btn.configure(state="normal")
        self.ai_template_key = None
        messagebox.showerror("Eroare AI", error_text)

    def generate_summary_prompt(self) -> None:
        self._set_ai_template_prompt(
            "SUMMARY",
            "Genereaza rezumat de garda: situatie, risc, recomandare, monitorizare pe 24h.",
        )
        self.send_ai_message()

    def generate_plan_24h_prompt(self) -> None:
        self._set_ai_template_prompt(
            "PLAN_24H",
            "Genereaza plan clinic pe 24h: investigatii, ordine medicale prioritare, monitorizare si criterii de reevaluare.",
        )
        self.send_ai_message()

    def generate_discharge_draft_prompt(self) -> None:
        self._set_ai_template_prompt(
            "DISCHARGE_DRAFT",
            "Genereaza draft de externare: evolutie, tratament recomandat, semne de alarma, follow-up si instructiuni pacient.",
        )
        self.send_ai_message()

    def explain_latest_alert_prompt(self) -> None:
        alert_context = self._latest_patient_alert_summary()
        self._set_ai_template_prompt(
            "EXPLAIN_ALERT",
            (
                "Explica alerta vitala recenta si impactul clinic imediat. "
                f"Context alerta: {alert_context}"
            ),
        )
        self.send_ai_message()


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    try:
        db = Database(DB_PATH)
        login = LoginDialog(root, db)
        user = login.show()
        if not user:
            root.destroy()
            return

        db.add_audit_log(user.get("id"), None, "login", f"user={user.get('username')}")
        root.deiconify()
        app = PacientiAIApp(root, current_user=user, db=db)
        root.mainloop()
    except Exception as exc:
        details = traceback.format_exc()
        log_path = APP_DIR / "startup_error.log"
        print(details, file=sys.stderr)
        try:
            log_path.write_text(details, encoding="utf-8")
        except Exception:
            pass
        try:
            root.deiconify()
            root.lift()
            try:
                root.attributes("-topmost", True)
                root.after(200, lambda: root.attributes("-topmost", False))
            except Exception:
                pass
            messagebox.showerror(
                "Eroare la pornire",
                f"Aplicatia nu a putut porni: {exc}\n\nDetalii: {log_path}",
            )
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
