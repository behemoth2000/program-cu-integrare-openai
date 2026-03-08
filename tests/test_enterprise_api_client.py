import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from pacienti_ai_independent.api.client import EnterpriseApiClient
from pacienti_ai_independent.observability import set_correlation_id


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class EnterpriseApiClientTest(unittest.TestCase):
    def test_diagnosis_suggestions_success(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        client.set_actor(user_id=7, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            header_map = {str(k).lower(): str(v) for k, v in req.header_items()}
            seen["role"] = header_map.get("x-role")
            seen["user"] = header_map.get("x-user-id")
            seen["idem"] = header_map.get("idempotency-key")
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "patient_id": 11,
                    "suggestions": [
                        {"code": "I10", "title": "HTA", "severity": "CC", "confidence": 0.82, "evidence": "rule"},
                        {"code": "E11", "title": "DZ", "severity": "CC", "confidence": 0.61, "evidence": "rule"},
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.diagnosis_suggestions(patient_id=11, idempotency_key="idem-diag-001")
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/11/diagnosis-suggestions", seen["url"])
        self.assertEqual("POST", seen["method"])
        self.assertEqual("medic", str(seen["role"]).lower())
        self.assertEqual("7", str(seen["user"]))
        self.assertEqual("idem-diag-001", str(seen["idem"] or ""))
        self.assertEqual(8, int(seen["timeout"]))
        self.assertEqual(2, len(rows))
        self.assertEqual("I10", rows[0]["code"])

    def test_drg_estimate_http_error_is_parsed(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            header_map = {str(k).lower(): str(v) for k, v in req.header_items()}
            seen["idem"] = header_map.get("idempotency-key")
            seen["timeout"] = timeout
            raise urllib.error.HTTPError(
                url="http://127.0.0.1:8000/api/v1/patients/11/drg-icm-estimate",
                code=422,
                msg="Unprocessable",
                hdrs=None,
                fp=io.BytesIO(b'{"detail":"payload invalid"}'),
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            with self.assertRaises(RuntimeError) as ctx:
                client.drg_icm_estimate(
                    patient_id=11,
                    primary_icd10="I10",
                    secondary_icd10=["E11"],
                    free_text="",
                    idempotency_key="idem-drg-001",
                )
        self.assertEqual("idem-drg-001", str(seen.get("idem") or ""))
        self.assertEqual(8, int(seen.get("timeout") or 0))
        self.assertIn("HTTP 422", str(ctx.exception))
        self.assertIn("payload invalid", str(ctx.exception))

    def test_not_ready_raises(self) -> None:
        client = EnterpriseApiClient(base_url="", timeout_seconds=8, enabled=False)
        with self.assertRaises(RuntimeError):
            client.diagnosis_suggestions(patient_id=10)

    def test_create_and_patch_patient_calls_expected_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=9, enabled=True)
        client.set_actor(user_id=9, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            body = req.data.decode("utf-8") if req.data else ""
            header_map = {str(k).lower(): str(v) for k, v in req.header_items()}
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": body,
                    "headers": header_map,
                }
            )
            if req.get_method() == "POST":
                return _FakeResponse({"id": 101, "first_name": "Ana", "last_name": "Pop", "diagnosis": {}})
            return _FakeResponse({"id": 101, "first_name": "Ana2", "last_name": "Pop", "diagnosis": {}})

        with patch("urllib.request.urlopen", _fake_urlopen):
            created = client.create_patient(payload={"first_name": "Ana", "last_name": "Pop", "diagnosis": {}})
            patched = client.patch_patient(
                patient_id=101,
                payload={"first_name": "Ana2", "diagnosis": {}},
                expected_updated_at="2026-03-06 19:00:00",
            )

        self.assertEqual(2, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients", calls[0]["url"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/101", calls[1]["url"])
        self.assertEqual("PATCH", calls[1]["method"])
        self.assertEqual(9, int(calls[0]["timeout"]))
        self.assertEqual(101, int(created["id"]))
        self.assertEqual("Ana2", str(patched["first_name"]))
        self.assertIn("expected_updated_at", str(calls[1]["body"]))

    def test_list_patients_uses_query_filters(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=7, enabled=True)
        client.set_actor(user_id=3, role="receptie")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 77,
                            "first_name": "Ion",
                            "last_name": "Pop",
                            "phone": "0711",
                            "email": "ion@example.com",
                            "reception_flag": "Internat",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_patients(search="ion", status_filter="active_admission", status_date="2026-03-06")
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/patients?search=ion&status_filter=active_admission&status_date=2026-03-06",
            seen["url"],
        )
        self.assertEqual("GET", seen["method"])
        self.assertEqual(7, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual(77, int(rows[0]["id"]))
        self.assertEqual("Internat", rows[0]["reception_flag"])

    def test_dashboard_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=6, enabled=True)
        client.set_actor(user_id=3, role="medic")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout})
            if "/dashboard/kpis" in req.full_url:
                return _FakeResponse(
                    {
                        "kpi": {
                            "active_admissions": 5,
                            "triage_1_2": 2,
                            "urgent_orders": 3,
                            "vital_alerts_24h": 1,
                        }
                    }
                )
            if "/dashboard/active-admissions" in req.full_url:
                return _FakeResponse(
                    {
                        "items": [
                            {
                                "id": 401,
                                "patient_id": 9,
                                "mrn": "MRN-401",
                                "admission_type": "inpatient",
                                "triage_level": "2",
                                "department": "Ortopedie",
                                "ward": "A2",
                                "bed": "12",
                                "attending_clinician": "Dr X",
                                "chief_complaint": "durere",
                                "admitted_at": "2026-03-06 09:00:00",
                                "first_name": "Ana",
                                "last_name": "Pop",
                                "cnp": "2990101123456",
                            }
                        ]
                    }
                )
            if "/dashboard/urgent-orders" in req.full_url:
                return _FakeResponse(
                    {
                        "items": [
                            {
                                "id": 33,
                                "patient_id": 9,
                                "admission_id": 401,
                                "order_type": "lab",
                                "priority": "urgent",
                                "status": "ordered",
                                "ordered_at": "2026-03-06 11:40:00",
                                "order_text": "Hemoleucograma",
                                "mrn": "MRN-401",
                                "department": "Ortopedie",
                                "first_name": "Ana",
                                "last_name": "Pop",
                            }
                        ]
                    }
                )
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 44,
                            "patient_id": 9,
                            "admission_id": 401,
                            "recorded_at": "2026-03-06 12:00:00",
                            "temperature_c": "39.2",
                            "systolic_bp": "120",
                            "diastolic_bp": "80",
                            "pulse": "95",
                            "respiratory_rate": "18",
                            "spo2": "98",
                            "pain_score": "3",
                            "notes": "febra",
                            "mrn": "MRN-401",
                            "department": "Ortopedie",
                            "first_name": "Ana",
                            "last_name": "Pop",
                            "reasons": "temp=39.2",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            kpi = client.get_dashboard_kpis(department="Ortopedie")
            admissions = client.list_dashboard_active_admissions(department="Ortopedie", limit=50)
            orders = client.list_dashboard_urgent_orders(department="Ortopedie", limit=60)
            alerts = client.list_dashboard_vital_alerts(department="Ortopedie", hours=24, limit=70)

        self.assertEqual(4, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/dashboard/kpis?department=Ortopedie", calls[0]["url"])
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/dashboard/active-admissions?limit=50&department=Ortopedie",
            calls[1]["url"],
        )
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/dashboard/urgent-orders?limit=60&department=Ortopedie",
            calls[2]["url"],
        )
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/dashboard/vital-alerts?hours=24&limit=70&department=Ortopedie",
            calls[3]["url"],
        )
        self.assertEqual(5, int(kpi["active_admissions"]))
        self.assertEqual(1, len(admissions))
        self.assertEqual(401, int(admissions[0]["id"]))
        self.assertEqual(1, len(orders))
        self.assertEqual(33, int(orders[0]["id"]))
        self.assertEqual(1, len(alerts))
        self.assertEqual("temp=39.2", alerts[0]["reasons"])

    def test_delete_patient_calls_expected_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=6, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            seen["headers"] = {str(k).lower(): str(v) for k, v in req.header_items()}
            return _FakeResponse({"id": 15, "deleted": True})

        with patch("urllib.request.urlopen", _fake_urlopen):
            response = client.delete_patient(
                patient_id=15,
                expected_updated_at="2026-03-06 10:00:00",
                idempotency_key="idem-delete-001",
            )
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/15", seen["url"])
        self.assertEqual("DELETE", seen["method"])
        self.assertEqual(6, int(seen["timeout"]))
        self.assertEqual("2026-03-06 10:00:00", str(seen["headers"].get("x-expected-updated-at") or ""))
        self.assertEqual("idem-delete-001", str(seen["headers"].get("idempotency-key") or ""))
        self.assertEqual(15, int(response["id"]))
        self.assertTrue(bool(response["deleted"]))

    def test_request_uses_existing_correlation_id_header(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=6, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}
        set_correlation_id("corr-client-001")

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["headers"] = {str(k).lower(): str(v) for k, v in req.header_items()}
            seen["timeout"] = timeout
            return _FakeResponse({"status": "ok", "timestamp": "2026-03-06 22:00:00", "checks": {}})

        try:
            with patch("urllib.request.urlopen", _fake_urlopen):
                _ = client.get_health()
        finally:
            set_correlation_id("")
        self.assertEqual(6, int(seen["timeout"]))
        self.assertEqual("corr-client-001", str(seen["headers"].get("x-correlation-id") or ""))

    def test_request_generates_correlation_id_when_missing(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=6, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}
        set_correlation_id("")

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["headers"] = {str(k).lower(): str(v) for k, v in req.header_items()}
            return _FakeResponse({"status": "ok", "timestamp": "2026-03-06 22:00:00", "checks": {}})

        try:
            with patch("urllib.request.urlopen", _fake_urlopen):
                _ = client.get_health()
        finally:
            set_correlation_id("")
        corr = str(seen["headers"].get("x-correlation-id") or "")
        self.assertTrue(bool(corr.strip()))

    def test_list_and_get_active_admission_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=5, enabled=True)
        client.set_actor(user_id=2, role="medic")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout})
            if req.full_url.endswith("/admissions/active"):
                return _FakeResponse(
                    {
                        "patient_id": 9,
                        "item": {
                            "id": 401,
                            "mrn": "MRN-2026-000401",
                            "admission_type": "inpatient",
                            "triage_level": "2",
                            "department": "Ortopedie",
                            "ward": "A2",
                            "bed": "12",
                            "attending_clinician": "Dr. X",
                            "chief_complaint": "durere",
                            "status": "active",
                            "admitted_at": "2026-03-06 09:00:00",
                            "discharged_at": "",
                            "discharge_summary": "",
                            "case_finalized_at": "",
                        },
                    }
                )
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 401,
                            "mrn": "MRN-2026-000401",
                            "admission_type": "inpatient",
                            "triage_level": "2",
                            "department": "Ortopedie",
                            "ward": "A2",
                            "bed": "12",
                            "attending_clinician": "Dr. X",
                            "chief_complaint": "durere",
                            "status": "active",
                            "admitted_at": "2026-03-06 09:00:00",
                            "discharged_at": "",
                            "discharge_summary": "",
                            "case_finalized_at": "",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_admissions(patient_id=9, include_closed=True, limit=200)
            active = client.get_active_admission(patient_id=9)

        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/patients/9/admissions?include_closed=1&limit=200",
            calls[0]["url"],
        )
        self.assertEqual("GET", calls[0]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/admissions/active", calls[1]["url"])
        self.assertEqual("GET", calls[1]["method"])
        self.assertEqual(1, len(rows))
        self.assertEqual(401, int(rows[0]["id"]))
        self.assertIsNotNone(active)
        self.assertEqual("MRN-2026-000401", str(active.get("mrn") if active else ""))

    def test_create_and_discharge_admission_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=7, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            body = req.data.decode("utf-8") if req.data else ""
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": body,
                    "headers": {str(k).lower(): str(v) for k, v in req.header_items()},
                }
            )
            if req.full_url.endswith("/api/v1/patients/9/admissions"):
                return _FakeResponse(
                    {
                        "admission_id": 401,
                        "patient_id": 9,
                        "mrn": "MRN-2026-000401",
                        "status": "active",
                        "admitted_at": "2026-03-07 08:00:00",
                        "completed_booking_id": 13,
                    }
                )
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "patient_id": 9,
                    "booking_id": 88,
                    "status": "discharged",
                    "discharged_at": "2026-03-07 14:00:00",
                    "discharge_summary": "externare test",
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            created = client.create_admission(
                patient_id=9,
                payload={
                    "admission_type": "inpatient",
                    "triage_level": "2",
                    "department": "Ortopedie",
                    "ward": "A2",
                    "bed": "12",
                    "attending_clinician": "Dr X",
                    "chief_complaint": "durere",
                    "admitted_at": "2026-03-07 08:00:00",
                },
                idempotency_key="idem-admission-create-001",
            )
            discharged = client.discharge_admission(
                admission_id=401,
                discharge_summary="externare test",
                idempotency_key="idem-admission-discharge-001",
            )

        self.assertEqual(2, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/admissions", calls[0]["url"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("idem-admission-create-001", str(calls[0]["headers"].get("idempotency-key") or ""))
        self.assertIn("triage_level", calls[0]["body"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/discharge", calls[1]["url"])
        self.assertEqual("POST", calls[1]["method"])
        self.assertEqual("idem-admission-discharge-001", str(calls[1]["headers"].get("idempotency-key") or ""))
        self.assertIn("discharge_summary", calls[1]["body"])
        self.assertEqual(401, int(created["admission_id"]))
        self.assertEqual(13, int(created["completed_booking_id"]))
        self.assertEqual(401, int(discharged["admission_id"]))
        self.assertEqual(88, int(discharged["booking_id"]))

    def test_transfer_and_case_finalize_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=7, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            body = req.data.decode("utf-8") if req.data else ""
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": body,
                    "headers": {str(k).lower(): str(v) for k, v in req.header_items()},
                }
            )
            if req.full_url.endswith("/transfer"):
                return _FakeResponse(
                    {
                        "admission_id": 401,
                        "patient_id": 9,
                        "department": "ATI",
                        "ward": "B1",
                        "bed": "5",
                        "transferred_at": "2026-03-07 12:00:00",
                    }
                )
            if "/case-validation" in req.full_url:
                return _FakeResponse(
                    {
                        "admission_id": 401,
                        "eligible": True,
                        "errors": [],
                        "finalized": False,
                        "finalized_at": "",
                    }
                )
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "finalized": True,
                    "finalized_at": "2026-03-07 16:00:00",
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            transfer = client.transfer_admission(
                admission_id=401,
                to_department="ATI",
                to_ward="B1",
                to_bed="5",
                transferred_at="2026-03-07 12:00:00",
                notes="transfer test",
                idempotency_key="idem-transfer-001",
            )
            validation = client.get_admission_case_validation(
                admission_id=401,
                require_financial_closure=True,
                require_siui_drg_submission=False,
            )
            finalized = client.finalize_admission_case(
                admission_id=401,
                require_financial_closure=True,
                require_siui_drg_submission=False,
                idempotency_key="idem-finalize-001",
            )

        self.assertEqual(3, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/transfer", calls[0]["url"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("idem-transfer-001", str(calls[0]["headers"].get("idempotency-key") or ""))
        self.assertIn("to_department", calls[0]["body"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/case-validation?require_financial_closure=1&require_siui_drg_submission=0", calls[1]["url"])
        self.assertEqual("GET", calls[1]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/finalize-case", calls[2]["url"])
        self.assertEqual("POST", calls[2]["method"])
        self.assertEqual("idem-finalize-001", str(calls[2]["headers"].get("idempotency-key") or ""))
        self.assertIn("require_financial_closure", calls[2]["body"])
        self.assertEqual("ATI", transfer["department"])
        self.assertTrue(bool(validation["eligible"]))
        self.assertTrue(bool(finalized["finalized"]))

    def test_save_diagnoses_and_issue_billing_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=7, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            body = req.data.decode("utf-8") if req.data else ""
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": body,
                    "headers": {str(k).lower(): str(v) for k, v in req.header_items()},
                }
            )
            if req.full_url.endswith("/diagnoses"):
                return _FakeResponse(
                    {
                        "admission_id": 401,
                        "updated_at": "2026-03-07 12:10:00",
                        "updated_by_user_id": 1,
                    }
                )
            return _FakeResponse(
                {
                    "billing_id": 77,
                    "admission_id": 401,
                    "patient_id": 9,
                    "record_type": "final",
                    "amount": 123.45,
                    "currency": "RON",
                    "issued_at": "2026-03-07 13:00:00",
                    "status": "issued",
                    "cost_center_id": 2,
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            saved = client.save_admission_diagnoses(
                admission_id=401,
                payload={
                    "referral_diagnosis": "R51",
                    "admission_diagnosis": "I10",
                    "discharge_diagnosis": "I10",
                    "secondary_diagnoses": "E11",
                    "dietary_regimen": "standard",
                    "admission_criteria": "criteria A",
                    "discharge_criteria": "criteria B",
                },
                idempotency_key="idem-diagnoses-001",
            )
            billing = client.issue_billing_record(
                admission_id=401,
                record_type="final",
                amount=123.45,
                issued_at="2026-03-07 13:00:00",
                notes="decont test",
                cost_center_id=2,
                idempotency_key="idem-billing-001",
            )

        self.assertEqual(2, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/diagnoses", calls[0]["url"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("idem-diagnoses-001", str(calls[0]["headers"].get("idempotency-key") or ""))
        self.assertIn("admission_diagnosis", calls[0]["body"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/billing-records", calls[1]["url"])
        self.assertEqual("POST", calls[1]["method"])
        self.assertEqual("idem-billing-001", str(calls[1]["headers"].get("idempotency-key") or ""))
        self.assertIn("record_type", calls[1]["body"])
        self.assertEqual(401, int(saved["admission_id"]))
        self.assertEqual(77, int(billing["billing_id"]))

    def test_issue_case_invoice_and_register_payment_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=7, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            body = req.data.decode("utf-8") if req.data else ""
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": body,
                    "headers": {str(k).lower(): str(v) for k, v in req.header_items()},
                }
            )
            if req.full_url.endswith("/case-invoices"):
                return _FakeResponse(
                    {
                        "invoice_id": 501,
                        "patient_id": 9,
                        "admission_id": 401,
                        "invoice_type": "proforma",
                        "series": "PF",
                        "invoice_number": "INV-501",
                        "subtotal": 100.0,
                        "tax_amount": 19.0,
                        "total_amount": 119.0,
                        "currency": "RON",
                        "issued_at": "2026-03-07 14:00:00",
                        "due_date": "2026-03-15",
                        "partner_id": 0,
                        "cost_center_id": 0,
                        "status": "issued",
                        "notes": "factura test",
                        "created_at": "2026-03-07 14:00:00",
                        "updated_at": "2026-03-07 14:00:00",
                    }
                )
            return _FakeResponse(
                {
                    "payment_id": 901,
                    "invoice_id": 501,
                    "admission_id": 401,
                    "patient_id": 9,
                    "amount": 119.0,
                    "currency": "RON",
                    "paid_at": "2026-03-07 14:05:00",
                    "payment_method": "card",
                    "reference_no": "PAY-901",
                    "notes": "plata integrala",
                    "created_at": "2026-03-07 14:05:00",
                    "invoice_status": "paid",
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            invoice = client.issue_case_invoice(
                admission_id=401,
                invoice_type="proforma",
                series="PF",
                invoice_number="INV-501",
                subtotal=100.0,
                tax_amount=19.0,
                total_amount=None,
                issued_at="2026-03-07 14:00:00",
                due_date="2026-03-15",
                status="issued",
                notes="factura test",
                idempotency_key="idem-invoice-001",
            )
            payment = client.register_invoice_payment(
                invoice_id=501,
                amount=119.0,
                paid_at="2026-03-07 14:05:00",
                payment_method="card",
                reference_no="PAY-901",
                notes="plata integrala",
                idempotency_key="idem-payment-001",
            )

        self.assertEqual(2, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/case-invoices", calls[0]["url"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("idem-invoice-001", str(calls[0]["headers"].get("idempotency-key") or ""))
        self.assertIn("invoice_type", calls[0]["body"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/case-invoices/501/payments", calls[1]["url"])
        self.assertEqual("POST", calls[1]["method"])
        self.assertEqual("idem-payment-001", str(calls[1]["headers"].get("idempotency-key") or ""))
        self.assertIn("payment_method", calls[1]["body"])
        self.assertEqual(501, int(invoice["invoice_id"]))
        self.assertEqual(901, int(payment["payment_id"]))

    def test_list_admission_transfers_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 1,
                            "admission_id": 401,
                            "action_type": "admit",
                            "from_department": "",
                            "from_ward": "",
                            "from_bed": "",
                            "to_department": "Ortopedie",
                            "to_ward": "A2",
                            "to_bed": "12",
                            "notes": "Internare initiala",
                            "transferred_at": "2026-03-06 09:00:00",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_admission_transfers(admission_id=401, limit=400)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/transfers?limit=400", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("admit", rows[0]["action_type"])

    def test_list_orders_for_admission_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 33,
                            "admission_id": 401,
                            "order_type": "lab",
                            "priority": "urgent",
                            "order_text": "Hemoleucograma completa",
                            "status": "ordered",
                            "ordered_at": "2026-03-06 11:40:00",
                            "completed_at": "",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_orders_for_admission(admission_id=401, limit=200)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/orders?limit=200", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("lab", rows[0]["order_type"])

    def test_list_vitals_for_admission_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 44,
                            "admission_id": 401,
                            "recorded_at": "2026-03-06 12:00:00",
                            "temperature_c": "37.2",
                            "systolic_bp": "120",
                            "diastolic_bp": "80",
                            "pulse": "82",
                            "respiratory_rate": "18",
                            "spo2": "98",
                            "pain_score": "2",
                            "notes": "stabil",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_vitals_for_admission(admission_id=401, limit=300)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/vitals?limit=300", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("37.2", rows[0]["temperature_c"])

    def test_list_institutional_reports_and_status_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout})
            if req.full_url.endswith("/institutional-reports/status"):
                return _FakeResponse({"admission_id": 401, "siui": True, "drg": False})
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 13,
                            "admission_id": 401,
                            "patient_id": 9,
                            "report_type": "siui",
                            "payload_json": "{\"x\":1}",
                            "payload_hash": "abc",
                            "validation_errors": "",
                            "status": "submitted",
                            "external_reference": "SIUI-13",
                            "ack_payload": "{\"ok\":true}",
                            "submitted_at": "2026-03-06 10:00:00",
                            "transport_state": "submitted",
                            "transport_attempts": 1,
                            "transport_last_error": "",
                            "transport_http_code": 200,
                            "transport_last_attempt_at": "2026-03-06 10:00:00",
                            "created_at": "2026-03-06 09:59:00",
                            "updated_at": "2026-03-06 10:00:00",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_institutional_reports(admission_id=401, limit=300)
            status = client.get_institutional_reporting_status(admission_id=401)
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/admissions/401/institutional-reports?limit=300",
            calls[0]["url"],
        )
        self.assertEqual("GET", calls[0]["method"])
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/admissions/401/institutional-reports/status",
            calls[1]["url"],
        )
        self.assertEqual("GET", calls[1]["method"])
        self.assertEqual(1, len(rows))
        self.assertEqual("siui", rows[0]["report_type"])
        self.assertTrue(status["siui"])
        self.assertFalse(status["drg"])

    def test_list_billing_records_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 5,
                            "admission_id": 401,
                            "patient_id": 9,
                            "record_type": "partial",
                            "amount": 150.0,
                            "currency": "RON",
                            "issued_at": "2026-03-06 10:00:00",
                            "notes": "decont partial",
                            "status": "issued",
                            "cost_center_id": 0,
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_billing_records(admission_id=401, limit=200)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/billing-records?limit=200", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("partial", rows[0]["record_type"])
        self.assertEqual(150.0, float(rows[0]["amount"]))

    def test_list_case_invoices_and_payments_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout})
            if "/case-invoices/31/payments" in req.full_url:
                return _FakeResponse(
                    {
                        "invoice_id": 31,
                        "items": [
                            {
                                "id": 71,
                                "invoice_id": 31,
                                "admission_id": 401,
                                "patient_id": 9,
                                "amount": 50.0,
                                "currency": "RON",
                                "paid_at": "2026-03-06 10:30:00",
                                "payment_method": "cash",
                                "reference_no": "R1",
                                "notes": "plata partiala",
                                "created_at": "2026-03-06 10:30:01",
                            }
                        ],
                    }
                )
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 31,
                            "patient_id": 9,
                            "admission_id": 401,
                            "invoice_type": "proforma",
                            "series": "PF",
                            "invoice_number": "00031",
                            "subtotal": 100.0,
                            "tax_amount": 19.0,
                            "total_amount": 119.0,
                            "currency": "RON",
                            "issued_at": "2026-03-06 10:00:00",
                            "due_date": "2026-03-15",
                            "partner_id": 0,
                            "cost_center_id": 0,
                            "status": "issued",
                            "notes": "n",
                            "created_at": "2026-03-06 10:00:01",
                            "updated_at": "2026-03-06 10:00:01",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            invoices = client.list_case_invoices(admission_id=401, limit=500)
            payments = client.list_invoice_payments(invoice_id=31, limit=500)

        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/case-invoices?limit=500", calls[0]["url"])
        self.assertEqual("GET", calls[0]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/case-invoices/31/payments?limit=500", calls[1]["url"])
        self.assertEqual("GET", calls[1]["method"])
        self.assertEqual(1, len(invoices))
        self.assertEqual("proforma", invoices[0]["invoice_type"])
        self.assertEqual(1, len(payments))
        self.assertEqual("cash", payments[0]["payment_method"])

    def test_list_offer_contracts_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 91,
                            "patient_id": 9,
                            "admission_id": 401,
                            "doc_type": "offer",
                            "package_name": "Pachet Premium",
                            "accommodation_type": "single",
                            "base_price": 1000.0,
                            "discount_amount": 100.0,
                            "final_price": 900.0,
                            "currency": "RON",
                            "status": "draft",
                            "notes": "n",
                            "created_at": "2026-03-06 11:00:00",
                            "updated_at": "2026-03-06 11:00:00",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_offer_contracts(admission_id=401, limit=300)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/offer-contracts?limit=300", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("offer", rows[0]["doc_type"])
        self.assertAlmostEqual(900.0, float(rows[0]["final_price"]), places=3)

    def test_list_medical_leaves_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 12,
                            "patient_id": 9,
                            "admission_id": 401,
                            "series": "CM",
                            "leave_number": "0012",
                            "issued_at": "2026-03-06 11:15:00",
                            "start_date": "2026-03-07",
                            "end_date": "2026-03-10",
                            "days_count": 4,
                            "diagnosis_code": "M16",
                            "notes": "n",
                            "status": "issued",
                            "series_rule_id": 0,
                            "created_at": "2026-03-06 11:15:01",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_medical_leaves(admission_id=401, limit=300)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/medical-leaves?limit=300", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("CM", rows[0]["series"])
        self.assertEqual(4, int(rows[0]["days_count"]))

    def test_list_case_consumptions_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "admission_id": 401,
                    "items": [
                        {
                            "id": 22,
                            "patient_id": 9,
                            "admission_id": 401,
                            "item_type": "material",
                            "item_name": "Bandaj",
                            "unit": "buc",
                            "quantity": 2.0,
                            "unit_price": 10.0,
                            "total_price": 20.0,
                            "source": "ward_stock",
                            "partner_id": 0,
                            "cost_center_id": 0,
                            "status": "recorded",
                            "notes": "n",
                            "recorded_at": "2026-03-06 11:30:00",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_case_consumptions(admission_id=401, limit=500)
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/case-consumptions?limit=500", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("material", rows[0]["item_type"])
        self.assertAlmostEqual(20.0, float(rows[0]["total_price"]), places=3)

    def test_list_orders_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 33,
                            "admission_id": 401,
                            "order_type": "lab",
                            "priority": "urgent",
                            "order_text": "Hemoleucograma completa",
                            "status": "ordered",
                            "ordered_at": "2026-03-06 11:40:00",
                            "completed_at": "",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_orders(patient_id=9, limit=300)
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/orders?limit=300", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("lab", rows[0]["order_type"])
        self.assertEqual("urgent", rows[0]["priority"])

    def test_list_vitals_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 44,
                            "admission_id": 401,
                            "recorded_at": "2026-03-06 12:00:00",
                            "temperature_c": "37.2",
                            "systolic_bp": "120",
                            "diastolic_bp": "80",
                            "pulse": "82",
                            "respiratory_rate": "18",
                            "spo2": "98",
                            "pain_score": "2",
                            "notes": "stabil",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_vitals(patient_id=9, limit=300)
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/vitals?limit=300", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("37.2", rows[0]["temperature_c"])
        self.assertEqual("98", rows[0]["spo2"])

    def test_list_visits_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 45,
                            "visit_date": "2026-03-06",
                            "reason": "Control",
                            "diagnosis": "J20.9",
                            "treatment": "Simptomatic",
                            "notes": "monitorizare",
                            "created_at": "2026-03-06 12:10:00",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_visits(patient_id=9, limit=200)
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/visits?limit=200", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("Control", rows[0]["reason"])
        self.assertEqual("J20.9", rows[0]["diagnosis"])

    def test_list_medis_investigations_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=2, role="medic")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 46,
                            "order_id": 33,
                            "patient_id": 9,
                            "admission_id": 401,
                            "provider": "MEDIS",
                            "external_request_id": "REQ-123",
                            "requested_at": "2026-03-06 12:20:00",
                            "request_payload": "{\"panel\":\"cbc\"}",
                            "status": "sent",
                            "result_received_at": "",
                            "result_summary": "",
                            "result_flag": "",
                            "result_payload": "",
                            "external_result_id": "",
                            "transport_state": "submitted_local",
                            "transport_attempts": 0,
                            "transport_last_error": "",
                            "transport_http_code": 0,
                            "transport_last_attempt_at": "",
                            "order_type": "lab",
                            "priority": "urgent",
                            "order_text": "Hemoleucograma completa",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_medis_investigations(patient_id=9, admission_id=401, limit=500)
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/patients/9/medis-investigations?limit=500&admission_id=401",
            seen["url"],
        )
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("MEDIS", rows[0]["provider"])
        self.assertEqual("REQ-123", rows[0]["external_request_id"])

    def test_list_integration_queue_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 201,
                            "provider": "medis",
                            "operation": "submit_order",
                            "entity_type": "medis_investigation",
                            "entity_id": 46,
                            "status": "retry",
                            "attempt_count": 2,
                            "next_retry_at": "2026-03-06 13:00:00",
                            "last_error": "timeout",
                            "last_http_code": 504,
                            "updated_at": "2026-03-06 12:59:00",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_integration_queue(limit=200, status_filter="retry")
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/ops/integration-queue?limit=200&status_filter=retry",
            seen["url"],
        )
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("retry", rows[0]["status"])
        self.assertEqual(504, int(rows[0]["last_http_code"]))

    def test_list_job_executions_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=4, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 301,
                            "job_name": "integration_queue_tick",
                            "status": "ok",
                            "duration_ms": 123,
                            "details_json": "{\"processed\":5}",
                            "correlation_id": "corr-123",
                            "created_at": "2026-03-06 13:05:00",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_job_executions(limit=200, job_name="")
        self.assertEqual("http://127.0.0.1:8000/api/v1/ops/job-executions?limit=200", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(4, int(seen["timeout"]))
        self.assertEqual(1, len(rows))
        self.assertEqual("integration_queue_tick", rows[0]["job_name"])
        self.assertEqual(123, int(rows[0]["duration_ms"]))

    def test_patient_timeline_snapshots_and_restore_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=5, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            header_map = {str(k).lower(): str(v) for k, v in req.header_items()}
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": req.data,
                    "headers": header_map,
                }
            )
            if "/timeline" in req.full_url:
                return _FakeResponse(
                    {
                        "patient_id": 9,
                        "items": [
                            {
                                "event_id": "snapshot:10",
                                "patient_id": 9,
                                "admission_id": 0,
                                "event_type": "patient_snapshot",
                                "category": "snapshot",
                                "occurred_at": "2026-03-06 12:00:00",
                                "actor_user_id": 1,
                                "actor_name": "admin",
                                "title": "Snapshot v1",
                                "summary": "create_patient",
                                "payload_json": "{\"k\":\"v\"}",
                            }
                        ],
                    }
                )
            if req.full_url.endswith("/snapshots/10/diff"):
                return _FakeResponse(
                    {
                        "patient_id": 9,
                        "from_snapshot_id": 9,
                        "to_snapshot_id": 10,
                        "changed_fields": ["first_name", "phone"],
                        "from_snapshot_created_at": "2026-03-06 11:00:00",
                        "to_snapshot_created_at": "2026-03-06 12:00:00",
                        "diff_json": "{\"first_name\":{\"from\":\"Ana\",\"to\":\"Maria\"}}",
                    }
                )
            if req.full_url.endswith("/snapshots/10/restore"):
                return _FakeResponse(
                    {
                        "ok": True,
                        "patient_id": 9,
                        "restored_snapshot_id": 10,
                        "backup_snapshot_id": 11,
                        "post_snapshot_id": 12,
                        "restored_at": "2026-03-06 12:05:00",
                    }
                )
            if req.full_url.endswith("/snapshots/10"):
                return _FakeResponse(
                    {
                        "id": 10,
                        "patient_id": 9,
                        "version_no": 2,
                        "trigger_action": "update_patient",
                        "trigger_source": "save_patient",
                        "trigger_ref_id": "patient_id:9",
                        "snapshot_json": "{\"first_name\":\"Maria\"}",
                        "changed_fields_json": "[\"first_name\"]",
                        "snapshot_hash": "abc",
                        "created_at": "2026-03-06 12:00:00",
                        "created_by_user_id": 1,
                        "created_by_username": "admin",
                    }
                )
            return _FakeResponse(
                {
                    "patient_id": 9,
                    "items": [
                        {
                            "id": 10,
                            "patient_id": 9,
                            "version_no": 2,
                            "trigger_action": "update_patient",
                            "trigger_source": "save_patient",
                            "trigger_ref_id": "patient_id:9",
                            "snapshot_json": "{\"first_name\":\"Maria\"}",
                            "changed_fields_json": "[\"first_name\"]",
                            "snapshot_hash": "abc",
                            "created_at": "2026-03-06 12:00:00",
                            "created_by_user_id": 1,
                            "created_by_username": "admin",
                        }
                    ],
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            timeline = client.list_patient_timeline(
                patient_id=9,
                limit=400,
                category="snapshot",
                event_type="patient_snapshot",
                date_from="2026-03-01",
                date_to="2026-03-06",
                admission_id=0,
            )
            snapshots = client.list_patient_snapshots(patient_id=9, limit=100)
            snapshot = client.get_patient_snapshot(patient_id=9, snapshot_id=10)
            diff = client.get_patient_snapshot_diff(patient_id=9, snapshot_id=10)
            restore = client.restore_patient_snapshot(
                patient_id=9,
                snapshot_id=10,
                reason="test",
                expected_updated_at="2026-03-06 12:00:00",
                idempotency_key="idem-restore-001",
            )

        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/patients/9/timeline?limit=400&category=snapshot&event_type=patient_snapshot&date_from=2026-03-01&date_to=2026-03-06",
            calls[0]["url"],
        )
        self.assertEqual("GET", calls[0]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/snapshots?limit=100", calls[1]["url"])
        self.assertEqual("GET", calls[1]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/snapshots/10", calls[2]["url"])
        self.assertEqual("GET", calls[2]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/snapshots/10/diff", calls[3]["url"])
        self.assertEqual("GET", calls[3]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/snapshots/10/restore", calls[4]["url"])
        self.assertEqual("POST", calls[4]["method"])
        self.assertIn("test", (calls[4]["body"] or b"").decode("utf-8"))
        self.assertIn("expected_updated_at", (calls[4]["body"] or b"").decode("utf-8"))
        self.assertEqual("idem-restore-001", str(calls[4]["headers"].get("idempotency-key") or ""))
        self.assertEqual(1, len(timeline))
        self.assertEqual("snapshot:10", timeline[0]["event_id"])
        self.assertEqual(1, len(snapshots))
        self.assertEqual(10, int(snapshots[0]["id"]))
        self.assertEqual(10, int(snapshot["id"]))
        self.assertEqual(["first_name", "phone"], diff["changed_fields"])
        self.assertTrue(bool(restore["ok"]))
        self.assertEqual(11, int(restore["backup_snapshot_id"]))

    def test_get_health_returns_normalized_payload(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=5, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "status": "degraded",
                    "timestamp": "2026-03-06 16:00:00",
                    "checks": {
                        "db_backend_configured": "postgres",
                        "db_backend_effective": "sqlite",
                        "central_db_ready": False,
                    },
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            health = client.get_health()
        self.assertEqual("http://127.0.0.1:8000/api/v1/health", seen["url"])
        self.assertEqual("GET", seen["method"])
        self.assertEqual(5, int(seen["timeout"]))
        self.assertEqual("degraded", health["status"])
        self.assertEqual("sqlite", health["checks"]["db_backend_effective"])
        self.assertFalse(bool(health["checks"]["central_db_ready"]))

    def test_val2_new_write_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        client.set_actor(user_id=7, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append(
                {
                    "url": req.full_url,
                    "method": req.get_method(),
                    "timeout": timeout,
                    "body": req.data.decode("utf-8") if req.data else "",
                    "headers": {str(k).lower(): str(v) for k, v in req.header_items()},
                }
            )
            url = str(req.full_url)
            if url.endswith("/case-invoices/501/status"):
                return _FakeResponse({"invoice_id": 501, "admission_id": 401, "status": "paid", "updated_at": "2026-03-08 10:10:00"})
            if url.endswith("/admissions/401/offer-contracts"):
                return _FakeResponse(
                    {
                        "offer_id": 601,
                        "patient_id": 9,
                        "admission_id": 401,
                        "doc_type": "offer",
                        "package_name": "Pachet Plus",
                        "accommodation_type": "single",
                        "base_price": 1200.0,
                        "discount_amount": 200.0,
                        "final_price": 1000.0,
                        "currency": "RON",
                        "status": "draft",
                        "notes": "test",
                        "created_at": "2026-03-08 10:00:00",
                        "updated_at": "2026-03-08 10:00:00",
                    }
                )
            if url.endswith("/offer-contracts/601/status"):
                return _FakeResponse({"offer_id": 601, "status": "approved", "updated_at": "2026-03-08 10:05:00"})
            if url.endswith("/admissions/401/medical-leaves"):
                return _FakeResponse(
                    {
                        "leave_id": 701,
                        "patient_id": 9,
                        "admission_id": 401,
                        "series": "CM",
                        "leave_number": "777",
                        "issued_at": "2026-03-08 10:30:00",
                        "start_date": "2026-03-09",
                        "end_date": "2026-03-11",
                        "days_count": 3,
                        "diagnosis_code": "M16",
                        "notes": "test",
                        "status": "active",
                        "series_rule_id": 0,
                        "created_at": "2026-03-08 10:30:00",
                    }
                )
            if url.endswith("/medical-leaves/701/cancel"):
                return _FakeResponse({"leave_id": 701, "status": "cancelled"})
            if url.endswith("/admissions/401/case-consumptions"):
                return _FakeResponse(
                    {
                        "consumption_id": 801,
                        "patient_id": 9,
                        "admission_id": 401,
                        "item_type": "material",
                        "item_name": "Bandaj",
                        "unit": "buc",
                        "quantity": 2.0,
                        "unit_price": 10.0,
                        "total_price": 20.0,
                        "source": "ward_stock",
                        "partner_id": 0,
                        "cost_center_id": 0,
                        "status": "draft",
                        "notes": "test",
                        "recorded_at": "2026-03-08 10:40:00",
                    }
                )
            if url.endswith("/case-consumptions/801/status"):
                return _FakeResponse({"consumption_id": 801, "status": "approved"})
            if url.endswith("/patients/9/orders"):
                return _FakeResponse(
                    {
                        "order_id": 901,
                        "patient_id": 9,
                        "admission_id": 401,
                        "order_type": "lab",
                        "priority": "urgent",
                        "order_text": "Hemoleucograma",
                        "status": "ordered",
                        "ordered_at": "2026-03-08 10:50:00",
                        "completed_at": "",
                    }
                )
            if url.endswith("/orders/901/status"):
                return _FakeResponse({"order_id": 901, "status": "in_progress", "completed_at": ""})
            if url.endswith("/patients/9/vitals"):
                return _FakeResponse(
                    {
                        "vital_id": 1001,
                        "patient_id": 9,
                        "admission_id": 401,
                        "recorded_at": "2026-03-08 11:00:00",
                        "temperature_c": "37.2",
                        "systolic_bp": "120",
                        "diastolic_bp": "80",
                        "pulse": "80",
                        "respiratory_rate": "18",
                        "spo2": "98",
                        "pain_score": "2",
                        "notes": "ok",
                    }
                )
            if url.endswith("/patients/9/visits"):
                return _FakeResponse(
                    {
                        "visit_id": 1101,
                        "patient_id": 9,
                        "visit_date": "2026-03-08",
                        "reason": "control",
                        "diagnosis": "I10",
                        "treatment": "monitorizare",
                        "notes": "ok",
                        "created_at": "2026-03-08 11:10:00",
                    }
                )
            if url.endswith("/visits/1101"):
                return _FakeResponse({"visit_id": 1101, "patient_id": 9, "deleted": True})
            return _FakeResponse({})

        with patch("urllib.request.urlopen", _fake_urlopen):
            inv = client.update_case_invoice_status(invoice_id=501, status="paid", idempotency_key="idem-inv-status")
            offer = client.create_offer_contract(
                admission_id=401,
                doc_type="offer",
                package_name="Pachet Plus",
                accommodation_type="single",
                base_price=1200.0,
                discount_amount=200.0,
                final_price=1000.0,
                status="draft",
                notes="test",
                idempotency_key="idem-offer-create",
            )
            offer_status = client.update_offer_contract_status(
                offer_id=601,
                status="approved",
                idempotency_key="idem-offer-status",
            )
            leave = client.create_medical_leave(
                admission_id=401,
                series="CM",
                leave_number="777",
                issued_at="2026-03-08 10:30:00",
                start_date="2026-03-09",
                end_date="2026-03-11",
                diagnosis_code="M16",
                notes="test",
                series_rule_id=None,
                idempotency_key="idem-leave-create",
            )
            leave_cancel = client.cancel_medical_leave(
                leave_id=701,
                idempotency_key="idem-leave-cancel",
            )
            consumption = client.create_case_consumption(
                admission_id=401,
                item_type="material",
                item_name="Bandaj",
                unit="buc",
                quantity=2.0,
                unit_price=10.0,
                source="ward_stock",
                notes="test",
                recorded_at="2026-03-08 10:40:00",
                partner_id=None,
                cost_center_id=None,
                idempotency_key="idem-consumption-create",
            )
            consumption_status = client.update_case_consumption_status(
                consumption_id=801,
                status="approved",
                idempotency_key="idem-consumption-status",
            )
            order = client.create_order(
                patient_id=9,
                admission_id=401,
                order_type="lab",
                priority="urgent",
                order_text="Hemoleucograma",
                idempotency_key="idem-order-create",
            )
            order_status = client.update_order_status(
                order_id=901,
                status="in_progress",
                idempotency_key="idem-order-status",
            )
            vital = client.create_vital(
                patient_id=9,
                admission_id=401,
                recorded_at="2026-03-08 11:00:00",
                temperature_c="37.2",
                systolic_bp="120",
                diastolic_bp="80",
                pulse="80",
                respiratory_rate="18",
                spo2="98",
                pain_score="2",
                notes="ok",
                idempotency_key="idem-vital-create",
            )
            visit = client.create_visit(
                patient_id=9,
                visit_date="2026-03-08",
                reason="control",
                diagnosis="I10",
                treatment="monitorizare",
                notes="ok",
                idempotency_key="idem-visit-create",
            )
            visit_delete = client.delete_visit(
                visit_id=1101,
                idempotency_key="idem-visit-delete",
            )

        self.assertEqual(12, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/case-invoices/501/status", calls[0]["url"])
        self.assertEqual("PATCH", calls[0]["method"])
        self.assertEqual("idem-inv-status", str(calls[0]["headers"].get("idempotency-key") or ""))
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/offer-contracts", calls[1]["url"])
        self.assertEqual("POST", calls[1]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/offer-contracts/601/status", calls[2]["url"])
        self.assertEqual("PATCH", calls[2]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/medical-leaves", calls[3]["url"])
        self.assertEqual("POST", calls[3]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/medical-leaves/701/cancel", calls[4]["url"])
        self.assertEqual("PATCH", calls[4]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/admissions/401/case-consumptions", calls[5]["url"])
        self.assertEqual("POST", calls[5]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/case-consumptions/801/status", calls[6]["url"])
        self.assertEqual("PATCH", calls[6]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/orders", calls[7]["url"])
        self.assertEqual("POST", calls[7]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/orders/901/status", calls[8]["url"])
        self.assertEqual("PATCH", calls[8]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/vitals", calls[9]["url"])
        self.assertEqual("POST", calls[9]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/patients/9/visits", calls[10]["url"])
        self.assertEqual("POST", calls[10]["method"])
        self.assertEqual("http://127.0.0.1:8000/api/v1/visits/1101", calls[11]["url"])
        self.assertEqual("DELETE", calls[11]["method"])
        self.assertEqual(501, int(inv["invoice_id"]))
        self.assertEqual(601, int(offer["offer_id"]))
        self.assertEqual("approved", str(offer_status["status"]))
        self.assertEqual(701, int(leave["leave_id"]))
        self.assertEqual("cancelled", str(leave_cancel["status"]))
        self.assertEqual(801, int(consumption["consumption_id"]))
        self.assertEqual("approved", str(consumption_status["status"]))
        self.assertEqual(901, int(order["order_id"]))
        self.assertEqual("in_progress", str(order_status["status"]))
        self.assertEqual(1001, int(vital["vital_id"]))
        self.assertEqual(1101, int(visit["visit_id"]))
        self.assertTrue(bool(visit_delete["deleted"]))

    def test_is_localhost_target(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        self.assertTrue(client.is_localhost_target())
        client.configure(base_url="https://localhost:9443", timeout_seconds=8, enabled=True)
        self.assertTrue(client.is_localhost_target())
        client.configure(base_url="https://api.example.com", timeout_seconds=8, enabled=True)
        self.assertFalse(client.is_localhost_target())

    def test_shadow_sync_client_routes(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        client.set_actor(user_id=1, role="admin")
        calls = []

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            calls.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout})
            if req.full_url.endswith("/ops/shadow-sync/status"):
                return _FakeResponse(
                    {
                        "timestamp": "2026-03-08 10:00:00",
                        "shadow_mode_enabled": True,
                        "shadow_backlog_pending": 2,
                        "shadow_last_sync_at": "",
                        "shadow_error_rate_24h": 0.25,
                        "attempted_24h": 8,
                        "failed_24h": 2,
                        "settings": {"batch_size": 50},
                    }
                )
            if "/ops/shadow-sync/process" in req.full_url:
                return _FakeResponse({"processed": 2, "synced": 1, "retried": 1, "failed": 0})
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 11,
                            "action_key": "POST /api/v1/patients",
                            "source": "api_middleware",
                            "payload_hash": "abc",
                            "status": "failed",
                            "retry_count": 3,
                            "next_retry_at": "",
                            "last_error": "db down",
                            "last_attempt_at": "2026-03-08 09:59:00",
                            "created_at": "2026-03-08 09:50:00",
                            "updated_at": "2026-03-08 09:59:00",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            status_payload = client.get_shadow_sync_status()
            process_payload = client.process_shadow_sync(max_jobs=25)
            errors_payload = client.list_shadow_sync_errors(limit=30)

        self.assertEqual(3, len(calls))
        self.assertEqual("http://127.0.0.1:8000/api/v1/ops/shadow-sync/status", calls[0]["url"])
        self.assertEqual("GET", calls[0]["method"])
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/ops/shadow-sync/process?max_jobs=25",
            calls[1]["url"],
        )
        self.assertEqual("POST", calls[1]["method"])
        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/ops/shadow-sync/errors?limit=30",
            calls[2]["url"],
        )
        self.assertEqual("GET", calls[2]["method"])
        self.assertTrue(bool(status_payload["shadow_mode_enabled"]))
        self.assertEqual(2, int(process_payload["processed"]))
        self.assertEqual(1, len(errors_payload))

    def test_integration_dry_run_logs_client_route(self) -> None:
        client = EnterpriseApiClient(base_url="http://127.0.0.1:8000", timeout_seconds=8, enabled=True)
        client.set_actor(user_id=1, role="admin")
        seen = {}

        def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["timeout"] = timeout
            return _FakeResponse(
                {
                    "items": [
                        {
                            "id": 7,
                            "provider": "medis",
                            "operation": "submit_order",
                            "dry_run": True,
                            "http_code": 200,
                            "latency_ms": 14,
                            "ok": True,
                            "error": "",
                            "created_at": "2026-03-08 12:00:00",
                            "correlation_id": "corr-ops-7",
                        }
                    ]
                }
            )

        with patch("urllib.request.urlopen", _fake_urlopen):
            rows = client.list_integration_dry_run_logs(limit=25, provider="medis", operation="submit_order")

        self.assertEqual(
            "http://127.0.0.1:8000/api/v1/ops/integration-dry-run-logs?limit=25&provider=medis&operation=submit_order",
            str(seen.get("url") or ""),
        )
        self.assertEqual("GET", str(seen.get("method") or ""))
        self.assertEqual(1, len(rows))
        self.assertEqual("medis", str(rows[0].get("provider") or ""))
        self.assertEqual("submit_order", str(rows[0].get("operation") or ""))
        self.assertTrue(bool(rows[0].get("dry_run")))


if __name__ == "__main__":
    unittest.main()
