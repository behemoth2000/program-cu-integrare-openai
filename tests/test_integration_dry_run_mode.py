import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pacienti_ai_independent.integrations.contracts import MedisResult, TransportResult
from pacienti_ai_independent.integrations.medis_client import MedisClient
from pacienti_ai_independent.integrations.siui_drg_client import SiuiDrgClient
from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class IntegrationDryRunModeTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_dry_run_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_siui_client_sets_dry_run_header_and_flag(self) -> None:
        client = SiuiDrgClient(
            base_url="https://sandbox.siui",
            endpoint_siui_submit="/siui/submit",
            endpoint_drg_submit="/drg/submit",
            auth_type="none",
            client_id="",
            client_secret="",
            api_key="",
            bearer_token="",
            timeout_seconds=10,
            max_retries=0,
            retry_base_seconds=1.0,
            dry_run=True,
        )
        seen = {}

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            seen["headers"] = dict(kwargs.get("headers") or {})
            return TransportResult(ok=True, http_code=200, response_payload='{"external_reference":"ACK"}')

        with patch.object(client.http, "request_json", _fake_request_json):
            result = client.submit_report("siui", {"demo": 1}, "idem-1")
        self.assertEqual("1", str(seen.get("headers", {}).get("X-Dry-Run") or ""))
        self.assertTrue(bool(result.dry_run))

    def test_medis_client_sets_dry_run_header(self) -> None:
        client = MedisClient(
            base_url="https://sandbox.medis",
            endpoint_order_submit="/orders/submit",
            endpoint_results_pull="/results/pull",
            auth_type="none",
            client_id="",
            client_secret="",
            api_key="",
            bearer_token="",
            timeout_seconds=10,
            max_retries=0,
            retry_base_seconds=1.0,
            dry_run=True,
        )
        seen = {}

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            seen["submit_headers"] = dict(kwargs.get("headers") or {})
            return TransportResult(ok=True, http_code=200, response_payload='{"external_request_id":"REQ-1"}')

        def _fake_get_json(**kwargs):  # type: ignore[no-untyped-def]
            seen["pull_headers"] = dict(kwargs.get("headers") or {})
            return TransportResult(ok=True, http_code=200, response_payload='[{"result_id":"R1","request_id":"REQ-1"}]')

        with patch.object(client.http, "request_json", _fake_request_json), patch.object(client.http, "get_json", _fake_get_json):
            submit_res = client.submit_order({"demo": 1}, "idem-2")
            pulled = client.pull_results(since_ts=now_ts(), limit=10)
        self.assertEqual("1", str(seen.get("submit_headers", {}).get("X-Dry-Run") or ""))
        self.assertEqual("1", str(seen.get("pull_headers", {}).get("X-Dry-Run") or ""))
        self.assertTrue(bool(submit_res.dry_run))
        self.assertTrue(isinstance(pulled, list))

    def test_dry_run_logs_are_separate_from_operational_status(self) -> None:
        patient_id = self.db.create_patient(
            {
                "first_name": "Dry",
                "last_name": "Run",
                "cnp": "",
                "phone": "",
                "email": "",
                "birth_date": "",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "primary_diagnosis_icd10": "",
                "secondary_diagnoses_icd10": "",
                "free_diagnosis_text": "",
                "gender": "",
                "occupation": "",
                "insurance_provider": "",
                "insurance_id": "",
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
                "bed": "5",
                "attending_clinician": "Dr Dry",
                "chief_complaint": "test",
                "admitted_at": now_ts(),
            },
            user_id=1,
        )
        report_id = self.db.create_institutional_report(admission_id=admission_id, report_type="siui", user_id=1)
        report_before = self.db.get_institutional_report(report_id)

        _ = self.db.log_integration_dry_run(
            provider="siui_drg",
            operation="submit_siui",
            endpoint="https://sandbox/siui",
            request_payload='{"dry":true}',
            response_payload='{"ok":true}',
            http_code=200,
            latency_ms=12,
            ok=True,
            error_text="",
            correlation_id="corr-dry-1",
            user_id=1,
        )
        dry_rows = self.db.list_integration_dry_run_logs(limit=10)
        self.assertGreaterEqual(len(dry_rows), 1)

        report_after = self.db.get_institutional_report(report_id)
        self.assertEqual(str(report_before["status"]), str(report_after["status"]))
        self.assertEqual(str(report_before["transport_state"]), str(report_after["transport_state"]))


if __name__ == "__main__":
    unittest.main()
