from __future__ import annotations

from typing import Any, Dict, Optional

from .contracts import ProcessSummary


class IntegrationDispatcher:
    def __init__(
        self,
        *,
        db: Any,
        siui_client: Optional[Any] = None,
        medis_client: Optional[Any] = None,
        lease_seconds: int = 120,
    ) -> None:
        self.db = db
        self.siui_client = siui_client
        self.medis_client = medis_client
        self.lease_seconds = max(10, int(lease_seconds))

    def enqueue(self, job: Dict[str, Any]) -> int:
        return int(
            self.db.enqueue_integration_job(
                provider=str(job.get("provider") or "").strip(),
                operation=str(job.get("operation") or "").strip(),
                entity_type=str(job.get("entity_type") or "").strip(),
                entity_id=int(job.get("entity_id") or 0),
                payload_json=str(job.get("payload_json") or "").strip(),
                idempotency_key=str(job.get("idempotency_key") or "").strip(),
            )
        )

    def process_due_jobs(self, *, max_jobs: int, lease_owner: str) -> ProcessSummary:
        summary = ProcessSummary()
        rows = self.db.claim_due_integration_jobs(
            max_jobs=max_jobs,
            lease_owner=lease_owner,
            lease_seconds=self.lease_seconds,
        )
        for row in rows:
            summary.processed += 1
            job_id = int(row["id"])
            summary.last_job_id = job_id
            provider = str(row.get("provider") or "").strip().lower()
            operation = str(row.get("operation") or "").strip().lower()
            try:
                if provider == "siui_drg" and operation == "submit_report":
                    self._process_submit_report(row, summary)
                elif provider == "medis" and operation == "submit_order":
                    self._process_submit_order(row, summary)
                else:
                    self.db.mark_integration_job_failed_permanent(
                        job_id=job_id,
                        http_code=0,
                        error=f"Job necunoscut: {provider}/{operation}",
                        response_payload="",
                    )
                    summary.permanent_failures += 1
            except Exception as exc:  # pragma: no cover - defensive fallback
                self.db.mark_integration_job_failed_retry(
                    job_id=job_id,
                    http_code=0,
                    error=f"Dispatcher exception: {exc}",
                    response_payload="",
                )
                summary.retriable_failures += 1
                summary.last_error = str(exc)
        return summary

    def _process_submit_report(self, row: Any, summary: ProcessSummary) -> None:
        job_id = int(row["id"])
        if self.siui_client is None:
            self.db.mark_integration_job_failed_retry(
                job_id=job_id,
                http_code=0,
                error="SIUI/DRG client indisponibil.",
                response_payload="",
            )
            summary.retriable_failures += 1
            return
        payload = self.db.integration_payload_to_dict(str(row.get("payload_json") or ""))
        report_type = str(payload.get("report_type") or "").strip().lower()
        report_payload = payload.get("payload")
        if not isinstance(report_payload, dict):
            self.db.mark_integration_job_failed_permanent(
                job_id=job_id,
                http_code=0,
                error="Payload SIUI/DRG invalid.",
                response_payload="",
            )
            summary.permanent_failures += 1
            return
        result = self.siui_client.submit_report(
            report_type=report_type,
            payload=report_payload,
            idempotency_key=str(row.get("idempotency_key") or ""),
        )
        if result.ok:
            ext_ref = (
                str(result.external_reference or "")
                or str(payload.get("external_reference_hint") or "")
                or f"{report_type.upper()}-{int(row.get('entity_id') or 0)}-{job_id}"
            )
            self.db.mark_institutional_report_submitted_transport(
                report_id=int(row.get("entity_id") or 0),
                external_reference=ext_ref,
                ack_payload=str(result.ack_payload or ""),
                http_code=int(result.http_code or 0),
            )
            self.db.mark_integration_job_success(
                job_id=job_id,
                http_code=int(result.http_code or 0),
                response_payload=str(result.response_payload or ""),
            )
            summary.success += 1
            return
        if result.retriable:
            self.db.mark_integration_job_failed_retry(
                job_id=job_id,
                http_code=int(result.http_code or 0),
                error=str(result.error or "SIUI/DRG transport retriable failure."),
                response_payload=str(result.response_payload or ""),
            )
            summary.retriable_failures += 1
            summary.last_error = str(result.error or "")
            return
        self.db.mark_integration_job_failed_permanent(
            job_id=job_id,
            http_code=int(result.http_code or 0),
            error=str(result.error or "SIUI/DRG transport permanent failure."),
            response_payload=str(result.response_payload or ""),
        )
        self.db.set_institutional_report_transport_state(
            report_id=int(row.get("entity_id") or 0),
            transport_state="failed",
            http_code=int(result.http_code or 0),
            error=str(result.error or "SIUI/DRG permanent failure."),
        )
        summary.permanent_failures += 1
        summary.last_error = str(result.error or "")

    def _process_submit_order(self, row: Any, summary: ProcessSummary) -> None:
        job_id = int(row["id"])
        if self.medis_client is None:
            self.db.mark_integration_job_failed_retry(
                job_id=job_id,
                http_code=0,
                error="MEDIS client indisponibil.",
                response_payload="",
            )
            summary.retriable_failures += 1
            return
        payload = self.db.integration_payload_to_dict(str(row.get("payload_json") or ""))
        request_payload = payload.get("payload")
        if not isinstance(request_payload, dict):
            self.db.mark_integration_job_failed_permanent(
                job_id=job_id,
                http_code=0,
                error="Payload MEDIS invalid.",
                response_payload="",
            )
            summary.permanent_failures += 1
            return
        result = self.medis_client.submit_order(
            payload=request_payload,
            idempotency_key=str(row.get("idempotency_key") or ""),
        )
        investigation_id = int(row.get("entity_id") or 0)
        if result.ok:
            ext_ref = str(result.external_reference or payload.get("external_request_id") or "").strip()
            self.db.mark_medis_investigation_sent_transport(
                investigation_id=investigation_id,
                external_request_id=ext_ref,
                http_code=int(result.http_code or 0),
                ack_payload=str(result.ack_payload or ""),
            )
            self.db.mark_integration_job_success(
                job_id=job_id,
                http_code=int(result.http_code or 0),
                response_payload=str(result.response_payload or ""),
            )
            summary.success += 1
            return
        if result.retriable:
            self.db.mark_integration_job_failed_retry(
                job_id=job_id,
                http_code=int(result.http_code or 0),
                error=str(result.error or "MEDIS transport retriable failure."),
                response_payload=str(result.response_payload or ""),
            )
            self.db.set_medis_investigation_transport_state(
                investigation_id=investigation_id,
                transport_state="pending_retry",
                status="queued",
                http_code=int(result.http_code or 0),
                error=str(result.error or "MEDIS retry pending."),
            )
            summary.retriable_failures += 1
            summary.last_error = str(result.error or "")
            return
        self.db.mark_integration_job_failed_permanent(
            job_id=job_id,
            http_code=int(result.http_code or 0),
            error=str(result.error or "MEDIS transport permanent failure."),
            response_payload=str(result.response_payload or ""),
        )
        self.db.set_medis_investigation_transport_state(
            investigation_id=investigation_id,
            transport_state="failed",
            status="send_failed",
            http_code=int(result.http_code or 0),
            error=str(result.error or "MEDIS permanent failure."),
        )
        summary.permanent_failures += 1
        summary.last_error = str(result.error or "")
