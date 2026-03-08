import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.integrations.contracts import TransportResult
from pacienti_ai_independent.integrations.medis_client import MedisClient
from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class MedisLiveSubmitAndPullTest(unittest.TestCase):
    def _build_client(self) -> MedisClient:
        return MedisClient(
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
            retry_base_seconds=0.1,
        )

    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_medis_live_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def _create_patient_and_admission(self) -> tuple[int, int]:
        patient_id = self.db.create_patient(
            {
                "first_name": "Lia",
                "last_name": "Matei",
                "cnp": "2980101223344",
                "phone": "",
                "email": "",
                "birth_date": "1998-01-01",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "gender": "F",
                "occupation": "",
                "insurance_provider": "CNAS",
                "insurance_id": "ABCD",
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
                "attending_clinician": "Dr Test",
                "chief_complaint": "durere",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def test_submit_order_extracts_external_reference(self) -> None:
        client = self._build_client()

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual("https://sandbox.medis/orders/submit", kwargs["url"])
            return TransportResult(
                ok=True,
                http_code=200,
                retriable=False,
                response_payload='{"external_request_id":"MED-REQ-1"}',
                ack_payload='{"external_request_id":"MED-REQ-1"}',
            )

        client.http.request_json = _fake_request_json  # type: ignore[assignment]
        res = client.submit_order({"order": {"id": 1}}, "idem")
        self.assertTrue(res.ok)
        self.assertEqual("MED-REQ-1", res.external_reference)

    def test_pull_results_and_apply_to_db(self) -> None:
        patient_id, admission_id = self._create_patient_and_admission()
        order_id = self.db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma",
            user_id=None,
        )
        inv_id = self.db.create_medis_investigation(
            order_id=order_id,
            provider="MEDIS",
            external_request_id="REQ-XYZ",
            requested_at=now_ts(),
            request_payload='{"panel":"cbc"}',
            user_id=None,
            initial_status="sent",
        )
        self.assertGreater(inv_id, 0)

        client = self._build_client()

        def _fake_get_json(**kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual("https://sandbox.medis/results/pull", kwargs["url"])
            self.assertEqual("2026-03-01 00:00:00", kwargs["query"]["since_ts"])
            self.assertEqual(50, kwargs["query"]["limit"])
            return TransportResult(
                ok=True,
                http_code=200,
                retriable=False,
                response_payload=(
                    '{"results":[{"external_result_id":"RES-1","external_request_id":"REQ-XYZ",'
                    '"result_summary":"Hb normal","result_flag":"normal",'
                    '"result_received_at":"2026-03-06 10:00:00"}]}'
                ),
            )

        client.http.get_json = _fake_get_json  # type: ignore[assignment]
        results = client.pull_results("2026-03-01 00:00:00", 50)
        self.assertEqual(1, len(results))
        applied = self.db.apply_medis_external_result(
            external_result_id=results[0].external_result_id,
            external_request_id=results[0].external_request_id,
            result_summary=results[0].result_summary,
            result_payload=results[0].result_payload,
            result_flag=results[0].result_flag,
            result_received_at=results[0].result_received_at,
        )
        self.assertEqual(inv_id, applied)
        refreshed = self.db.get_medis_investigation(inv_id)
        self.assertEqual("result_received", refreshed["status"])
        self.assertEqual("RES-1", refreshed["external_result_id"])
        order = self.db.get_order_by_id(order_id)
        self.assertEqual("done", order["status"])


if __name__ == "__main__":
    unittest.main()
