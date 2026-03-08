from __future__ import annotations

import json
import random
import socket
import time
from typing import Any, Dict, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .contracts import TransportResult


def _safe_json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class HttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: int = 15,
        max_retries: int = 2,
        retry_base_seconds: float = 1.0,
        jitter_ratio: float = 0.15,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_retries = max(0, int(max_retries))
        self.retry_base_seconds = max(0.05, float(retry_base_seconds))
        self.jitter_ratio = max(0.0, float(jitter_ratio))

    def request_json(
        self,
        *,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: str = "",
    ) -> TransportResult:
        req_method = (method or "POST").strip().upper() or "POST"
        target = (url or "").strip()
        if not target:
            return TransportResult(
                ok=False,
                http_code=0,
                retriable=False,
                error="Endpoint URL gol.",
                endpoint=target,
            )

        req_headers: Dict[str, str] = {"Accept": "application/json"}
        if headers:
            for key, value in headers.items():
                if not key:
                    continue
                req_headers[str(key)] = str(value or "")
        if idempotency_key:
            req_headers.setdefault("Idempotency-Key", idempotency_key.strip())

        body_bytes: Optional[bytes] = None
        if payload is not None:
            req_headers.setdefault("Content-Type", "application/json; charset=utf-8")
            body_bytes = _safe_json_dumps(payload).encode("utf-8")

        last_result = TransportResult(
            ok=False,
            http_code=0,
            retriable=False,
            error="Eroare necunoscuta transport.",
            endpoint=target,
        )

        for attempt in range(self.max_retries + 1):
            try:
                req = urllib_request.Request(target, data=body_bytes, method=req_method)
                for key, value in req_headers.items():
                    req.add_header(key, value)
                with urllib_request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    status = int(getattr(resp, "status", 200) or 200)
                    raw = resp.read()
                    text = raw.decode("utf-8", errors="replace").strip()
                    return TransportResult(
                        ok=True,
                        http_code=status,
                        retriable=False,
                        ack_payload=text,
                        response_payload=text,
                        endpoint=target,
                    )
            except urllib_error.HTTPError as exc:
                status = int(getattr(exc, "code", 0) or 0)
                raw = b""
                try:
                    raw = exc.read() or b""
                except Exception:
                    raw = b""
                text = raw.decode("utf-8", errors="replace").strip()
                retriable = status in {408, 409, 425, 429} or status >= 500
                last_result = TransportResult(
                    ok=False,
                    http_code=status,
                    retriable=retriable,
                    error=f"HTTP {status}",
                    response_payload=text,
                    ack_payload=text,
                    endpoint=target,
                )
            except urllib_error.URLError as exc:
                reason = str(getattr(exc, "reason", "") or str(exc))
                last_result = TransportResult(
                    ok=False,
                    http_code=0,
                    retriable=True,
                    error=f"URLError: {reason}",
                    endpoint=target,
                )
            except socket.timeout:
                last_result = TransportResult(
                    ok=False,
                    http_code=0,
                    retriable=True,
                    error="Timeout transport.",
                    endpoint=target,
                )
            except TimeoutError:
                last_result = TransportResult(
                    ok=False,
                    http_code=0,
                    retriable=True,
                    error="Timeout transport.",
                    endpoint=target,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback
                last_result = TransportResult(
                    ok=False,
                    http_code=0,
                    retriable=True,
                    error=f"Transport exception: {exc}",
                    endpoint=target,
                )

            if attempt >= self.max_retries or not last_result.retriable:
                break
            delay = self.retry_base_seconds * (2**attempt)
            if self.jitter_ratio > 0:
                delay += random.random() * delay * self.jitter_ratio
            time.sleep(max(0.01, delay))

        return last_result

    def get_json(
        self,
        *,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        query: Optional[Dict[str, Any]] = None,
        idempotency_key: str = "",
    ) -> TransportResult:
        target = (url or "").strip()
        query_params = query or {}
        if query_params:
            encoded = urllib_parse.urlencode(
                {str(k): str(v) for k, v in query_params.items() if str(v or "").strip()}
            )
            if encoded:
                sep = "&" if "?" in target else "?"
                target = f"{target}{sep}{encoded}"
        return self.request_json(
            method="GET",
            url=target,
            payload=None,
            headers=headers,
            idempotency_key=idempotency_key,
        )
