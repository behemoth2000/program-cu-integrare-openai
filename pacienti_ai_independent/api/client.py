from __future__ import annotations

import json
import urllib.error
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional
from urllib import request as urllib_request

try:
    from pacienti_ai_independent.observability import get_correlation_id, set_correlation_id
except Exception:  # pragma: no cover - fallback defensive for isolated runtime
    def get_correlation_id() -> str:
        return ""

    def set_correlation_id(value: str) -> None:
        _ = value


class EnterpriseApiClient:
    def __init__(
        self,
        *,
        base_url: str = "",
        timeout_seconds: int = 8,
        enabled: bool = False,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 8))
        self.enabled = bool(enabled)
        self.user_id: Optional[int] = None
        self.role = "admin"

    def configure(self, *, base_url: str, timeout_seconds: int, enabled: bool) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 8))
        self.enabled = bool(enabled)

    def set_actor(self, *, user_id: Optional[int], role: str) -> None:
        self.user_id = int(user_id) if user_id else None
        self.role = (role or "").strip().lower() or "admin"

    def is_ready(self) -> bool:
        return bool(self.enabled and self.base_url)

    def is_localhost_target(self) -> bool:
        url = (self.base_url or "").strip().lower()
        return url.startswith("http://127.0.0.1") or url.startswith("https://127.0.0.1") or url.startswith(
            "http://localhost"
        ) or url.startswith("https://localhost")

    @staticmethod
    def _extract_error_message(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return "Cerere API esuata."
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, str) and detail.strip():
                    return detail.strip()
        except Exception:
            pass
        return text

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: str = "",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not self.is_ready():
            raise RuntimeError("API intern indisponibil.")
        url = f"{self.base_url}{path}"
        body = None
        headers = {
            "Accept": "application/json",
            "X-Role": self.role or "admin",
            "X-Correlation-Id": self._ensure_correlation_id(),
        }
        if self.user_id:
            headers["X-User-Id"] = str(self.user_id)
        idem = (idempotency_key or "").strip()
        if idem:
            headers["Idempotency-Key"] = idem
        if extra_headers:
            for key, value in extra_headers.items():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k and v:
                    headers[k] = v
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib_request.Request(url=url, data=body, method=(method or "GET").upper())
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = ""
            try:
                raw = exc.read().decode("utf-8", errors="replace")
            except Exception:
                raw = str(exc)
            detail = self._extract_error_message(raw)
            raise RuntimeError(f"API HTTP {int(exc.code)}: {detail}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API indisponibil: {exc}")
        except Exception as exc:
            raise RuntimeError(f"Eroare transport API: {exc}")
        try:
            obj = json.loads(raw) if raw.strip() else {}
        except Exception:
            raise RuntimeError("Raspuns API invalid (JSON).")
        if not isinstance(obj, dict):
            raise RuntimeError("Raspuns API invalid.")
        return obj

    @staticmethod
    def _ensure_correlation_id() -> str:
        corr = str(get_correlation_id() or "").strip()
        if corr:
            return corr
        generated = uuid.uuid4().hex
        try:
            set_correlation_id(generated)
        except Exception:
            pass
        return generated

    def diagnosis_suggestions(self, *, patient_id: int, idempotency_key: str = "") -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/diagnosis-suggestions",
            idempotency_key=(idempotency_key or "").strip(),
        )
        rows = resp.get("suggestions")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "code": str(row.get("code") or "").strip().upper(),
                    "title": str(row.get("title") or "").strip(),
                    "severity": str(row.get("severity") or "none").strip() or "none",
                    "confidence": float(row.get("confidence") or 0.0),
                    "evidence": str(row.get("evidence") or "").strip(),
                }
            )
        return [row for row in out if row.get("code")]

    def get_patient(self, *, patient_id: int) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        return self._request_json(
            method="GET",
            path=f"/api/v1/patients/{pid}",
        )

    def list_patient_timeline(
        self,
        *,
        patient_id: int,
        limit: int = 500,
        category: str = "",
        event_type: str = "",
        date_from: str = "",
        date_to: str = "",
        admission_id: int = 0,
    ) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (category or "").strip():
            query_payload["category"] = str(category).strip()
        if (event_type or "").strip():
            query_payload["event_type"] = str(event_type).strip()
        if (date_from or "").strip():
            query_payload["date_from"] = str(date_from).strip()
        if (date_to or "").strip():
            query_payload["date_to"] = str(date_to).strip()
        if int(admission_id or 0) > 0:
            query_payload["admission_id"] = str(int(admission_id))
        query = urllib.parse.urlencode(query_payload)
        path = f"/api/v1/patients/{pid}/timeline"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "event_id": str(row.get("event_id") or "").strip(),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "event_type": str(row.get("event_type") or "").strip(),
                    "category": str(row.get("category") or "").strip(),
                    "occurred_at": str(row.get("occurred_at") or "").strip(),
                    "actor_user_id": int(row.get("actor_user_id") or 0),
                    "actor_name": str(row.get("actor_name") or "").strip(),
                    "title": str(row.get("title") or "").strip(),
                    "summary": str(row.get("summary") or ""),
                    "payload_json": str(row.get("payload_json") or ""),
                }
            )
        return [item for item in out if item.get("event_id")]

    def list_patient_snapshots(self, *, patient_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/patients/{pid}/snapshots"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "version_no": int(row.get("version_no") or 0),
                    "trigger_action": str(row.get("trigger_action") or "").strip(),
                    "trigger_source": str(row.get("trigger_source") or "").strip(),
                    "trigger_ref_id": str(row.get("trigger_ref_id") or "").strip(),
                    "snapshot_json": str(row.get("snapshot_json") or ""),
                    "changed_fields_json": str(row.get("changed_fields_json") or ""),
                    "snapshot_hash": str(row.get("snapshot_hash") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "created_by_user_id": int(row.get("created_by_user_id") or 0),
                    "created_by_username": str(row.get("created_by_username") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def get_patient_snapshot(self, *, patient_id: int, snapshot_id: int) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        sid = int(snapshot_id or 0)
        if pid <= 0 or sid <= 0:
            raise ValueError("patient_id/snapshot_id invalid.")
        resp = self._request_json(
            method="GET",
            path=f"/api/v1/patients/{pid}/snapshots/{sid}",
        )
        return {
            "id": int(resp.get("id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "version_no": int(resp.get("version_no") or 0),
            "trigger_action": str(resp.get("trigger_action") or "").strip(),
            "trigger_source": str(resp.get("trigger_source") or "").strip(),
            "trigger_ref_id": str(resp.get("trigger_ref_id") or "").strip(),
            "snapshot_json": str(resp.get("snapshot_json") or ""),
            "changed_fields_json": str(resp.get("changed_fields_json") or ""),
            "snapshot_hash": str(resp.get("snapshot_hash") or "").strip(),
            "created_at": str(resp.get("created_at") or "").strip(),
            "created_by_user_id": int(resp.get("created_by_user_id") or 0),
            "created_by_username": str(resp.get("created_by_username") or "").strip(),
        }

    def get_patient_snapshot_diff(self, *, patient_id: int, snapshot_id: int) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        sid = int(snapshot_id or 0)
        if pid <= 0 or sid <= 0:
            raise ValueError("patient_id/snapshot_id invalid.")
        resp = self._request_json(
            method="GET",
            path=f"/api/v1/patients/{pid}/snapshots/{sid}/diff",
        )
        changed_fields_raw = resp.get("changed_fields")
        changed_fields = [str(item).strip() for item in changed_fields_raw if str(item).strip()] if isinstance(changed_fields_raw, list) else []
        return {
            "patient_id": int(resp.get("patient_id") or 0),
            "from_snapshot_id": int(resp.get("from_snapshot_id") or 0),
            "to_snapshot_id": int(resp.get("to_snapshot_id") or 0),
            "changed_fields": changed_fields,
            "from_snapshot_created_at": str(resp.get("from_snapshot_created_at") or "").strip(),
            "to_snapshot_created_at": str(resp.get("to_snapshot_created_at") or "").strip(),
            "diff_json": str(resp.get("diff_json") or ""),
        }

    def restore_patient_snapshot(
        self,
        *,
        patient_id: int,
        snapshot_id: int,
        reason: str = "",
        expected_updated_at: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        sid = int(snapshot_id or 0)
        if pid <= 0 or sid <= 0:
            raise ValueError("patient_id/snapshot_id invalid.")
        payload = {"reason": str(reason or "").strip()}
        expected = str(expected_updated_at or "").strip()
        if expected:
            payload["expected_updated_at"] = expected
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/snapshots/{sid}/restore",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "ok": bool(resp.get("ok", False)),
            "patient_id": int(resp.get("patient_id") or 0),
            "restored_snapshot_id": int(resp.get("restored_snapshot_id") or 0),
            "backup_snapshot_id": int(resp.get("backup_snapshot_id") or 0),
            "post_snapshot_id": int(resp.get("post_snapshot_id") or 0),
            "restored_at": str(resp.get("restored_at") or "").strip(),
        }

    def list_patients(self, *, search: str = "", status_filter: str = "all", status_date: str = "") -> List[Dict[str, Any]]:
        params = {
            "search": (search or "").strip(),
            "status_filter": (status_filter or "all").strip() or "all",
            "status_date": (status_date or "").strip(),
        }
        query = urllib.parse.urlencode(params)
        path = "/api/v1/patients"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "first_name": str(row.get("first_name") or "").strip(),
                    "last_name": str(row.get("last_name") or "").strip(),
                    "phone": str(row.get("phone") or "").strip(),
                    "email": str(row.get("email") or "").strip(),
                    "reception_flag": str(row.get("reception_flag") or "-").strip() or "-",
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def get_dashboard_kpis(self, *, department: str = "") -> Dict[str, int]:
        query_payload: Dict[str, str] = {}
        if (department or "").strip():
            query_payload["department"] = str(department).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/dashboard/kpis"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        row = resp.get("kpi")
        if not isinstance(row, dict):
            row = resp
        return {
            "active_admissions": int(row.get("active_admissions") or 0),
            "triage_1_2": int(row.get("triage_1_2") or 0),
            "urgent_orders": int(row.get("urgent_orders") or 0),
            "vital_alerts_24h": int(row.get("vital_alerts_24h") or 0),
        }

    def list_dashboard_active_admissions(self, *, department: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (department or "").strip():
            query_payload["department"] = str(department).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/dashboard/active-admissions"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "mrn": str(row.get("mrn") or "").strip(),
                    "admission_type": str(row.get("admission_type") or "").strip(),
                    "triage_level": str(row.get("triage_level") or "").strip(),
                    "department": str(row.get("department") or "").strip(),
                    "ward": str(row.get("ward") or "").strip(),
                    "bed": str(row.get("bed") or "").strip(),
                    "attending_clinician": str(row.get("attending_clinician") or "").strip(),
                    "chief_complaint": str(row.get("chief_complaint") or "").strip(),
                    "admitted_at": str(row.get("admitted_at") or "").strip(),
                    "first_name": str(row.get("first_name") or "").strip(),
                    "last_name": str(row.get("last_name") or "").strip(),
                    "cnp": str(row.get("cnp") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_dashboard_urgent_orders(self, *, department: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (department or "").strip():
            query_payload["department"] = str(department).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/dashboard/urgent-orders"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "order_type": str(row.get("order_type") or "").strip(),
                    "priority": str(row.get("priority") or "").strip(),
                    "status": str(row.get("status") or "").strip(),
                    "ordered_at": str(row.get("ordered_at") or "").strip(),
                    "order_text": str(row.get("order_text") or ""),
                    "mrn": str(row.get("mrn") or "").strip(),
                    "department": str(row.get("department") or "").strip(),
                    "first_name": str(row.get("first_name") or "").strip(),
                    "last_name": str(row.get("last_name") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_dashboard_vital_alerts(
        self,
        *,
        department: str = "",
        hours: int = 24,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {
            "hours": str(max(1, int(hours))),
            "limit": str(max(1, int(limit))),
        }
        if (department or "").strip():
            query_payload["department"] = str(department).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/dashboard/vital-alerts"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "recorded_at": str(row.get("recorded_at") or "").strip(),
                    "temperature_c": str(row.get("temperature_c") or "").strip(),
                    "systolic_bp": str(row.get("systolic_bp") or "").strip(),
                    "diastolic_bp": str(row.get("diastolic_bp") or "").strip(),
                    "pulse": str(row.get("pulse") or "").strip(),
                    "respiratory_rate": str(row.get("respiratory_rate") or "").strip(),
                    "spo2": str(row.get("spo2") or "").strip(),
                    "pain_score": str(row.get("pain_score") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "mrn": str(row.get("mrn") or "").strip(),
                    "department": str(row.get("department") or "").strip(),
                    "first_name": str(row.get("first_name") or "").strip(),
                    "last_name": str(row.get("last_name") or "").strip(),
                    "reasons": str(row.get("reasons") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_admissions(self, *, patient_id: int, include_closed: bool = True, limit: int = 200) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        params = {
            "include_closed": "1" if bool(include_closed) else "0",
            "limit": str(max(1, int(limit))),
        }
        query = urllib.parse.urlencode(params)
        path = f"/api/v1/patients/{pid}/admissions"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "mrn": str(row.get("mrn") or "").strip(),
                    "admission_type": str(row.get("admission_type") or "").strip(),
                    "triage_level": str(row.get("triage_level") or "").strip(),
                    "department": str(row.get("department") or "").strip(),
                    "ward": str(row.get("ward") or "").strip(),
                    "bed": str(row.get("bed") or "").strip(),
                    "attending_clinician": str(row.get("attending_clinician") or "").strip(),
                    "chief_complaint": str(row.get("chief_complaint") or "").strip(),
                    "status": str(row.get("status") or "").strip(),
                    "admitted_at": str(row.get("admitted_at") or "").strip(),
                    "discharged_at": str(row.get("discharged_at") or "").strip(),
                    "discharge_summary": str(row.get("discharge_summary") or "").strip(),
                    "case_finalized_at": str(row.get("case_finalized_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_admission(
        self,
        *,
        patient_id: int,
        payload: Dict[str, Any],
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        body = {
            "admission_type": str(payload.get("admission_type") or "").strip(),
            "triage_level": str(payload.get("triage_level") or "").strip(),
            "department": str(payload.get("department") or "").strip(),
            "ward": str(payload.get("ward") or "").strip(),
            "bed": str(payload.get("bed") or "").strip(),
            "attending_clinician": str(payload.get("attending_clinician") or "").strip(),
            "chief_complaint": str(payload.get("chief_complaint") or "").strip(),
            "admitted_at": str(payload.get("admitted_at") or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/admissions",
            payload=body,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "mrn": str(resp.get("mrn") or "").strip(),
            "status": str(resp.get("status") or "").strip(),
            "admitted_at": str(resp.get("admitted_at") or "").strip(),
            "completed_booking_id": int(resp.get("completed_booking_id") or 0),
        }

    def discharge_admission(
        self,
        *,
        admission_id: int,
        discharge_summary: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/discharge",
            payload={"discharge_summary": str(discharge_summary or "").strip()},
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "booking_id": int(resp.get("booking_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "discharged_at": str(resp.get("discharged_at") or "").strip(),
            "discharge_summary": str(resp.get("discharge_summary") or "").strip(),
        }

    def get_active_admission(self, *, patient_id: int) -> Optional[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        resp = self._request_json(
            method="GET",
            path=f"/api/v1/patients/{pid}/admissions/active",
        )
        item = resp.get("item")
        if not isinstance(item, dict):
            return None
        normalized = {
            "id": int(item.get("id") or 0),
            "mrn": str(item.get("mrn") or "").strip(),
            "admission_type": str(item.get("admission_type") or "").strip(),
            "triage_level": str(item.get("triage_level") or "").strip(),
            "department": str(item.get("department") or "").strip(),
            "ward": str(item.get("ward") or "").strip(),
            "bed": str(item.get("bed") or "").strip(),
            "attending_clinician": str(item.get("attending_clinician") or "").strip(),
            "chief_complaint": str(item.get("chief_complaint") or "").strip(),
            "status": str(item.get("status") or "").strip(),
            "admitted_at": str(item.get("admitted_at") or "").strip(),
            "discharged_at": str(item.get("discharged_at") or "").strip(),
            "discharge_summary": str(item.get("discharge_summary") or "").strip(),
            "case_finalized_at": str(item.get("case_finalized_at") or "").strip(),
        }
        if int(normalized["id"] or 0) <= 0:
            return None
        return normalized

    def list_admission_transfers(self, *, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/transfers"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "action_type": str(row.get("action_type") or "").strip(),
                    "from_department": str(row.get("from_department") or "").strip(),
                    "from_ward": str(row.get("from_ward") or "").strip(),
                    "from_bed": str(row.get("from_bed") or "").strip(),
                    "to_department": str(row.get("to_department") or "").strip(),
                    "to_ward": str(row.get("to_ward") or "").strip(),
                    "to_bed": str(row.get("to_bed") or "").strip(),
                    "notes": str(row.get("notes") or "").strip(),
                    "transferred_at": str(row.get("transferred_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def transfer_admission(
        self,
        *,
        admission_id: int,
        to_department: str,
        to_ward: str,
        to_bed: str,
        transferred_at: str = "",
        notes: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload = {
            "to_department": str(to_department or "").strip(),
            "to_ward": str(to_ward or "").strip(),
            "to_bed": str(to_bed or "").strip(),
            "transferred_at": str(transferred_at or "").strip(),
            "notes": str(notes or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/transfer",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "department": str(resp.get("department") or "").strip(),
            "ward": str(resp.get("ward") or "").strip(),
            "bed": str(resp.get("bed") or "").strip(),
            "transferred_at": str(resp.get("transferred_at") or "").strip(),
        }

    def get_admission_case_validation(
        self,
        *,
        admission_id: int,
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        params = {
            "require_financial_closure": "1" if bool(require_financial_closure) else "0",
            "require_siui_drg_submission": "1" if bool(require_siui_drg_submission) else "0",
        }
        query = urllib.parse.urlencode(params)
        path = f"/api/v1/admissions/{aid}/case-validation"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        errors_raw = resp.get("errors")
        errors = [str(item).strip() for item in errors_raw if str(item).strip()] if isinstance(errors_raw, list) else []
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "eligible": bool(resp.get("eligible", False)),
            "errors": errors,
            "finalized": bool(resp.get("finalized", False)),
            "finalized_at": str(resp.get("finalized_at") or "").strip(),
        }

    def save_admission_diagnoses(
        self,
        *,
        admission_id: int,
        payload: Dict[str, Any],
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        body = {
            "referral_diagnosis": str(payload.get("referral_diagnosis") or "").strip(),
            "admission_diagnosis": str(payload.get("admission_diagnosis") or "").strip(),
            "discharge_diagnosis": str(payload.get("discharge_diagnosis") or "").strip(),
            "secondary_diagnoses": str(payload.get("secondary_diagnoses") or "").strip(),
            "dietary_regimen": str(payload.get("dietary_regimen") or "").strip(),
            "admission_criteria": str(payload.get("admission_criteria") or "").strip(),
            "discharge_criteria": str(payload.get("discharge_criteria") or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/diagnoses",
            payload=body,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "updated_at": str(resp.get("updated_at") or "").strip(),
            "updated_by_user_id": int(resp.get("updated_by_user_id") or 0),
        }

    def finalize_admission_case(
        self,
        *,
        admission_id: int,
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload = {
            "require_financial_closure": bool(require_financial_closure),
            "require_siui_drg_submission": bool(require_siui_drg_submission),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/finalize-case",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "admission_id": int(resp.get("admission_id") or 0),
            "finalized": bool(resp.get("finalized", False)),
            "finalized_at": str(resp.get("finalized_at") or "").strip(),
        }

    def issue_billing_record(
        self,
        *,
        admission_id: int,
        record_type: str,
        amount: float,
        issued_at: str = "",
        notes: str = "",
        cost_center_id: Optional[int] = None,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload: Dict[str, Any] = {
            "record_type": str(record_type or "").strip(),
            "amount": float(amount or 0.0),
            "issued_at": str(issued_at or "").strip(),
            "notes": str(notes or "").strip(),
            "cost_center_id": int(cost_center_id) if cost_center_id else None,
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/billing-records",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "billing_id": int(resp.get("billing_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "record_type": str(resp.get("record_type") or "").strip(),
            "amount": float(resp.get("amount") or 0.0),
            "currency": str(resp.get("currency") or "RON").strip() or "RON",
            "issued_at": str(resp.get("issued_at") or "").strip(),
            "status": str(resp.get("status") or "").strip(),
            "cost_center_id": int(resp.get("cost_center_id") or 0),
        }

    def issue_case_invoice(
        self,
        *,
        admission_id: int,
        invoice_type: str,
        series: str,
        invoice_number: str,
        subtotal: float,
        tax_amount: float,
        total_amount: Optional[float] = None,
        issued_at: str = "",
        due_date: str = "",
        status: str = "issued",
        notes: str = "",
        partner_id: Optional[int] = None,
        cost_center_id: Optional[int] = None,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload: Dict[str, Any] = {
            "invoice_type": str(invoice_type or "").strip(),
            "series": str(series or "").strip(),
            "invoice_number": str(invoice_number or "").strip(),
            "subtotal": float(subtotal or 0.0),
            "tax_amount": float(tax_amount or 0.0),
            "total_amount": float(total_amount) if total_amount is not None else None,
            "issued_at": str(issued_at or "").strip(),
            "due_date": str(due_date or "").strip(),
            "status": str(status or "").strip(),
            "notes": str(notes or "").strip(),
            "partner_id": int(partner_id) if partner_id else None,
            "cost_center_id": int(cost_center_id) if cost_center_id else None,
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/case-invoices",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "invoice_id": int(resp.get("invoice_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "invoice_type": str(resp.get("invoice_type") or "").strip(),
            "series": str(resp.get("series") or "").strip(),
            "invoice_number": str(resp.get("invoice_number") or "").strip(),
            "subtotal": float(resp.get("subtotal") or 0.0),
            "tax_amount": float(resp.get("tax_amount") or 0.0),
            "total_amount": float(resp.get("total_amount") or 0.0),
            "currency": str(resp.get("currency") or "RON").strip() or "RON",
            "issued_at": str(resp.get("issued_at") or "").strip(),
            "due_date": str(resp.get("due_date") or "").strip(),
            "partner_id": int(resp.get("partner_id") or 0),
            "cost_center_id": int(resp.get("cost_center_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "created_at": str(resp.get("created_at") or "").strip(),
            "updated_at": str(resp.get("updated_at") or "").strip(),
        }

    def update_case_invoice_status(
        self,
        *,
        invoice_id: int,
        status: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        iid = int(invoice_id or 0)
        if iid <= 0:
            raise ValueError("invoice_id invalid.")
        payload: Dict[str, Any] = {"status": str(status or "").strip()}
        resp = self._request_json(
            method="PATCH",
            path=f"/api/v1/case-invoices/{iid}/status",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "invoice_id": int(resp.get("invoice_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "updated_at": str(resp.get("updated_at") or "").strip(),
        }

    def register_invoice_payment(
        self,
        *,
        invoice_id: int,
        amount: float,
        paid_at: str = "",
        payment_method: str = "cash",
        reference_no: str = "",
        notes: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        iid = int(invoice_id or 0)
        if iid <= 0:
            raise ValueError("invoice_id invalid.")
        payload: Dict[str, Any] = {
            "amount": float(amount or 0.0),
            "paid_at": str(paid_at or "").strip(),
            "payment_method": str(payment_method or "").strip(),
            "reference_no": str(reference_no or "").strip(),
            "notes": str(notes or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/case-invoices/{iid}/payments",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "payment_id": int(resp.get("payment_id") or 0),
            "invoice_id": int(resp.get("invoice_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "amount": float(resp.get("amount") or 0.0),
            "currency": str(resp.get("currency") or "RON").strip() or "RON",
            "paid_at": str(resp.get("paid_at") or "").strip(),
            "payment_method": str(resp.get("payment_method") or "").strip(),
            "reference_no": str(resp.get("reference_no") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "created_at": str(resp.get("created_at") or "").strip(),
            "invoice_status": str(resp.get("invoice_status") or "").strip(),
        }

    def list_orders_for_admission(self, *, admission_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/orders"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "order_type": str(row.get("order_type") or "").strip(),
                    "priority": str(row.get("priority") or "").strip(),
                    "order_text": str(row.get("order_text") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "ordered_at": str(row.get("ordered_at") or "").strip(),
                    "completed_at": str(row.get("completed_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_vitals_for_admission(self, *, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/vitals"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "recorded_at": str(row.get("recorded_at") or "").strip(),
                    "temperature_c": str(row.get("temperature_c") or "").strip(),
                    "systolic_bp": str(row.get("systolic_bp") or "").strip(),
                    "diastolic_bp": str(row.get("diastolic_bp") or "").strip(),
                    "pulse": str(row.get("pulse") or "").strip(),
                    "respiratory_rate": str(row.get("respiratory_rate") or "").strip(),
                    "spo2": str(row.get("spo2") or "").strip(),
                    "pain_score": str(row.get("pain_score") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_institutional_reports(self, *, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/institutional-reports"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "report_type": str(row.get("report_type") or "").strip(),
                    "payload_json": str(row.get("payload_json") or ""),
                    "payload_hash": str(row.get("payload_hash") or ""),
                    "validation_errors": str(row.get("validation_errors") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "external_reference": str(row.get("external_reference") or "").strip(),
                    "ack_payload": str(row.get("ack_payload") or ""),
                    "submitted_at": str(row.get("submitted_at") or "").strip(),
                    "transport_state": str(row.get("transport_state") or "").strip(),
                    "transport_attempts": int(row.get("transport_attempts") or 0),
                    "transport_last_error": str(row.get("transport_last_error") or ""),
                    "transport_http_code": int(row.get("transport_http_code") or 0),
                    "transport_last_attempt_at": str(row.get("transport_last_attempt_at") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def get_institutional_reporting_status(self, *, admission_id: int) -> Dict[str, bool]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        resp = self._request_json(
            method="GET",
            path=f"/api/v1/admissions/{aid}/institutional-reports/status",
        )
        return {
            "siui": bool(resp.get("siui", False)),
            "drg": bool(resp.get("drg", False)),
        }

    def list_billing_records(self, *, admission_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/billing-records"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "record_type": str(row.get("record_type") or "").strip(),
                    "amount": float(row.get("amount") or 0.0),
                    "currency": str(row.get("currency") or "RON").strip() or "RON",
                    "issued_at": str(row.get("issued_at") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "cost_center_id": int(row.get("cost_center_id") or 0),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_case_invoices(self, *, admission_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/case-invoices"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "invoice_type": str(row.get("invoice_type") or "").strip(),
                    "series": str(row.get("series") or "").strip(),
                    "invoice_number": str(row.get("invoice_number") or "").strip(),
                    "subtotal": float(row.get("subtotal") or 0.0),
                    "tax_amount": float(row.get("tax_amount") or 0.0),
                    "total_amount": float(row.get("total_amount") or 0.0),
                    "currency": str(row.get("currency") or "RON").strip() or "RON",
                    "issued_at": str(row.get("issued_at") or "").strip(),
                    "due_date": str(row.get("due_date") or "").strip(),
                    "partner_id": int(row.get("partner_id") or 0),
                    "cost_center_id": int(row.get("cost_center_id") or 0),
                    "status": str(row.get("status") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_invoice_payments(self, *, invoice_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        iid = int(invoice_id or 0)
        if iid <= 0:
            raise ValueError("invoice_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/case-invoices/{iid}/payments"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "invoice_id": int(row.get("invoice_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "amount": float(row.get("amount") or 0.0),
                    "currency": str(row.get("currency") or "RON").strip() or "RON",
                    "paid_at": str(row.get("paid_at") or "").strip(),
                    "payment_method": str(row.get("payment_method") or "").strip(),
                    "reference_no": str(row.get("reference_no") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "created_at": str(row.get("created_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_offer_contract(
        self,
        *,
        admission_id: int,
        doc_type: str,
        package_name: str,
        accommodation_type: str,
        base_price: float,
        discount_amount: float,
        final_price: Optional[float] = None,
        status: str = "draft",
        notes: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload: Dict[str, Any] = {
            "doc_type": str(doc_type or "").strip(),
            "package_name": str(package_name or "").strip(),
            "accommodation_type": str(accommodation_type or "").strip(),
            "base_price": float(base_price or 0.0),
            "discount_amount": float(discount_amount or 0.0),
            "final_price": float(final_price) if final_price is not None else None,
            "status": str(status or "").strip(),
            "notes": str(notes or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/offer-contracts",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "offer_id": int(resp.get("offer_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "doc_type": str(resp.get("doc_type") or "").strip(),
            "package_name": str(resp.get("package_name") or "").strip(),
            "accommodation_type": str(resp.get("accommodation_type") or "").strip(),
            "base_price": float(resp.get("base_price") or 0.0),
            "discount_amount": float(resp.get("discount_amount") or 0.0),
            "final_price": float(resp.get("final_price") or 0.0),
            "currency": str(resp.get("currency") or "RON").strip() or "RON",
            "status": str(resp.get("status") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "created_at": str(resp.get("created_at") or "").strip(),
            "updated_at": str(resp.get("updated_at") or "").strip(),
        }

    def update_offer_contract_status(
        self,
        *,
        offer_id: int,
        status: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        oid = int(offer_id or 0)
        if oid <= 0:
            raise ValueError("offer_id invalid.")
        payload: Dict[str, Any] = {"status": str(status or "").strip()}
        resp = self._request_json(
            method="PATCH",
            path=f"/api/v1/offer-contracts/{oid}/status",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "offer_id": int(resp.get("offer_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "updated_at": str(resp.get("updated_at") or "").strip(),
        }

    def list_offer_contracts(self, *, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/offer-contracts"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "doc_type": str(row.get("doc_type") or "").strip(),
                    "package_name": str(row.get("package_name") or "").strip(),
                    "accommodation_type": str(row.get("accommodation_type") or "").strip(),
                    "base_price": float(row.get("base_price") or 0.0),
                    "discount_amount": float(row.get("discount_amount") or 0.0),
                    "final_price": float(row.get("final_price") or 0.0),
                    "currency": str(row.get("currency") or "RON").strip() or "RON",
                    "status": str(row.get("status") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_medical_leave(
        self,
        *,
        admission_id: int,
        series: str,
        leave_number: str,
        issued_at: str,
        start_date: str,
        end_date: str,
        diagnosis_code: str,
        notes: str = "",
        series_rule_id: Optional[int] = None,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload: Dict[str, Any] = {
            "series": str(series or "").strip(),
            "leave_number": str(leave_number or "").strip(),
            "issued_at": str(issued_at or "").strip(),
            "start_date": str(start_date or "").strip(),
            "end_date": str(end_date or "").strip(),
            "diagnosis_code": str(diagnosis_code or "").strip(),
            "notes": str(notes or "").strip(),
            "series_rule_id": int(series_rule_id) if series_rule_id else None,
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/medical-leaves",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "leave_id": int(resp.get("leave_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "series": str(resp.get("series") or "").strip(),
            "leave_number": str(resp.get("leave_number") or "").strip(),
            "issued_at": str(resp.get("issued_at") or "").strip(),
            "start_date": str(resp.get("start_date") or "").strip(),
            "end_date": str(resp.get("end_date") or "").strip(),
            "days_count": int(resp.get("days_count") or 0),
            "diagnosis_code": str(resp.get("diagnosis_code") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "status": str(resp.get("status") or "").strip(),
            "series_rule_id": int(resp.get("series_rule_id") or 0),
            "created_at": str(resp.get("created_at") or "").strip(),
        }

    def cancel_medical_leave(
        self,
        *,
        leave_id: int,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        lid = int(leave_id or 0)
        if lid <= 0:
            raise ValueError("leave_id invalid.")
        resp = self._request_json(
            method="PATCH",
            path=f"/api/v1/medical-leaves/{lid}/cancel",
            payload={},
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "leave_id": int(resp.get("leave_id") or 0),
            "status": str(resp.get("status") or "").strip(),
        }

    def list_medical_leaves(self, *, admission_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/medical-leaves"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "series": str(row.get("series") or "").strip(),
                    "leave_number": str(row.get("leave_number") or "").strip(),
                    "issued_at": str(row.get("issued_at") or "").strip(),
                    "start_date": str(row.get("start_date") or "").strip(),
                    "end_date": str(row.get("end_date") or "").strip(),
                    "days_count": int(row.get("days_count") or 0),
                    "diagnosis_code": str(row.get("diagnosis_code") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "series_rule_id": int(row.get("series_rule_id") or 0),
                    "created_at": str(row.get("created_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_case_consumption(
        self,
        *,
        admission_id: int,
        item_type: str,
        item_name: str,
        unit: str,
        quantity: float,
        unit_price: float,
        source: str,
        notes: str = "",
        recorded_at: str = "",
        partner_id: Optional[int] = None,
        cost_center_id: Optional[int] = None,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        payload: Dict[str, Any] = {
            "item_type": str(item_type or "").strip(),
            "item_name": str(item_name or "").strip(),
            "unit": str(unit or "").strip(),
            "quantity": float(quantity or 0.0),
            "unit_price": float(unit_price or 0.0),
            "source": str(source or "").strip(),
            "notes": str(notes or "").strip(),
            "recorded_at": str(recorded_at or "").strip(),
            "partner_id": int(partner_id) if partner_id else None,
            "cost_center_id": int(cost_center_id) if cost_center_id else None,
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/admissions/{aid}/case-consumptions",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "consumption_id": int(resp.get("consumption_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "item_type": str(resp.get("item_type") or "").strip(),
            "item_name": str(resp.get("item_name") or "").strip(),
            "unit": str(resp.get("unit") or "").strip(),
            "quantity": float(resp.get("quantity") or 0.0),
            "unit_price": float(resp.get("unit_price") or 0.0),
            "total_price": float(resp.get("total_price") or 0.0),
            "source": str(resp.get("source") or "").strip(),
            "partner_id": int(resp.get("partner_id") or 0),
            "cost_center_id": int(resp.get("cost_center_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "recorded_at": str(resp.get("recorded_at") or "").strip(),
        }

    def update_case_consumption_status(
        self,
        *,
        consumption_id: int,
        status: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        cid = int(consumption_id or 0)
        if cid <= 0:
            raise ValueError("consumption_id invalid.")
        payload: Dict[str, Any] = {"status": str(status or "").strip()}
        resp = self._request_json(
            method="PATCH",
            path=f"/api/v1/case-consumptions/{cid}/status",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "consumption_id": int(resp.get("consumption_id") or 0),
            "status": str(resp.get("status") or "").strip(),
        }

    def list_case_consumptions(self, *, admission_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        aid = int(admission_id or 0)
        if aid <= 0:
            raise ValueError("admission_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/admissions/{aid}/case-consumptions"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "item_type": str(row.get("item_type") or "").strip(),
                    "item_name": str(row.get("item_name") or "").strip(),
                    "unit": str(row.get("unit") or "").strip(),
                    "quantity": float(row.get("quantity") or 0.0),
                    "unit_price": float(row.get("unit_price") or 0.0),
                    "total_price": float(row.get("total_price") or 0.0),
                    "source": str(row.get("source") or "").strip(),
                    "partner_id": int(row.get("partner_id") or 0),
                    "cost_center_id": int(row.get("cost_center_id") or 0),
                    "status": str(row.get("status") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "recorded_at": str(row.get("recorded_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_order(
        self,
        *,
        patient_id: int,
        admission_id: Optional[int],
        order_type: str,
        priority: str,
        order_text: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        payload: Dict[str, Any] = {
            "admission_id": int(admission_id) if admission_id else None,
            "order_type": str(order_type or "").strip(),
            "priority": str(priority or "").strip(),
            "order_text": str(order_text or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/orders",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "order_id": int(resp.get("order_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "order_type": str(resp.get("order_type") or "").strip(),
            "priority": str(resp.get("priority") or "").strip(),
            "order_text": str(resp.get("order_text") or "").strip(),
            "status": str(resp.get("status") or "").strip(),
            "ordered_at": str(resp.get("ordered_at") or "").strip(),
            "completed_at": str(resp.get("completed_at") or "").strip(),
        }

    def update_order_status(
        self,
        *,
        order_id: int,
        status: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        oid = int(order_id or 0)
        if oid <= 0:
            raise ValueError("order_id invalid.")
        payload: Dict[str, Any] = {"status": str(status or "").strip()}
        resp = self._request_json(
            method="PATCH",
            path=f"/api/v1/orders/{oid}/status",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "order_id": int(resp.get("order_id") or 0),
            "status": str(resp.get("status") or "").strip(),
            "completed_at": str(resp.get("completed_at") or "").strip(),
        }

    def list_orders(self, *, patient_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/patients/{pid}/orders"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "order_type": str(row.get("order_type") or "").strip(),
                    "priority": str(row.get("priority") or "").strip(),
                    "order_text": str(row.get("order_text") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "ordered_at": str(row.get("ordered_at") or "").strip(),
                    "completed_at": str(row.get("completed_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_vital(
        self,
        *,
        patient_id: int,
        admission_id: Optional[int],
        recorded_at: str,
        temperature_c: str,
        systolic_bp: str,
        diastolic_bp: str,
        pulse: str,
        respiratory_rate: str,
        spo2: str,
        pain_score: str,
        notes: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        payload: Dict[str, Any] = {
            "admission_id": int(admission_id) if admission_id else None,
            "recorded_at": str(recorded_at or "").strip(),
            "temperature_c": str(temperature_c or "").strip(),
            "systolic_bp": str(systolic_bp or "").strip(),
            "diastolic_bp": str(diastolic_bp or "").strip(),
            "pulse": str(pulse or "").strip(),
            "respiratory_rate": str(respiratory_rate or "").strip(),
            "spo2": str(spo2 or "").strip(),
            "pain_score": str(pain_score or "").strip(),
            "notes": str(notes or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/vitals",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "vital_id": int(resp.get("vital_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "admission_id": int(resp.get("admission_id") or 0),
            "recorded_at": str(resp.get("recorded_at") or "").strip(),
            "temperature_c": str(resp.get("temperature_c") or "").strip(),
            "systolic_bp": str(resp.get("systolic_bp") or "").strip(),
            "diastolic_bp": str(resp.get("diastolic_bp") or "").strip(),
            "pulse": str(resp.get("pulse") or "").strip(),
            "respiratory_rate": str(resp.get("respiratory_rate") or "").strip(),
            "spo2": str(resp.get("spo2") or "").strip(),
            "pain_score": str(resp.get("pain_score") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
        }

    def list_vitals(self, *, patient_id: int, limit: int = 300) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/patients/{pid}/vitals"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "recorded_at": str(row.get("recorded_at") or "").strip(),
                    "temperature_c": str(row.get("temperature_c") or "").strip(),
                    "systolic_bp": str(row.get("systolic_bp") or "").strip(),
                    "diastolic_bp": str(row.get("diastolic_bp") or "").strip(),
                    "pulse": str(row.get("pulse") or "").strip(),
                    "respiratory_rate": str(row.get("respiratory_rate") or "").strip(),
                    "spo2": str(row.get("spo2") or "").strip(),
                    "pain_score": str(row.get("pain_score") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_visit(
        self,
        *,
        patient_id: int,
        visit_date: str,
        reason: str,
        diagnosis: str,
        treatment: str,
        notes: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        payload: Dict[str, Any] = {
            "visit_date": str(visit_date or "").strip(),
            "reason": str(reason or "").strip(),
            "diagnosis": str(diagnosis or "").strip(),
            "treatment": str(treatment or "").strip(),
            "notes": str(notes or "").strip(),
        }
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/visits",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "visit_id": int(resp.get("visit_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "visit_date": str(resp.get("visit_date") or "").strip(),
            "reason": str(resp.get("reason") or "").strip(),
            "diagnosis": str(resp.get("diagnosis") or "").strip(),
            "treatment": str(resp.get("treatment") or "").strip(),
            "notes": str(resp.get("notes") or "").strip(),
            "created_at": str(resp.get("created_at") or "").strip(),
        }

    def delete_visit(
        self,
        *,
        visit_id: int,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        vid = int(visit_id or 0)
        if vid <= 0:
            raise ValueError("visit_id invalid.")
        resp = self._request_json(
            method="DELETE",
            path=f"/api/v1/visits/{vid}",
            idempotency_key=(idempotency_key or "").strip(),
        )
        return {
            "visit_id": int(resp.get("visit_id") or 0),
            "patient_id": int(resp.get("patient_id") or 0),
            "deleted": bool(resp.get("deleted", False)),
        }

    def list_visits(self, *, patient_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query = urllib.parse.urlencode({"limit": str(max(1, int(limit)))})
        path = f"/api/v1/patients/{pid}/visits"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "visit_date": str(row.get("visit_date") or "").strip(),
                    "reason": str(row.get("reason") or "").strip(),
                    "diagnosis": str(row.get("diagnosis") or "").strip(),
                    "treatment": str(row.get("treatment") or "").strip(),
                    "notes": str(row.get("notes") or ""),
                    "created_at": str(row.get("created_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_medis_investigations(
        self,
        *,
        patient_id: int,
        admission_id: int = 0,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if int(admission_id or 0) > 0:
            query_payload["admission_id"] = str(int(admission_id))
        query = urllib.parse.urlencode(query_payload)
        path = f"/api/v1/patients/{pid}/medis-investigations"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "order_id": int(row.get("order_id") or 0),
                    "patient_id": int(row.get("patient_id") or 0),
                    "admission_id": int(row.get("admission_id") or 0),
                    "provider": str(row.get("provider") or "").strip(),
                    "external_request_id": str(row.get("external_request_id") or "").strip(),
                    "requested_at": str(row.get("requested_at") or "").strip(),
                    "request_payload": str(row.get("request_payload") or ""),
                    "status": str(row.get("status") or "").strip(),
                    "result_received_at": str(row.get("result_received_at") or "").strip(),
                    "result_summary": str(row.get("result_summary") or ""),
                    "result_flag": str(row.get("result_flag") or "").strip(),
                    "result_payload": str(row.get("result_payload") or ""),
                    "external_result_id": str(row.get("external_result_id") or "").strip(),
                    "transport_state": str(row.get("transport_state") or "").strip(),
                    "transport_attempts": int(row.get("transport_attempts") or 0),
                    "transport_last_error": str(row.get("transport_last_error") or ""),
                    "transport_http_code": int(row.get("transport_http_code") or 0),
                    "transport_last_attempt_at": str(row.get("transport_last_attempt_at") or "").strip(),
                    "order_type": str(row.get("order_type") or "").strip(),
                    "priority": str(row.get("priority") or "").strip(),
                    "order_text": str(row.get("order_text") or ""),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def create_patient(self, *, payload: Dict[str, Any], idempotency_key: str = "") -> Dict[str, Any]:
        return self._request_json(
            method="POST",
            path="/api/v1/patients",
            payload=dict(payload or {}),
            idempotency_key=(idempotency_key or "").strip(),
        )

    def patch_patient(
        self,
        *,
        patient_id: int,
        payload: Dict[str, Any],
        idempotency_key: str = "",
        expected_updated_at: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        body = dict(payload or {})
        expected = str(expected_updated_at or "").strip()
        if expected:
            body["expected_updated_at"] = expected
        return self._request_json(
            method="PATCH",
            path=f"/api/v1/patients/{pid}",
            payload=body,
            idempotency_key=(idempotency_key or "").strip(),
        )

    def delete_patient(
        self,
        *,
        patient_id: int,
        expected_updated_at: str = "",
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        expected = str(expected_updated_at or "").strip()
        extra_headers: Dict[str, str] = {}
        if expected:
            extra_headers["X-Expected-Updated-At"] = expected
        return self._request_json(
            method="DELETE",
            path=f"/api/v1/patients/{pid}",
            idempotency_key=(idempotency_key or "").strip(),
            extra_headers=extra_headers if extra_headers else None,
        )

    def drg_icm_estimate(
        self,
        *,
        patient_id: int,
        primary_icd10: str,
        secondary_icd10: List[str],
        free_text: str,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        pid = int(patient_id or 0)
        if pid <= 0:
            raise ValueError("patient_id invalid.")
        payload = {
            "primary_icd10": str(primary_icd10 or "").strip(),
            "secondary_icd10": [str(item or "").strip() for item in (secondary_icd10 or []) if str(item or "").strip()],
            "free_text": str(free_text or "").strip(),
        }
        return self._request_json(
            method="POST",
            path=f"/api/v1/patients/{pid}/drg-icm-estimate",
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )

    def get_health(self) -> Dict[str, Any]:
        resp = self._request_json(method="GET", path="/api/v1/health")
        checks_obj = resp.get("checks")
        checks = dict(checks_obj) if isinstance(checks_obj, dict) else {}
        return {
            "status": str(resp.get("status") or "").strip(),
            "timestamp": str(resp.get("timestamp") or "").strip(),
            "checks": checks,
        }

    def list_integration_queue(self, *, limit: int = 200, status_filter: str = "") -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (status_filter or "").strip():
            query_payload["status_filter"] = str(status_filter).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/ops/integration-queue"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "provider": str(row.get("provider") or "").strip(),
                    "operation": str(row.get("operation") or "").strip(),
                    "entity_type": str(row.get("entity_type") or "").strip(),
                    "entity_id": int(row.get("entity_id") or 0),
                    "status": str(row.get("status") or "").strip(),
                    "attempt_count": int(row.get("attempt_count") or 0),
                    "next_retry_at": str(row.get("next_retry_at") or "").strip(),
                    "last_error": str(row.get("last_error") or ""),
                    "last_http_code": int(row.get("last_http_code") or 0),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_job_executions(self, *, limit: int = 200, job_name: str = "") -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (job_name or "").strip():
            query_payload["job_name"] = str(job_name).strip()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/ops/job-executions"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "job_name": str(row.get("job_name") or "").strip(),
                    "status": str(row.get("status") or "").strip(),
                    "duration_ms": int(row.get("duration_ms") or 0),
                    "details_json": str(row.get("details_json") or ""),
                    "correlation_id": str(row.get("correlation_id") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def list_integration_dry_run_logs(
        self,
        *,
        limit: int = 200,
        provider: str = "",
        operation: str = "",
    ) -> List[Dict[str, Any]]:
        query_payload: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if (provider or "").strip():
            query_payload["provider"] = str(provider).strip().lower()
        if (operation or "").strip():
            query_payload["operation"] = str(operation).strip().lower()
        query = urllib.parse.urlencode(query_payload)
        path = "/api/v1/ops/integration-dry-run-logs"
        if query:
            path = f"{path}?{query}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "provider": str(row.get("provider") or "").strip(),
                    "operation": str(row.get("operation") or "").strip(),
                    "dry_run": bool(row.get("dry_run", True)),
                    "http_code": int(row.get("http_code") or 0),
                    "latency_ms": int(row.get("latency_ms") or 0),
                    "ok": bool(row.get("ok", False)),
                    "error": str(row.get("error") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "correlation_id": str(row.get("correlation_id") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]

    def get_shadow_sync_status(self) -> Dict[str, Any]:
        resp = self._request_json(method="GET", path="/api/v1/ops/shadow-sync/status")
        return {
            "timestamp": str(resp.get("timestamp") or "").strip(),
            "shadow_mode_enabled": bool(resp.get("shadow_mode_enabled", False)),
            "shadow_backlog_pending": int(resp.get("shadow_backlog_pending") or 0),
            "shadow_last_sync_at": str(resp.get("shadow_last_sync_at") or "").strip(),
            "shadow_error_rate_24h": float(resp.get("shadow_error_rate_24h") or 0.0),
            "attempted_24h": int(resp.get("attempted_24h") or 0),
            "failed_24h": int(resp.get("failed_24h") or 0),
            "settings": dict(resp.get("settings") or {}),
        }

    def process_shadow_sync(self, *, max_jobs: int = 0) -> Dict[str, Any]:
        path = "/api/v1/ops/shadow-sync/process"
        jobs = int(max_jobs or 0)
        if jobs > 0:
            path = f"{path}?max_jobs={jobs}"
        return self._request_json(method="POST", path=path, payload={})

    def list_shadow_sync_errors(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        lim = max(1, int(limit or 200))
        path = f"/api/v1/ops/shadow-sync/errors?limit={lim}"
        resp = self._request_json(method="GET", path=path)
        rows = resp.get("items")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": int(row.get("id") or 0),
                    "action_key": str(row.get("action_key") or "").strip(),
                    "source": str(row.get("source") or "").strip(),
                    "payload_hash": str(row.get("payload_hash") or "").strip(),
                    "status": str(row.get("status") or "").strip(),
                    "retry_count": int(row.get("retry_count") or 0),
                    "next_retry_at": str(row.get("next_retry_at") or "").strip(),
                    "last_error": str(row.get("last_error") or "").strip(),
                    "last_attempt_at": str(row.get("last_attempt_at") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "updated_at": str(row.get("updated_at") or "").strip(),
                }
            )
        return [item for item in out if int(item.get("id") or 0) > 0]
