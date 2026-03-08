from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .contracts import MedisResult, TransportResult
from .http_client import HttpClient


class MedisClient:
    def __init__(
        self,
        *,
        base_url: str,
        endpoint_order_submit: str,
        endpoint_results_pull: str,
        auth_type: str,
        client_id: str,
        client_secret: str,
        api_key: str,
        bearer_token: str,
        timeout_seconds: int,
        max_retries: int,
        retry_base_seconds: float,
        dry_run: bool = False,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.endpoint_order_submit = (endpoint_order_submit or "").strip()
        self.endpoint_results_pull = (endpoint_results_pull or "").strip()
        self.auth_type = (auth_type or "none").strip().lower()
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.api_key = (api_key or "").strip()
        self.bearer_token = (bearer_token or "").strip()
        self.dry_run = bool(dry_run)
        self.http = HttpClient(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
        )

    def _join_url(self, endpoint: str) -> str:
        target = (endpoint or "").strip()
        if not target:
            return ""
        if target.startswith("http://") or target.startswith("https://"):
            return target
        if not self.base_url:
            return ""
        if target.startswith("/"):
            return f"{self.base_url}{target}"
        return f"{self.base_url}/{target}"

    def _auth_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.auth_type == "bearer":
            if self.bearer_token:
                headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.auth_type == "api_key":
            if self.api_key:
                headers["X-API-Key"] = self.api_key
        elif self.auth_type == "client_credentials":
            if self.client_id:
                headers["X-Client-Id"] = self.client_id
            if self.client_secret:
                headers["X-Client-Secret"] = self.client_secret
        return headers

    @staticmethod
    def _extract_external_reference(payload_text: str) -> str:
        raw = (payload_text or "").strip()
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
        except Exception:
            return ""
        if isinstance(obj, dict):
            for key in ("external_request_id", "request_id", "reference", "id"):
                value = obj.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
        return ""

    def submit_order(
        self,
        payload: Dict[str, Any],
        idempotency_key: str,
        *,
        dry_run: Optional[bool] = None,
    ) -> TransportResult:
        endpoint = self._join_url(self.endpoint_order_submit)
        if not endpoint:
            return TransportResult(
                ok=False,
                http_code=0,
                retriable=False,
                error="Endpoint MEDIS submit lipsa sau invalid.",
            )
        effective_dry_run = self.dry_run if dry_run is None else bool(dry_run)
        headers = self._auth_headers()
        if effective_dry_run:
            headers["X-Dry-Run"] = "1"
        result = self.http.request_json(
            method="POST",
            url=endpoint,
            payload=payload,
            headers=headers,
            idempotency_key=idempotency_key,
        )
        result.endpoint = endpoint
        result.dry_run = bool(effective_dry_run)
        if result.ok:
            result.external_reference = self._extract_external_reference(result.response_payload)
        return result

    @staticmethod
    def _parse_results_payload(raw_payload: str) -> List[MedisResult]:
        text = (raw_payload or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except Exception:
            return []
        records: List[Dict[str, Any]] = []
        if isinstance(payload, list):
            records = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            for key in ("results", "items", "data"):
                val = payload.get(key)
                if isinstance(val, list):
                    records = [item for item in val if isinstance(item, dict)]
                    break

        out: List[MedisResult] = []
        for row in records:
            result_id = str(
                row.get("external_result_id")
                or row.get("result_id")
                or row.get("id")
                or ""
            ).strip()
            ext_req = str(
                row.get("external_request_id")
                or row.get("request_id")
                or row.get("reference")
                or ""
            ).strip()
            summary = str(row.get("result_summary") or row.get("summary") or "").strip()
            flag = str(row.get("result_flag") or row.get("flag") or "").strip().lower()
            received_at = str(row.get("result_received_at") or row.get("received_at") or "").strip()
            payload_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if not result_id and not ext_req:
                continue
            out.append(
                MedisResult(
                    external_result_id=result_id,
                    external_request_id=ext_req,
                    result_summary=summary,
                    result_payload=payload_json,
                    result_flag=flag,
                    result_received_at=received_at,
                )
            )
        return out

    def pull_results(self, since_ts: str, limit: int, *, dry_run: Optional[bool] = None) -> List[MedisResult]:
        endpoint = self._join_url(self.endpoint_results_pull)
        if not endpoint:
            return []
        effective_dry_run = self.dry_run if dry_run is None else bool(dry_run)
        headers = self._auth_headers()
        if effective_dry_run:
            headers["X-Dry-Run"] = "1"
        result = self.http.get_json(
            url=endpoint,
            headers=headers,
            query={
                "since_ts": (since_ts or "").strip(),
                "limit": max(1, int(limit or 100)),
            },
            idempotency_key="",
        )
        if not result.ok:
            return []
        return self._parse_results_payload(result.response_payload)
