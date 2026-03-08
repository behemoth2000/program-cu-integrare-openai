from __future__ import annotations

import hashlib
import json
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from pacienti_ai_independent.domain.dto import (
    AdmissionCreateDto,
    AdmissionCreateResultDto,
    AdmissionDiagnosesDto,
    AdmissionDiagnosesResultDto,
    AdmissionDischargeDto,
    AdmissionDischargeResultDto,
    AdmissionListItemDto,
    AdmissionTransferRequestDto,
    AdmissionTransferResultDto,
    BillingRecordCreateDto,
    BillingRecordCreateResultDto,
    AdmissionTransferItemDto,
    BillingRecordItemDto,
    CaseConsumptionCreateDto,
    CaseConsumptionCreateResultDto,
    CaseConsumptionStatusUpdateDto,
    CaseConsumptionStatusUpdateResultDto,
    CaseValidationResultDto,
    CaseConsumptionItemDto,
    CaseInvoiceCreateDto,
    CaseInvoiceCreateResultDto,
    CaseInvoiceItemDto,
    CaseInvoiceStatusUpdateDto,
    CaseInvoiceStatusUpdateResultDto,
    DashboardAdmissionItemDto,
    DashboardKpiDto,
    DashboardUrgentOrderItemDto,
    DashboardVitalAlertItemDto,
    DrgIcmEstimateDto,
    FinalizeCaseRequestDto,
    FinalizeCaseResultDto,
    HealthDto,
    IntegrationDryRunLogItemDto,
    IntegrationQueueItemDto,
    InvoicePaymentCreateDto,
    InvoicePaymentCreateResultDto,
    InvoicePaymentItemDto,
    InstitutionalReportItemDto,
    MedisInvestigationItemDto,
    MedicalLeaveCancelResultDto,
    MedicalLeaveCreateDto,
    MedicalLeaveCreateResultDto,
    MedicalLeaveItemDto,
    OrderCreateDto,
    OrderCreateResultDto,
    OrderStatusUpdateDto,
    OrderStatusUpdateResultDto,
    OrderItemDto,
    OfferContractCreateDto,
    OfferContractCreateResultDto,
    OfferContractStatusUpdateDto,
    OfferContractStatusUpdateResultDto,
    OfferContractItemDto,
    VitalCreateDto,
    VitalCreateResultDto,
    VitalItemDto,
    VisitCreateDto,
    VisitCreateResultDto,
    VisitDeleteResultDto,
    VisitItemDto,
    PatientDiagnosisDto,
    PatientDto,
    PatientListItemDto,
    PatientPatchDto,
    PatientSnapshotDiffDto,
    PatientSnapshotDto,
    RestoreSnapshotRequestDto,
    RestoreSnapshotResultDto,
    TimelineEventDto,
)
from pacienti_ai_independent.observability import (
    configure_telemetry,
    get_app_logger,
    set_correlation_id,
    telemetry_enabled,
    traced_operation,
)
from pacienti_ai_independent.data_backend import PostgresShadowBackend, process_shadow_sync_with_backend
from pacienti_ai_independent.pacienti_ai_app import APP_DIR, DB_PATH, Database, now_ts
from pacienti_ai_independent.repositories import PatientRepository
from pacienti_ai_independent.security import RequestActor, require_roles
from pacienti_ai_independent.services import PatientService

try:  # optional dependency for Val 3 preview (central DB readiness checks)
    import psycopg  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


def _json_model(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return dict(model)


def _to_bool(value: str, default: bool = False) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def _to_float(value: str, default: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    try:
        parsed = float((value or "").strip() or default)
    except Exception:
        parsed = default
    parsed = max(min_value, min(max_value, parsed))
    return parsed


def _normalized_db_backend(value: str) -> str:
    backend = (value or "").strip().lower()
    if backend in {"postgres", "postgresql"}:
        return "postgres"
    return "sqlite"


def _check_postgres_connectivity(dsn: str, timeout_seconds: int = 2) -> Tuple[bool, str]:
    dsn_text = (dsn or "").strip()
    if not dsn_text:
        return False, "PACIENTI_POSTGRES_DSN lipseste."
    if psycopg is None:
        return False, "Pachetul psycopg nu este instalat."
    try:
        with psycopg.connect(dsn_text, connect_timeout=max(1, int(timeout_seconds))) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                _ = cur.fetchone()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _to_int(value: str, default: int, min_value: int = 0, max_value: int = 10_000) -> int:
    try:
        parsed = int(str(value or "").strip() or str(default))
    except Exception:
        parsed = int(default)
    return max(min_value, min(max_value, parsed))


def create_api_app(db_path: Optional[Path] = None) -> FastAPI:
    logger = get_app_logger("pacienti_ai.enterprise.api")
    obs_enabled = _to_bool(os.getenv("OBSERVABILITY_ENABLED") or "0", False)
    obs_service = (os.getenv("OBSERVABILITY_SERVICE_NAME") or "pacienti-ai-enterprise-api").strip()
    obs_endpoint = (os.getenv("OBSERVABILITY_OTLP_ENDPOINT") or "").strip()
    obs_sample_ratio = _to_float(os.getenv("OBSERVABILITY_SAMPLE_RATIO") or "1.0", 1.0, 0.0, 1.0)
    telemetry_active = configure_telemetry(
        service_name=obs_service,
        enabled=obs_enabled,
        otlp_endpoint=obs_endpoint,
        sample_ratio=obs_sample_ratio,
    )
    sqlite_db_path = Path(db_path) if db_path is not None else DB_PATH
    db = Database(sqlite_db_path)
    repository = PatientRepository(db)
    service = PatientService(repository)

    configured_backend = _normalized_db_backend(os.getenv("PACIENTI_DB_BACKEND") or "sqlite")
    postgres_dsn = (os.getenv("PACIENTI_POSTGRES_DSN") or "").strip()
    postgres_timeout = max(1, int(_to_float(os.getenv("PACIENTI_POSTGRES_CONNECT_TIMEOUT_SECONDS") or "2", 2.0, 1.0, 30.0)))

    def _shadow_runtime_settings() -> Dict[str, Any]:
        env_enabled = os.getenv("PACIENTI_POSTGRES_SHADOW_ENABLED")
        db_enabled_raw = db.get_setting("API_INTERNAL_POSTGRES_SHADOW_ENABLED", "0")
        if env_enabled is None:
            enabled = _to_bool(db_enabled_raw, False)
        else:
            enabled = _to_bool(env_enabled, False)

        def _setting(name: str, default: str) -> str:
            env_value = os.getenv(name)
            if env_value is not None:
                return str(env_value).strip()
            db_key = name.replace("PACIENTI_", "")
            return str(db.get_setting(db_key, default) or default).strip()

        return {
            "enabled": bool(enabled),
            "max_retries": _to_int(
                _setting("PACIENTI_POSTGRES_SHADOW_MAX_RETRIES", db.get_setting("API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES", "3")),
                3,
                0,
                100,
            ),
            "batch_size": _to_int(
                _setting("PACIENTI_POSTGRES_SHADOW_BATCH_SIZE", db.get_setting("API_INTERNAL_POSTGRES_SHADOW_BATCH_SIZE", "50")),
                50,
                1,
                1000,
            ),
            "interval_seconds": _to_int(
                _setting("PACIENTI_POSTGRES_SHADOW_INTERVAL_SECONDS", db.get_setting("API_INTERNAL_POSTGRES_SHADOW_INTERVAL_SECONDS", "60")),
                60,
                5,
                3600,
            ),
            "stop_on_error_rate": _to_float(
                _setting(
                    "PACIENTI_POSTGRES_SHADOW_STOP_ON_ERROR_RATE",
                    db.get_setting("API_INTERNAL_POSTGRES_SHADOW_STOP_ON_ERROR_RATE", "0.5"),
                ),
                0.5,
                0.0,
                1.0,
            ),
        }

    app = FastAPI(
        title="PacientiAIIndependent Enterprise API",
        version="1.0.0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
    )

    @app.middleware("http")
    async def _correlation_middleware(request: Request, call_next):
        corr = str(request.headers.get("X-Correlation-Id") or uuid.uuid4().hex).strip()
        set_correlation_id(corr)
        method = str(request.method or "GET").upper()
        path = str(request.url.path or "").strip()
        should_capture_shadow = (
            method in {"POST", "PATCH", "DELETE"}
            and path.startswith("/api/v1/")
            and not path.startswith("/api/v1/ops/shadow-sync")
        )
        request_body_text = ""
        if should_capture_shadow:
            try:
                raw = await request.body()
                request_body_text = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                request_body_text = ""
        with traced_operation(
            "api.request",
            {
                "http.method": request.method,
                "http.route": request.url.path,
                "correlation_id": corr,
            },
        ) as trace_ctx:
            response = await call_next(request)
            span = trace_ctx.get("span")
            if span is not None:
                try:
                    span.set_attribute("http.status_code", int(response.status_code))
                except Exception:
                    pass
        if should_capture_shadow and int(response.status_code or 0) < 500:
            settings = _shadow_runtime_settings()
            if bool(settings.get("enabled", False)):
                payload = {
                    "method": method,
                    "path": path,
                    "query": str(request.url.query or ""),
                    "status_code": int(response.status_code or 0),
                    "actor_role": str(request.headers.get("X-Role") or "").strip().lower(),
                    "actor_user_id": str(request.headers.get("X-User-Id") or "").strip(),
                    "correlation_id": corr,
                    "request_json": request_body_text[:12_000],
                    "captured_at": now_ts(),
                }
                payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                try:
                    service.enqueue_shadow_write(
                        action_key=f"{method} {path}",
                        source="api_middleware",
                        payload_json=payload_json,
                        payload_hash=payload_hash,
                    )
                except Exception as exc:
                    logger.warning("shadow enqueue failed: %s", str(exc))
        response.headers["X-Correlation-Id"] = corr
        return response

    def _idempotency_hit(
        *,
        endpoint: str,
        key: str,
        request_payload: Dict[str, Any],
    ) -> Optional[JSONResponse]:
        existing = repository.get_idempotency(endpoint=endpoint, key=key)
        if not existing:
            return None
        incoming_hash = repository.compute_request_hash(request_payload)
        stored_hash = str(existing.get("request_hash") or "")
        if stored_hash and stored_hash != incoming_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency-Key reutilizat cu payload diferit.",
            )
        status_code = int(existing.get("response_status") or 200)
        payload = db.integration_payload_to_dict(str(existing.get("response_json") or "{}"))
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/api/v1/health")
    def api_health(
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> HealthDto:
        _ = actor
        checks = service.health()
        shadow_settings = _shadow_runtime_settings()
        shadow_status = service.shadow_sync_status(lookback_hours=24)
        central_db_ready = False
        central_db_error = ""
        effective_backend = "sqlite"
        if configured_backend == "postgres":
            central_db_ready, central_db_error = _check_postgres_connectivity(postgres_dsn, postgres_timeout)
            if central_db_ready:
                effective_backend = "postgres"
            elif central_db_error:
                logger.warning("central postgres not ready, using sqlite fallback: %s", central_db_error)
        status_value = "ok"
        if not bool(checks.get("db_access", False)):
            status_value = "error"
        elif not bool(checks.get("required_tables_ok", False)):
            status_value = "degraded"
        elif configured_backend == "postgres" and not central_db_ready:
            status_value = "degraded"
        elif bool(shadow_settings.get("enabled", False)) and float(shadow_status.get("error_rate_24h") or 0.0) > float(
            shadow_settings.get("stop_on_error_rate") or 1.0
        ):
            status_value = "degraded"
        checks_payload: Dict[str, Any] = {
            "db_path": str(sqlite_db_path),
            "telemetry_enabled": bool(telemetry_enabled() and telemetry_active),
            "db_backend_configured": configured_backend,
            "db_backend_effective": effective_backend,
            "postgres_dsn_configured": bool(postgres_dsn),
            "central_db_ready": bool(central_db_ready),
            "shadow_mode_enabled": bool(shadow_settings.get("enabled", False)),
            "shadow_backlog_pending": int(shadow_status.get("backlog_pending") or 0),
            "shadow_last_sync_at": str(shadow_status.get("last_sync_at") or ""),
            "shadow_error_rate_24h": float(shadow_status.get("error_rate_24h") or 0.0),
            "shadow_stop_on_error_rate": float(shadow_settings.get("stop_on_error_rate") or 0.0),
            **checks,
        }
        if configured_backend == "postgres" and central_db_error:
            checks_payload["central_db_error"] = central_db_error
        return HealthDto(
            status=status_value,
            timestamp=now_ts(),
            checks=checks_payload,
        )

    @app.get("/api/v1/dashboard/kpis")
    def dashboard_kpis(
        department: str = "",
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        dept = (department or "").strip()
        item: DashboardKpiDto = service.get_dashboard_kpis(department=dept)
        return {
            "kpi": _json_model(item),
            "filters": {"department": dept},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/dashboard/active-admissions")
    def dashboard_active_admissions(
        department: str = "",
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        dept = (department or "").strip()
        rows: List[DashboardAdmissionItemDto] = service.list_dashboard_active_admissions(
            department=dept,
            limit=max(1, int(limit)),
        )
        return {
            "items": [_json_model(item) for item in rows],
            "filters": {
                "department": dept,
                "limit": max(1, int(limit)),
            },
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/dashboard/urgent-orders")
    def dashboard_urgent_orders(
        department: str = "",
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        dept = (department or "").strip()
        rows: List[DashboardUrgentOrderItemDto] = service.list_dashboard_urgent_orders(
            department=dept,
            limit=max(1, int(limit)),
        )
        return {
            "items": [_json_model(item) for item in rows],
            "filters": {
                "department": dept,
                "limit": max(1, int(limit)),
            },
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/dashboard/vital-alerts")
    def dashboard_vital_alerts(
        department: str = "",
        hours: int = 24,
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        dept = (department or "").strip()
        hours_clamped = max(1, int(hours))
        rows: List[DashboardVitalAlertItemDto] = service.list_dashboard_vital_alerts(
            department=dept,
            hours=hours_clamped,
            limit=max(1, int(limit)),
        )
        return {
            "items": [_json_model(item) for item in rows],
            "filters": {
                "department": dept,
                "hours": hours_clamped,
                "limit": max(1, int(limit)),
            },
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/patients/{patient_id}")
    def get_patient(
        patient_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> PatientDto:
        _ = actor
        try:
            return service.get_patient(patient_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    @app.get("/api/v1/patients/{patient_id}/timeline")
    def list_patient_timeline(
        patient_id: int,
        limit: int = 500,
        category: str = "",
        event_type: str = "",
        date_from: str = "",
        date_to: str = "",
        admission_id: int = 0,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        aid: Optional[int] = int(admission_id) if int(admission_id or 0) > 0 else None
        try:
            rows: List[TimelineEventDto] = service.list_patient_timeline(
                int(patient_id),
                limit=max(1, int(limit)),
                category=(category or "").strip(),
                event_type=(event_type or "").strip(),
                date_from=(date_from or "").strip(),
                date_to=(date_to or "").strip(),
                admission_id=aid,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {
                "limit": max(1, int(limit)),
                "category": (category or "").strip(),
                "event_type": (event_type or "").strip(),
                "date_from": (date_from or "").strip(),
                "date_to": (date_to or "").strip(),
                "admission_id": int(admission_id or 0),
            },
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/patients/{patient_id}/snapshots")
    def list_patient_snapshots(
        patient_id: int,
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        try:
            rows: List[PatientSnapshotDto] = service.list_patient_snapshots(
                int(patient_id),
                limit=max(1, int(limit)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/patients/{patient_id}/snapshots/{snapshot_id}")
    def get_patient_snapshot(
        patient_id: int,
        snapshot_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> PatientSnapshotDto:
        _ = actor
        try:
            return service.get_patient_snapshot(int(patient_id), int(snapshot_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    @app.get("/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/diff")
    def get_patient_snapshot_diff(
        patient_id: int,
        snapshot_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> PatientSnapshotDiffDto:
        _ = actor
        try:
            return service.get_patient_snapshot_diff(int(patient_id), int(snapshot_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    @app.post("/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/restore")
    def restore_patient_snapshot(
        patient_id: int,
        snapshot_id: int,
        payload: RestoreSnapshotRequestDto,
        actor: RequestActor = Depends(require_roles("admin")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        body = _json_model(payload)
        endpoint = f"/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/restore"
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out = service.restore_patient_snapshot(
                patient_id=int(patient_id),
                snapshot_id=int(snapshot_id),
                reason=str(payload.reason or "").strip(),
                user_id=actor.user_id,
                expected_updated_at=str(payload.expected_updated_at or "").strip(),
            )
        except ValueError as exc:
            msg = str(exc)
            if "concurenta" in msg.lower():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/patients/{patient_id}/admissions")
    def list_patient_admissions(
        patient_id: int,
        include_closed: bool = True,
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[AdmissionListItemDto] = service.list_admissions(
            patient_id=int(patient_id),
            include_closed=bool(include_closed),
            limit=max(1, int(limit)),
        )
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {
                "include_closed": bool(include_closed),
                "limit": max(1, int(limit)),
            },
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/patients/{patient_id}/admissions/active")
    def get_patient_active_admission(
        patient_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        item = service.get_active_admission(int(patient_id))
        return {
            "patient_id": int(patient_id),
            "item": _json_model(item) if item is not None else None,
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/patients/{patient_id}/admissions", status_code=status.HTTP_201_CREATED)
    def create_patient_admission(
        patient_id: int,
        payload: AdmissionCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/patients/{patient_id}/admissions"
        body = {"patient_id": int(patient_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: AdmissionCreateResultDto = service.create_admission(
                patient_id=int(patient_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_201_CREATED,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=content)

    @app.post("/api/v1/admissions/{admission_id}/discharge")
    def discharge_admission(
        admission_id: int,
        payload: AdmissionDischargeDto,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/discharge"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: AdmissionDischargeResultDto = service.discharge_admission(
                admission_id=int(admission_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistent" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "nu este activa" in lower_msg or "tranzitie invalida" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.post("/api/v1/admissions/{admission_id}/transfer")
    def transfer_admission(
        admission_id: int,
        payload: AdmissionTransferRequestDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/transfer"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: AdmissionTransferResultDto = service.transfer_admission(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistent" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "nu este activa" in lower_msg or "deja ocupat" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/case-validation")
    def validate_admission_case(
        admission_id: int,
        require_financial_closure: bool = False,
        require_siui_drg_submission: bool = False,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
    ) -> CaseValidationResultDto:
        _ = actor
        return service.validate_admission_case(
            admission_id=int(admission_id),
            require_financial_closure=bool(require_financial_closure),
            require_siui_drg_submission=bool(require_siui_drg_submission),
        )

    @app.post("/api/v1/admissions/{admission_id}/finalize-case")
    def finalize_admission_case(
        admission_id: int,
        payload: FinalizeCaseRequestDto,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/finalize-case"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: FinalizeCaseResultDto = service.finalize_admission_case(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "deja finalizat" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.post("/api/v1/admissions/{admission_id}/diagnoses")
    def save_admission_diagnoses(
        admission_id: int,
        payload: AdmissionDiagnosesDto,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/diagnoses"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: AdmissionDiagnosesResultDto = service.save_admission_diagnoses(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/transfers")
    def list_admission_transfers(
        admission_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[AdmissionTransferItemDto] = service.list_admission_transfers(
            admission_id=int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/admissions/{admission_id}/orders")
    def list_admission_orders(
        admission_id: int,
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[OrderItemDto] = service.list_orders_for_admission(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/admissions/{admission_id}/vitals")
    def list_admission_vitals(
        admission_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[VitalItemDto] = service.list_vitals_for_admission(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/admissions/{admission_id}/institutional-reports")
    def list_institutional_reports(
        admission_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[InstitutionalReportItemDto] = service.list_institutional_reports(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/admissions/{admission_id}/institutional-reports/status")
    def institutional_reporting_status(
        admission_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        status_map = service.institutional_reporting_status(int(admission_id))
        return {
            "admission_id": int(admission_id),
            "siui": bool(status_map.get("siui", False)),
            "drg": bool(status_map.get("drg", False)),
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/admissions/{admission_id}/billing-records")
    def list_billing_records(
        admission_id: int,
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[BillingRecordItemDto] = service.list_billing_records(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/admissions/{admission_id}/billing-records")
    def issue_billing_record(
        admission_id: int,
        payload: BillingRecordCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/billing-records"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: BillingRecordCreateResultDto = service.issue_billing_record(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistent" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "deja" in lower_msg or "doar dupa externare" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/case-invoices")
    def list_case_invoices(
        admission_id: int,
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[CaseInvoiceItemDto] = service.list_case_invoices(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/admissions/{admission_id}/case-invoices")
    def issue_case_invoice(
        admission_id: int,
        payload: CaseInvoiceCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/case-invoices"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: CaseInvoiceCreateResultDto = service.issue_case_invoice(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "deja" in lower_msg or "doar dupa externare" in lower_msg or "folosite" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.patch("/api/v1/case-invoices/{invoice_id}/status")
    def update_case_invoice_status(
        invoice_id: int,
        payload: CaseInvoiceStatusUpdateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/case-invoices/{invoice_id}/status"
        body = {"invoice_id": int(invoice_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: CaseInvoiceStatusUpdateResultDto = service.update_case_invoice_status(
                invoice_id=int(invoice_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "acoperita" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/case-invoices/{invoice_id}/payments")
    def list_invoice_payments(
        invoice_id: int,
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[InvoicePaymentItemDto] = service.list_invoice_payments(
            int(invoice_id),
            limit=max(1, int(limit)),
        )
        return {
            "invoice_id": int(invoice_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/case-invoices/{invoice_id}/payments")
    def register_invoice_payment(
        invoice_id: int,
        payload: InvoicePaymentCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/case-invoices/{invoice_id}/payments"
        body = {"invoice_id": int(invoice_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: InvoicePaymentCreateResultDto = service.register_invoice_payment(
                invoice_id=int(invoice_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "anulata" in lower_msg or "draft" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/offer-contracts")
    def list_offer_contracts(
        admission_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[OfferContractItemDto] = service.list_offer_contracts(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/admissions/{admission_id}/offer-contracts")
    def create_offer_contract(
        admission_id: int,
        payload: OfferContractCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/offer-contracts"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            admission = repository.get_admission(int(admission_id))
            if not admission:
                raise ValueError("Internare inexistenta pentru oferta/contract.")
            patient_id = int(admission.get("patient_id") or 0)
            out: OfferContractCreateResultDto = service.create_offer_contract(
                patient_id=patient_id,
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "nu apartine" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.patch("/api/v1/offer-contracts/{offer_id}/status")
    def update_offer_contract_status(
        offer_id: int,
        payload: OfferContractStatusUpdateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/offer-contracts/{offer_id}/status"
        body = {"offer_id": int(offer_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: OfferContractStatusUpdateResultDto = service.update_offer_contract_status(
                offer_id=int(offer_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/medical-leaves")
    def list_medical_leaves(
        admission_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[MedicalLeaveItemDto] = service.list_medical_leaves(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/admissions/{admission_id}/medical-leaves")
    def create_medical_leave(
        admission_id: int,
        payload: MedicalLeaveCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/medical-leaves"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: MedicalLeaveCreateResultDto = service.create_medical_leave(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            if "exista deja" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.patch("/api/v1/medical-leaves/{leave_id}/cancel")
    def cancel_medical_leave(
        leave_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/medical-leaves/{leave_id}/cancel"
        body = {"leave_id": int(leave_id)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: MedicalLeaveCancelResultDto = service.cancel_medical_leave(
                leave_id=int(leave_id),
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/admissions/{admission_id}/case-consumptions")
    def list_case_consumptions(
        admission_id: int,
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[CaseConsumptionItemDto] = service.list_case_consumptions(
            int(admission_id),
            limit=max(1, int(limit)),
        )
        return {
            "admission_id": int(admission_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/admissions/{admission_id}/case-consumptions")
    def create_case_consumption(
        admission_id: int,
        payload: CaseConsumptionCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/admissions/{admission_id}/case-consumptions"
        body = {"admission_id": int(admission_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: CaseConsumptionCreateResultDto = service.create_case_consumption(
                admission_id=int(admission_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "inexistenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.patch("/api/v1/case-consumptions/{consumption_id}/status")
    def update_case_consumption_status(
        consumption_id: int,
        payload: CaseConsumptionStatusUpdateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/case-consumptions/{consumption_id}/status"
        body = {"consumption_id": int(consumption_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: CaseConsumptionStatusUpdateResultDto = service.update_case_consumption_status(
                consumption_id=int(consumption_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/patients/{patient_id}/orders")
    def list_orders(
        patient_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[OrderItemDto] = service.list_orders(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/patients/{patient_id}/orders")
    def create_order(
        patient_id: int,
        payload: OrderCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/patients/{patient_id}/orders"
        body = {"patient_id": int(patient_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: OrderCreateResultDto = service.create_order(
                patient_id=int(patient_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.patch("/api/v1/orders/{order_id}/status")
    def update_order_status(
        order_id: int,
        payload: OrderStatusUpdateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/orders/{order_id}/status"
        body = {"order_id": int(order_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: OrderStatusUpdateResultDto = service.update_order_status(
                order_id=int(order_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/patients/{patient_id}/vitals")
    def list_vitals(
        patient_id: int,
        limit: int = 300,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[VitalItemDto] = service.list_vitals(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/patients/{patient_id}/vitals")
    def create_vital(
        patient_id: int,
        payload: VitalCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/patients/{patient_id}/vitals"
        body = {"patient_id": int(patient_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: VitalCreateResultDto = service.create_vital(
                patient_id=int(patient_id),
                payload=payload,
                user_id=actor.user_id,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/patients/{patient_id}/visits")
    def list_visits(
        patient_id: int,
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[VisitItemDto] = service.list_visits(
            int(patient_id),
            limit=max(1, int(limit)),
        )
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/patients/{patient_id}/visits")
    def create_visit(
        patient_id: int,
        payload: VisitCreateDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        _ = actor
        endpoint = f"/api/v1/patients/{patient_id}/visits"
        body = {"patient_id": int(patient_id), **_json_model(payload)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: VisitCreateResultDto = service.create_visit(
                patient_id=int(patient_id),
                payload=payload,
            )
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.delete("/api/v1/visits/{visit_id}")
    def delete_visit(
        visit_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/visits/{visit_id}"
        body = {"visit_id": int(visit_id)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: VisitDeleteResultDto = service.delete_visit(visit_id=int(visit_id))
        except ValueError as exc:
            msg = str(exc)
            if "inexistent" in msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.get("/api/v1/patients/{patient_id}/medis-investigations")
    def list_medis_investigations(
        patient_id: int,
        admission_id: int = 0,
        limit: int = 500,
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        aid: Optional[int] = int(admission_id) if int(admission_id) > 0 else None
        rows: List[MedisInvestigationItemDto] = service.list_medis_investigations(
            int(patient_id),
            admission_id=aid,
            limit=max(1, int(limit)),
        )
        return {
            "patient_id": int(patient_id),
            "items": [_json_model(item) for item in rows],
            "filters": {"admission_id": int(admission_id or 0), "limit": max(1, int(limit))},
            "timestamp": now_ts(),
        }

    @app.get("/api/v1/patients")
    def list_patients(
        search: str = "",
        status_filter: str = "all",
        status_date: str = "",
        actor: RequestActor = Depends(require_roles("admin", "medic", "asistent", "receptie")),
    ) -> Dict[str, Any]:
        _ = actor
        rows: List[PatientListItemDto] = service.list_patients(
            search=(search or "").strip(),
            status_filter=(status_filter or "all").strip() or "all",
            status_date=(status_date or "").strip(),
        )
        return {
            "items": [_json_model(item) for item in rows],
            "filters": {
                "search": (search or "").strip(),
                "status_filter": (status_filter or "all").strip() or "all",
                "status_date": (status_date or "").strip(),
            },
            "timestamp": now_ts(),
        }

    @app.post("/api/v1/patients", status_code=status.HTTP_201_CREATED)
    def create_patient(
        payload: PatientDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        body = _json_model(payload)
        endpoint = "/api/v1/patients"
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out = service.create_patient(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_201_CREATED,
                response_body=content,
                user_id=actor.user_id,
            )
        logger.info("api create_patient success")
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=content)

    @app.patch("/api/v1/patients/{patient_id}")
    def patch_patient(
        patient_id: int,
        patch: PatientPatchDto,
        actor: RequestActor = Depends(require_roles("admin", "medic", "receptie")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        body = _json_model(patch)
        endpoint = f"/api/v1/patients/{patient_id}"
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out = service.patch_patient(patient_id, patch)
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "concurenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            if "inexistent" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.delete("/api/v1/patients/{patient_id}")
    def delete_patient(
        patient_id: int,
        actor: RequestActor = Depends(require_roles("admin")),
        expected_updated_at: str = Header(default="", alias="X-Expected-Updated-At"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/patients/{patient_id}"
        expected = (expected_updated_at or "").strip()
        body = {"patient_id": int(patient_id), "expected_updated_at": expected}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            service.delete_patient(patient_id, expected_updated_at=expected)
        except ValueError as exc:
            msg = str(exc)
            lower_msg = msg.lower()
            if "concurenta" in lower_msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
            if "inexistent" in lower_msg:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        content = {"id": int(patient_id), "deleted": True}
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=content,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    @app.post("/api/v1/patients/{patient_id}/diagnosis-suggestions")
    def diagnosis_suggestions(
        patient_id: int,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ):
        endpoint = f"/api/v1/patients/{patient_id}/diagnosis-suggestions"
        body = {"patient_id": int(patient_id)}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            rows = service.diagnosis_suggestions(
                patient_id=patient_id,
                user_id=actor.user_id,
                correlation_id=request_correlation_id(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        payload = {"patient_id": patient_id, "suggestions": [_json_model(item) for item in rows]}
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=payload,
                user_id=actor.user_id,
            )
        return payload

    class EstimateRequest(PatientDiagnosisDto):
        pass

    @app.post("/api/v1/patients/{patient_id}/drg-icm-estimate")
    def drg_icm_estimate(
        patient_id: int,
        diagnosis: Optional[EstimateRequest] = None,
        actor: RequestActor = Depends(require_roles("admin", "medic")),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        endpoint = f"/api/v1/patients/{patient_id}/drg-icm-estimate"
        body = {"patient_id": int(patient_id), "diagnosis": _json_model(diagnosis) if diagnosis else {}}
        key = (idempotency_key or "").strip()
        if key:
            hit = _idempotency_hit(endpoint=endpoint, key=key, request_payload=body)
            if hit is not None:
                return hit
        try:
            out: DrgIcmEstimateDto = service.drg_icm_estimate(
                patient_id=patient_id,
                diagnosis=diagnosis,
                user_id=actor.user_id,
                correlation_id=request_correlation_id(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        payload = _json_model(out)
        if key:
            repository.save_idempotency(
                endpoint=endpoint,
                key=key,
                request_body=body,
                response_status=status.HTTP_200_OK,
                response_body=payload,
                user_id=actor.user_id,
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=payload)

    @app.get("/api/v1/ops/integration-queue")
    def integration_queue(
        limit: int = 200,
        status_filter: str = "",
        actor: RequestActor = Depends(require_roles("admin")),
    ):
        _ = actor
        rows = [IntegrationQueueItemDto(**item) for item in service.integration_queue(limit=limit, status=status_filter)]
        return {"timestamp": now_ts(), "items": [_json_model(item) for item in rows]}

    @app.get("/api/v1/ops/job-executions")
    def job_executions(
        limit: int = 200,
        job_name: str = "",
        actor: RequestActor = Depends(require_roles("admin")),
    ):
        _ = actor
        rows = service.job_executions(limit=limit, job_name=job_name)
        return {"timestamp": now_ts(), "items": rows}

    @app.get("/api/v1/ops/integration-dry-run-logs")
    def integration_dry_run_logs(
        limit: int = 200,
        provider: str = "",
        operation: str = "",
        actor: RequestActor = Depends(require_roles("admin")),
    ) -> Dict[str, Any]:
        _ = actor
        rows = service.integration_dry_run_logs(
            limit=max(1, int(limit)),
            provider=(provider or "").strip(),
            operation=(operation or "").strip(),
        )
        normalized = [IntegrationDryRunLogItemDto(**item) for item in rows]
        return {"timestamp": now_ts(), "items": [_json_model(item) for item in normalized]}

    def _shadow_backend_factory() -> Tuple[Dict[str, Any], PostgresShadowBackend]:
        settings = _shadow_runtime_settings()
        pg_backend = PostgresShadowBackend(
            dsn=(os.getenv("PACIENTI_POSTGRES_DSN") or "").strip(),
            connect_timeout_seconds=postgres_timeout,
        )
        return settings, pg_backend

    @app.get("/api/v1/ops/shadow-sync/status")
    def shadow_sync_status(
        actor: RequestActor = Depends(require_roles("admin")),
    ) -> Dict[str, Any]:
        _ = actor
        settings = _shadow_runtime_settings()
        status_payload = service.shadow_sync_status(lookback_hours=24)
        return {
            "timestamp": now_ts(),
            "shadow_mode_enabled": bool(settings.get("enabled", False)),
            "shadow_backlog_pending": int(status_payload.get("backlog_pending") or 0),
            "shadow_last_sync_at": str(status_payload.get("last_sync_at") or ""),
            "shadow_error_rate_24h": float(status_payload.get("error_rate_24h") or 0.0),
            "attempted_24h": int(status_payload.get("attempted_24h") or 0),
            "failed_24h": int(status_payload.get("failed_24h") or 0),
            "settings": {
                "max_retries": int(settings.get("max_retries") or 0),
                "batch_size": int(settings.get("batch_size") or 0),
                "interval_seconds": int(settings.get("interval_seconds") or 0),
                "stop_on_error_rate": float(settings.get("stop_on_error_rate") or 0.0),
            },
        }

    @app.post("/api/v1/ops/shadow-sync/process")
    def shadow_sync_process(
        max_jobs: int = 0,
        actor: RequestActor = Depends(require_roles("admin")),
    ) -> Dict[str, Any]:
        _ = actor
        settings, backend = _shadow_backend_factory()
        if not bool(settings.get("enabled", False)):
            return {
                "timestamp": now_ts(),
                "processed": 0,
                "synced": 0,
                "retried": 0,
                "failed": 0,
                "auto_stopped": False,
                "shadow_mode_enabled": False,
                "message": "Shadow mode este dezactivat.",
            }
        batch_size = int(settings.get("batch_size") or 50)
        target_jobs = max(1, int(max_jobs or batch_size))
        summary = process_shadow_sync_with_backend(
            db=db,
            backend=backend,
            max_jobs=target_jobs,
            max_retries=int(settings.get("max_retries") or 3),
            stop_on_error_rate=float(settings.get("stop_on_error_rate") or 0.5),
        )
        if bool(summary.get("auto_stopped", False)):
            try:
                db.set_setting("API_INTERNAL_POSTGRES_SHADOW_ENABLED", "0")
            except Exception:
                pass
        summary["timestamp"] = now_ts()
        summary["shadow_mode_enabled"] = not bool(summary.get("auto_stopped", False))
        return summary

    @app.get("/api/v1/ops/shadow-sync/errors")
    def shadow_sync_errors(
        limit: int = 200,
        actor: RequestActor = Depends(require_roles("admin")),
    ) -> Dict[str, Any]:
        _ = actor
        rows = service.shadow_sync_errors(limit=max(1, int(limit)))
        return {"timestamp": now_ts(), "items": rows}

    @app.get("/api/v1")
    def api_root() -> Dict[str, Any]:
        return {
            "app": "PacientiAIIndependent Enterprise API",
            "version": "1.0.0",
            "timestamp": now_ts(),
            "data_dir": str(APP_DIR),
        }

    return app


def request_correlation_id() -> str:
    from pacienti_ai_independent.observability import get_correlation_id

    return get_correlation_id() or uuid.uuid4().hex
