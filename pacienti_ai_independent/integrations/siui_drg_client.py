from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .contracts import TransportResult
from .http_client import HttpClient


class SiuiDrgClient:
    def __init__(
        self,
        *,
        base_url: str,
        endpoint_siui_submit: str,
        endpoint_drg_submit: str,
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
        self.endpoint_siui_submit = (endpoint_siui_submit or "").strip()
        self.endpoint_drg_submit = (endpoint_drg_submit or "").strip()
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

    def _endpoint_for_report_type(self, report_type: str) -> str:
        kind = (report_type or "").strip().lower()
        if kind == "siui":
            endpoint = self.endpoint_siui_submit
        elif kind == "drg":
            endpoint = self.endpoint_drg_submit
        else:
            endpoint = ""
        endpoint = endpoint.strip()
        if not endpoint:
            return ""
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        if not self.base_url:
            return ""
        if endpoint.startswith("/"):
            return f"{self.base_url}{endpoint}"
        return f"{self.base_url}/{endpoint}"

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
            for key in (
                "external_reference",
                "reference",
                "reference_id",
                "request_id",
                "id",
                "ack_id",
            ):
                val = obj.get(key)
                if val is None:
                    continue
                text = str(val).strip()
                if text:
                    return text
        return ""

    def submit_report(
        self,
        report_type: str,
        payload: Dict[str, Any],
        idempotency_key: str,
        *,
        dry_run: Optional[bool] = None,
    ) -> TransportResult:
        endpoint = self._endpoint_for_report_type(report_type)
        if not endpoint:
            return TransportResult(
                ok=False,
                http_code=0,
                retriable=False,
                error="Endpoint SIUI/DRG lipsa sau invalid.",
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
