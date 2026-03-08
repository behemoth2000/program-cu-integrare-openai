from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TransportResult:
    ok: bool
    http_code: int = 0
    retriable: bool = False
    dry_run: bool = False
    external_reference: str = ""
    ack_payload: str = ""
    error: str = ""
    response_payload: str = ""
    endpoint: str = ""


@dataclass
class MedisResult:
    external_result_id: str
    external_request_id: str
    result_summary: str
    result_payload: str
    result_flag: str
    result_received_at: str


@dataclass
class ProcessSummary:
    processed: int = 0
    success: int = 0
    retriable_failures: int = 0
    permanent_failures: int = 0
    last_error: str = ""
    last_job_id: Optional[int] = None
