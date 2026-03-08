from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Protocol, Tuple

try:  # optional dependency
    import psycopg  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


class DataBackend(Protocol):
    def validate_shadow_target(self) -> Tuple[bool, str]:
        ...

    def write_shadow_event(
        self,
        *,
        action_key: str,
        source: str,
        payload_json: str,
        payload_hash: str,
        created_at: str,
    ) -> Tuple[bool, str]:
        ...

    def write_shadow_row(self, row: Dict[str, Any]) -> Tuple[bool, str]:
        ...


@dataclass
class SqliteBackend:
    """Authoritative backend marker for Val 3A (no-op shadow writer)."""

    def validate_shadow_target(self) -> Tuple[bool, str]:
        return True, "sqlite-authoritative"

    def write_shadow_event(
        self,
        *,
        action_key: str,
        source: str,
        payload_json: str,
        payload_hash: str,
        created_at: str,
    ) -> Tuple[bool, str]:
        _ = action_key, source, payload_json, payload_hash, created_at
        return True, "sqlite-authoritative"

    def write_shadow_row(self, row: Dict[str, Any]) -> Tuple[bool, str]:
        return self.write_shadow_event(
            action_key=str(row.get("action_key") or "").strip(),
            source=str(row.get("source") or "api").strip() or "api",
            payload_json=str(row.get("payload_json") or "").strip(),
            payload_hash=str(row.get("payload_hash") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
        )


@dataclass
class PostgresShadowBackend:
    dsn: str
    connect_timeout_seconds: int = 2

    def validate_shadow_target(self) -> Tuple[bool, str]:
        dsn_text = (self.dsn or "").strip()
        if not dsn_text:
            return False, "PACIENTI_POSTGRES_DSN lipseste pentru shadow mode."
        if psycopg is None:
            return False, "psycopg nu este instalat pentru shadow mode."
        return True, ""

    def is_enabled(self) -> bool:
        ready, _ = self.validate_shadow_target()
        return bool(ready)

    def write_shadow_event(
        self,
        *,
        action_key: str,
        source: str,
        payload_json: str,
        payload_hash: str,
        created_at: str,
    ) -> Tuple[bool, str]:
        ready, reason = self.validate_shadow_target()
        if not ready:
            return False, reason
        try:
            with psycopg.connect((self.dsn or "").strip(), connect_timeout=max(1, int(self.connect_timeout_seconds or 2))) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS shadow_write_events (
                            id BIGSERIAL PRIMARY KEY,
                            action_key TEXT NOT NULL,
                            source TEXT NOT NULL DEFAULT '',
                            payload_json TEXT NOT NULL DEFAULT '',
                            payload_hash TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO shadow_write_events (
                            action_key, source, payload_json, payload_hash, created_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            (action_key or "").strip(),
                            (source or "").strip() or "api",
                            (payload_json or "").strip(),
                            (payload_hash or "").strip(),
                            (created_at or "").strip(),
                        ),
                    )
                conn.commit()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def write_shadow_row(self, row: Dict[str, Any]) -> Tuple[bool, str]:
        return self.write_shadow_event(
            action_key=str(row.get("action_key") or "").strip(),
            source=str(row.get("source") or "api_middleware").strip() or "api_middleware",
            payload_json=str(row.get("payload_json") or "").strip(),
            payload_hash=str(row.get("payload_hash") or "").strip(),
            created_at=str(row.get("created_at") or "").strip(),
        )

    @staticmethod
    def json_payload(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class ShadowSyncDatabase(Protocol):
    def process_shadow_sync_jobs(
        self,
        *,
        max_jobs: int,
        max_retries: int,
        stop_on_error_rate: float,
        processor: Callable[[Dict[str, Any]], Tuple[bool, str]],
    ) -> Dict[str, Any]:
        ...


def build_shadow_processor(backend: DataBackend) -> Callable[[Dict[str, Any]], Tuple[bool, str]]:
    def _processor(row: Dict[str, Any]) -> Tuple[bool, str]:
        return backend.write_shadow_row(dict(row or {}))

    return _processor


def process_shadow_sync_with_backend(
    *,
    db: ShadowSyncDatabase,
    backend: DataBackend,
    max_jobs: int,
    max_retries: int,
    stop_on_error_rate: float,
) -> Dict[str, Any]:
    summary = db.process_shadow_sync_jobs(
        max_jobs=max(1, int(max_jobs or 1)),
        max_retries=max(0, int(max_retries or 0)),
        stop_on_error_rate=max(0.0, min(1.0, float(stop_on_error_rate or 0.0))),
        processor=build_shadow_processor(backend),
    )
    ready, reason = backend.validate_shadow_target()
    summary["shadow_backend_ready"] = bool(ready)
    summary["shadow_backend_reason"] = str(reason or "")
    return summary
