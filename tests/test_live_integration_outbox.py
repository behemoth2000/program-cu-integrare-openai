import os
import tempfile
import unittest
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.integrations.contracts import TransportResult
from pacienti_ai_independent.integrations.dispatcher import IntegrationDispatcher
from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class LiveIntegrationOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_live_outbox_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_enqueue_idempotency(self) -> None:
        payload_json = '{"k":"v"}'
        idem = "idem-001"
        job1 = self.db.enqueue_integration_job(
            provider="siui_drg",
            operation="submit_report",
            entity_type="institutional_report",
            entity_id=11,
            payload_json=payload_json,
            idempotency_key=idem,
        )
        job2 = self.db.enqueue_integration_job(
            provider="siui_drg",
            operation="submit_report",
            entity_type="institutional_report",
            entity_id=11,
            payload_json=payload_json,
            idempotency_key=idem,
        )
        self.assertEqual(job1, job2)

    def test_claim_and_mark_retry_and_failed(self) -> None:
        job_id = self.db.enqueue_integration_job(
            provider="medis",
            operation="submit_order",
            entity_type="medis_investigation",
            entity_id=21,
            payload_json='{"payload":{"test":1}}',
            idempotency_key="idem-002",
        )
        claimed = self.db.claim_due_integration_jobs(max_jobs=10, lease_owner="unit-test", lease_seconds=60)
        self.assertEqual(1, len(claimed))
        self.assertEqual(job_id, int(claimed[0]["id"]))

        self.db.mark_integration_job_failed_retry(
            job_id=job_id,
            http_code=503,
            error="service unavailable",
            response_payload='{"error":"503"}',
        )
        errors = self.db.list_integration_errors(limit=10)
        self.assertEqual(1, len(errors))
        self.assertEqual("retry", str(errors[0]["status"]))
        self.assertEqual(503, int(errors[0]["last_http_code"]))

        self.db.mark_integration_job_failed_permanent(
            job_id=job_id,
            http_code=400,
            error="bad request",
            response_payload='{"error":"400"}',
        )
        errors2 = self.db.list_integration_errors(limit=10)
        self.assertEqual(1, len(errors2))
        self.assertEqual("failed", str(errors2[0]["status"]))

    def test_mark_success_removes_from_errors(self) -> None:
        job_id = self.db.enqueue_integration_job(
            provider="medis",
            operation="submit_order",
            entity_type="medis_investigation",
            entity_id=22,
            payload_json='{"payload":{"test":1}}',
            idempotency_key="idem-003",
        )
        self.db.mark_integration_job_failed_retry(
            job_id=job_id,
            http_code=502,
            error="gateway",
            response_payload="",
        )
        self.assertEqual(1, len(self.db.list_integration_errors(limit=10)))
        self.db.mark_integration_job_success(
            job_id=job_id,
            http_code=200,
            response_payload='{"ok":true}',
        )
        self.assertEqual(0, len(self.db.list_integration_errors(limit=10)))

    def test_legacy_medis_table_without_external_result_id_is_migrated(self) -> None:
        legacy_path = Path(tempfile.gettempdir()) / f"pacienti_ai_legacy_medis_{uuid4().hex}.db"
        try:
            conn = sqlite3.connect(str(legacy_path))
            conn.execute(
                """
                CREATE TABLE medis_investigations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    patient_id INTEGER NOT NULL,
                    admission_id INTEGER,
                    provider TEXT NOT NULL DEFAULT 'MEDIS',
                    external_request_id TEXT NOT NULL DEFAULT '',
                    requested_at TEXT NOT NULL,
                    request_payload TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'sent',
                    result_received_at TEXT NOT NULL DEFAULT '',
                    result_summary TEXT NOT NULL DEFAULT '',
                    result_flag TEXT NOT NULL DEFAULT '',
                    result_payload TEXT NOT NULL DEFAULT '',
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()

            migrated = Database(legacy_path)
            with migrated._connect() as check_conn:
                cols = {
                    str(row[1]).strip().lower()
                    for row in check_conn.execute("PRAGMA table_info(medis_investigations)").fetchall()
                }
            self.assertIn("external_result_id", cols)
        finally:
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except PermissionError:
                    pass

    def test_dispatcher_retry_then_success_updates_report(self) -> None:
        patient_id = self.db.create_patient(
            {
                "first_name": "Alin",
                "last_name": "Retry",
                "cnp": "1980101223344",
                "phone": "",
                "email": "",
                "birth_date": "1980-01-01",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "gender": "M",
                "occupation": "",
                "insurance_provider": "CNAS",
                "insurance_id": "INS-123",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "blood_type": "",
                "height_cm": "",
                "weight_kg": "",
                "surgeries": "",
                "family_history": "",
                "lifestyle_notes": "",
            }
        )
        admission_id, _ = self.db.create_admission(
            {
                "patient_id": str(patient_id),
                "admission_type": "inpatient",
                "triage_level": "3",
                "department": "Ortopedie",
                "ward": "A",
                "bed": "7",
                "attending_clinician": "Dr Retry",
                "chief_complaint": "durere",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        self.db.upsert_admission_diagnoses(
            admission_id,
            {
                "referral_diagnosis": "M16",
                "admission_diagnosis": "M16",
                "discharge_diagnosis": "M16",
                "secondary_diagnoses": "",
                "dietary_regimen": "Normal",
                "admission_criteria": "criteriu",
                "discharge_criteria": "criteriu",
            },
            user_id=None,
        )
        self.db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Ortopedie",
                "ward": "A",
                "bed": "7",
                "operating_room": "",
                "attending_clinician": "Dr Retry",
                "starts_at": now_ts(),
                "ends_at": "2099-01-01 00:00:00",
                "notes": "",
            },
            user_id=None,
        )
        self.db.discharge_admission(admission_id, "Externare pentru test retry.")
        self.db.create_billing_record(
            admission_id=admission_id,
            record_type="final",
            amount=500.0,
            issued_at=now_ts(),
            notes="decont",
            user_id=None,
        )
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="final",
            series="FCT",
            invoice_number=f"R-{admission_id}",
            subtotal=450.0,
            tax_amount=50.0,
            total_amount=None,
            issued_at=now_ts(),
            due_date="2099-01-01",
            status="issued",
            notes="final",
            user_id=None,
        )
        self.db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=500.0,
            paid_at=now_ts(),
            payment_method="card",
            reference_no="R-1",
            notes="achitat",
            user_id=None,
        )
        report_id = self.db.create_institutional_report(
            admission_id=admission_id,
            report_type="siui",
            user_id=None,
        )
        report = self.db.get_institutional_report(report_id)
        payload = json.loads(str(report["payload_json"]))
        job_id = self.db.enqueue_integration_job(
            provider="siui_drg",
            operation="submit_report",
            entity_type="institutional_report",
            entity_id=report_id,
            payload_json=json.dumps({"report_type": "siui", "payload": payload}, ensure_ascii=False),
            idempotency_key=f"idem-retry-{report_id}",
        )

        class _FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def submit_report(self, report_type, payload, idempotency_key):  # type: ignore[no-untyped-def]
                _ = report_type, payload, idempotency_key
                self.calls += 1
                if self.calls == 1:
                    return TransportResult(
                        ok=False,
                        http_code=503,
                        retriable=True,
                        error="HTTP 503",
                        response_payload='{"error":"temp"}',
                    )
                return TransportResult(
                    ok=True,
                    http_code=200,
                    retriable=False,
                    external_reference="SIUI-RETRY-ACK",
                    response_payload='{"external_reference":"SIUI-RETRY-ACK"}',
                    ack_payload='{"external_reference":"SIUI-RETRY-ACK"}',
                )

        fake_client = _FakeClient()
        dispatcher = IntegrationDispatcher(db=self.db, siui_client=fake_client, lease_seconds=30)

        first = dispatcher.process_due_jobs(max_jobs=10, lease_owner="t1")
        self.assertEqual(1, first.processed)
        self.assertEqual(1, first.retriable_failures)
        self.assertEqual(0, first.success)

        with self.db._connect() as conn:
            conn.execute(
                "UPDATE integration_outbox SET next_retry_at = ?, status = 'retry' WHERE id = ?",
                (now_ts(), job_id),
            )
            conn.commit()

        second = dispatcher.process_due_jobs(max_jobs=10, lease_owner="t2")
        self.assertEqual(1, second.processed)
        self.assertEqual(1, second.success)

        refreshed_report = self.db.get_institutional_report(report_id)
        self.assertEqual("submitted", refreshed_report["status"])
        self.assertEqual("submitted", refreshed_report["transport_state"])
        self.assertEqual("SIUI-RETRY-ACK", refreshed_report["external_reference"])

        with self.db._connect() as conn:
            row = conn.execute("SELECT status FROM integration_outbox WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual("done", row["status"])


if __name__ == "__main__":
    unittest.main()
