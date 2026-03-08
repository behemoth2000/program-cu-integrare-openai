import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
    from pacienti_ai_independent.api import create_api_app
    from pacienti_ai_independent.pacienti_ai_app import Database
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]
    create_api_app = None  # type: ignore[assignment]
    Database = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None or create_api_app is None, "fastapi/starlette nu sunt instalate")
class EnterpriseApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_db_backend = os.environ.get("PACIENTI_DB_BACKEND")
        self._prev_postgres_dsn = os.environ.get("PACIENTI_POSTGRES_DSN")
        self._prev_postgres_timeout = os.environ.get("PACIENTI_POSTGRES_CONNECT_TIMEOUT_SECONDS")
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        os.environ.pop("PACIENTI_DB_BACKEND", None)
        os.environ.pop("PACIENTI_POSTGRES_DSN", None)
        os.environ.pop("PACIENTI_POSTGRES_CONNECT_TIMEOUT_SECONDS", None)
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_enterprise_api_{uuid4().hex}.db"
        self.app = create_api_app(db_path=self.db_path)
        self.client = TestClient(self.app)
        self.admin_headers = {"X-Role": "admin", "X-User-Id": "1"}
        self.medic_headers = {"X-Role": "medic", "X-User-Id": "2"}

    def tearDown(self) -> None:
        self.client.close()
        if self._prev_db_backend is None:
            os.environ.pop("PACIENTI_DB_BACKEND", None)
        else:
            os.environ["PACIENTI_DB_BACKEND"] = self._prev_db_backend
        if self._prev_postgres_dsn is None:
            os.environ.pop("PACIENTI_POSTGRES_DSN", None)
        else:
            os.environ["PACIENTI_POSTGRES_DSN"] = self._prev_postgres_dsn
        if self._prev_postgres_timeout is None:
            os.environ.pop("PACIENTI_POSTGRES_CONNECT_TIMEOUT_SECONDS", None)
        else:
            os.environ["PACIENTI_POSTGRES_CONNECT_TIMEOUT_SECONDS"] = self._prev_postgres_timeout
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def _seed_active_admission(self, patient_id: int) -> int:
        db = Database(self.db_path)
        admission_id, _ = db.create_admission(
            {
                "patient_id": str(int(patient_id)),
                "admission_type": "inpatient",
                "triage_level": "2",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "12",
                "attending_clinician": "Dr Test",
                "chief_complaint": "Durere severa",
                "admitted_at": "2026-03-06 09:00:00",
            },
            user_id=1,
        )
        return int(admission_id)

    def test_health_contract(self) -> None:
        res = self.client.get("/api/v1/health", headers=self.admin_headers)
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn(body.get("status"), {"ok", "degraded", "error"})
        self.assertIn("checks", body)
        self.assertIn("db_access", body["checks"])
        self.assertIn(body["checks"].get("db_backend_configured"), {"sqlite", "postgres"})
        self.assertIn(body["checks"].get("db_backend_effective"), {"sqlite", "postgres"})
        self.assertIsInstance(bool(body["checks"].get("central_db_ready")), bool)

    def test_health_echoes_correlation_id_header(self) -> None:
        headers = {**self.admin_headers, "X-Correlation-Id": "corr-contract-001"}
        res = self.client.get("/api/v1/health", headers=headers)
        self.assertEqual(200, res.status_code)
        self.assertEqual("corr-contract-001", str(res.headers.get("X-Correlation-Id") or ""))

    def test_health_generates_correlation_id_header_when_missing(self) -> None:
        res = self.client.get("/api/v1/health", headers=self.admin_headers)
        self.assertEqual(200, res.status_code)
        corr = str(res.headers.get("X-Correlation-Id") or "")
        self.assertTrue(bool(corr.strip()))

    def test_health_contract_postgres_configured_fallbacks_to_sqlite_when_missing_dsn(self) -> None:
        os.environ["PACIENTI_DB_BACKEND"] = "postgres"
        os.environ.pop("PACIENTI_POSTGRES_DSN", None)
        db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_enterprise_api_pg_{uuid4().hex}.db"
        app = create_api_app(db_path=db_path)
        client = TestClient(app)
        try:
            res = client.get("/api/v1/health", headers=self.admin_headers)
            self.assertEqual(200, res.status_code)
            body = res.json()
            self.assertEqual("degraded", str(body.get("status") or ""))
            checks = body.get("checks") or {}
            self.assertEqual("postgres", str(checks.get("db_backend_configured") or ""))
            self.assertEqual("sqlite", str(checks.get("db_backend_effective") or ""))
            self.assertFalse(bool(checks.get("central_db_ready")))
            self.assertIn("central_db_error", checks)
        finally:
            client.close()
            if db_path.exists():
                try:
                    db_path.unlink()
                except PermissionError:
                    pass

    def test_dashboard_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Dashboard", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        current_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order_id = db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma completa",
            user_id=1,
        )
        vital_id = db.add_vital(
            patient_id=patient_id,
            admission_id=admission_id,
            payload={
                "recorded_at": current_ts,
                "temperature_c": "39.1",
                "systolic_bp": "120",
                "diastolic_bp": "80",
                "pulse": "82",
                "respiratory_rate": "18",
                "spo2": "98",
                "pain_score": "2",
                "notes": "alert test",
            },
            user_id=1,
        )

        kpi_res = self.client.get("/api/v1/dashboard/kpis?department=Ortopedie", headers=self.medic_headers)
        self.assertEqual(200, kpi_res.status_code)
        kpi_body = kpi_res.json()
        self.assertIn("kpi", kpi_body)
        self.assertIn("active_admissions", kpi_body["kpi"])

        adm_res = self.client.get(
            "/api/v1/dashboard/active-admissions?department=Ortopedie&limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, adm_res.status_code)
        adm_items = adm_res.json().get("items") or []
        adm_ids = {int(item.get("id") or 0) for item in adm_items}
        self.assertIn(admission_id, adm_ids)

        orders_res = self.client.get(
            "/api/v1/dashboard/urgent-orders?department=Ortopedie&limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, orders_res.status_code)
        order_items = orders_res.json().get("items") or []
        order_ids = {int(item.get("id") or 0) for item in order_items}
        self.assertIn(int(order_id), order_ids)

        alerts_res = self.client.get(
            "/api/v1/dashboard/vital-alerts?department=Ortopedie&hours=24&limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, alerts_res.status_code)
        alert_items = alerts_res.json().get("items") or []
        alert_ids = {int(item.get("id") or 0) for item in alert_items}
        self.assertIn(int(vital_id), alert_ids)
        self.assertTrue(any(str(item.get("reasons") or "").strip() for item in alert_items))

    def test_create_patient_idempotency_contract(self) -> None:
        payload = {
            "first_name": "Ana",
            "last_name": "Ionescu",
            "cnp": "",
            "diagnosis": {"primary_icd10": "I10", "secondary_icd10": ["E11"], "free_text": "HTA"},
        }
        headers = {**self.admin_headers, "Idempotency-Key": "idem-patient-create-001"}
        first = self.client.post("/api/v1/patients", json=payload, headers=headers)
        self.assertEqual(201, first.status_code)
        body1 = first.json()
        self.assertGreater(int(body1.get("id") or 0), 0)

        second = self.client.post("/api/v1/patients", json=payload, headers=headers)
        self.assertEqual(201, second.status_code)
        body2 = second.json()
        self.assertEqual(body1.get("id"), body2.get("id"))

        altered = dict(payload)
        altered["first_name"] = "Maria"
        third = self.client.post("/api/v1/patients", json=altered, headers=headers)
        self.assertEqual(409, third.status_code)

    def test_patient_read_patch_and_estimations(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Mihai", "last_name": "Pop", "diagnosis": {"primary_icd10": "J18"}},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])

        get_res = self.client.get(f"/api/v1/patients/{patient_id}", headers=self.medic_headers)
        self.assertEqual(200, get_res.status_code)
        self.assertEqual("Mihai", get_res.json()["first_name"])

        patch_res = self.client.patch(
            f"/api/v1/patients/{patient_id}",
            json={"phone": "0712345678", "diagnosis": {"primary_icd10": "I10", "secondary_icd10": ["E11"]}},
            headers=self.admin_headers,
        )
        self.assertEqual(200, patch_res.status_code)
        self.assertEqual("0712345678", patch_res.json()["phone"])

        sug_res = self.client.post(
            f"/api/v1/patients/{patient_id}/diagnosis-suggestions",
            headers=self.medic_headers,
        )
        self.assertEqual(200, sug_res.status_code)
        sug_body = sug_res.json()
        self.assertEqual(patient_id, int(sug_body.get("patient_id") or 0))
        self.assertIn("suggestions", sug_body)

        estimate_res = self.client.post(
            f"/api/v1/patients/{patient_id}/drg-icm-estimate",
            json={"primary_icd10": "I10", "secondary_icd10": ["E11"], "free_text": "control"},
            headers=self.medic_headers,
        )
        self.assertEqual(200, estimate_res.status_code)
        estimate_body = estimate_res.json()
        self.assertIn("icm_estimated", estimate_body)
        self.assertFalse(bool(estimate_body.get("is_official", True)))

    def test_patient_patch_conflict_when_expected_updated_at_is_stale(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Concurenta", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])

        first_get = self.client.get(f"/api/v1/patients/{patient_id}", headers=self.admin_headers)
        self.assertEqual(200, first_get.status_code)
        stale_updated_at = str(first_get.json().get("updated_at") or "")
        self.assertTrue(stale_updated_at)

        ok_patch = self.client.patch(
            f"/api/v1/patients/{patient_id}",
            json={"phone": "0711000000", "expected_updated_at": stale_updated_at},
            headers=self.admin_headers,
        )
        self.assertEqual(200, ok_patch.status_code)

        db = Database(self.db_path)
        with db._connect() as conn:
            conn.execute(
                "UPDATE patients SET updated_at = ? WHERE id = ?",
                ("2099-12-31 23:59:59", patient_id),
            )
            conn.commit()

        conflict_patch = self.client.patch(
            f"/api/v1/patients/{patient_id}",
            json={"email": "conflict@example.com", "expected_updated_at": stale_updated_at},
            headers=self.admin_headers,
        )
        self.assertEqual(409, conflict_patch.status_code)
        self.assertIn("Conflict de concurenta", str(conflict_patch.json().get("detail") or ""))

    def test_patient_timeline_snapshots_and_restore_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Timeline", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        db = Database(self.db_path)
        sid1 = db.create_patient_snapshot(
            patient_id=patient_id,
            trigger_action="create_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        db.update_patient(
            patient_id,
            {
                "first_name": "Timeline2",
                "last_name": "Demo",
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
            },
        )
        sid2 = db.create_patient_snapshot(
            patient_id=patient_id,
            trigger_action="update_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )

        timeline_res = self.client.get(
            f"/api/v1/patients/{patient_id}/timeline?limit=200&category=snapshot",
            headers=self.medic_headers,
        )
        self.assertEqual(200, timeline_res.status_code)
        timeline_items = timeline_res.json().get("items") or []
        self.assertTrue(any(str(item.get("event_type") or "") == "patient_snapshot" for item in timeline_items))

        snapshots_res = self.client.get(
            f"/api/v1/patients/{patient_id}/snapshots?limit=50",
            headers=self.medic_headers,
        )
        self.assertEqual(200, snapshots_res.status_code)
        snapshot_items = snapshots_res.json().get("items") or []
        snapshot_ids = {int(item.get("id") or 0) for item in snapshot_items}
        self.assertIn(int(sid1), snapshot_ids)
        self.assertIn(int(sid2), snapshot_ids)

        snapshot_res = self.client.get(
            f"/api/v1/patients/{patient_id}/snapshots/{sid2}",
            headers=self.medic_headers,
        )
        self.assertEqual(200, snapshot_res.status_code)
        self.assertEqual(int(sid2), int(snapshot_res.json().get("id") or 0))

        diff_res = self.client.get(
            f"/api/v1/patients/{patient_id}/snapshots/{sid2}/diff",
            headers=self.medic_headers,
        )
        self.assertEqual(200, diff_res.status_code)
        diff_body = diff_res.json()
        self.assertEqual(int(sid2), int(diff_body.get("to_snapshot_id") or 0))
        self.assertIn("changed_fields", diff_body)

        forbidden = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{sid1}/restore",
            json={"reason": "medic should be forbidden"},
            headers=self.medic_headers,
        )
        self.assertEqual(403, forbidden.status_code)

        missing_reason = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{sid1}/restore",
            json={"reason": "   "},
            headers=self.admin_headers,
        )
        self.assertEqual(400, missing_reason.status_code)

        restore_res = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{sid1}/restore",
            json={"reason": "admin restore test"},
            headers=self.admin_headers,
        )
        self.assertEqual(200, restore_res.status_code)
        restore_body = restore_res.json()
        self.assertTrue(bool(restore_body.get("ok")))
        self.assertEqual(patient_id, int(restore_body.get("patient_id") or 0))
        self.assertGreater(int(restore_body.get("backup_snapshot_id") or 0), 0)
        self.assertGreater(int(restore_body.get("post_snapshot_id") or 0), 0)

    def test_list_patients_contract(self) -> None:
        create_a = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Ilie", "last_name": "Mihai"},
            headers=self.admin_headers,
        )
        create_b = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Ana", "last_name": "Popa"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_a.status_code)
        self.assertEqual(201, create_b.status_code)
        res = self.client.get(
            "/api/v1/patients?search=ilie&status_filter=all&status_date=2026-03-06",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        self.assertIn("filters", body)
        self.assertEqual("ilie", body["filters"]["search"])
        names = {f"{item.get('last_name')} {item.get('first_name')}".strip() for item in body["items"]}
        self.assertIn("Mihai Ilie", names)

    def test_restore_snapshot_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "RestoreIdem", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        db = Database(self.db_path)
        snapshot_id = db.create_patient_snapshot(
            patient_id=patient_id,
            trigger_action="create_patient",
            trigger_source="unit_test",
            created_by_user_id=1,
        )
        idem_headers = {**self.admin_headers, "Idempotency-Key": "idem-restore-snapshot-001"}

        first = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/restore",
            json={"reason": "idempotency restore"},
            headers=idem_headers,
        )
        self.assertEqual(200, first.status_code)
        first_body = first.json()
        self.assertTrue(bool(first_body.get("ok")))
        self.assertGreater(int(first_body.get("backup_snapshot_id") or 0), 0)
        self.assertGreater(int(first_body.get("post_snapshot_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/restore",
            json={"reason": "idempotency restore"},
            headers=idem_headers,
        )
        self.assertEqual(200, second.status_code)
        second_body = second.json()
        self.assertEqual(first_body.get("backup_snapshot_id"), second_body.get("backup_snapshot_id"))
        self.assertEqual(first_body.get("post_snapshot_id"), second_body.get("post_snapshot_id"))

        mismatch = self.client.post(
            f"/api/v1/patients/{patient_id}/snapshots/{snapshot_id}/restore",
            json={"reason": "different reason"},
            headers=idem_headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_delete_patient_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Sterge", "last_name": "Test"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        forbidden = self.client.delete(f"/api/v1/patients/{patient_id}", headers=self.medic_headers)
        self.assertEqual(403, forbidden.status_code)
        deleted = self.client.delete(f"/api/v1/patients/{patient_id}", headers=self.admin_headers)
        self.assertEqual(200, deleted.status_code)
        self.assertTrue(bool(deleted.json().get("deleted")))
        missing_after = self.client.get(f"/api/v1/patients/{patient_id}", headers=self.admin_headers)
        self.assertEqual(404, missing_after.status_code)

    def test_delete_patient_conflict_when_expected_updated_at_is_stale(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "DeleteConflict", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])

        first_get = self.client.get(f"/api/v1/patients/{patient_id}", headers=self.admin_headers)
        self.assertEqual(200, first_get.status_code)
        stale_updated_at = str(first_get.json().get("updated_at") or "")
        self.assertTrue(stale_updated_at)

        db = Database(self.db_path)
        with db._connect() as conn:
            conn.execute(
                "UPDATE patients SET updated_at = ? WHERE id = ?",
                ("2099-12-31 23:59:59", patient_id),
            )
            conn.commit()

        conflict = self.client.delete(
            f"/api/v1/patients/{patient_id}",
            headers={**self.admin_headers, "X-Expected-Updated-At": stale_updated_at},
        )
        self.assertEqual(409, conflict.status_code)
        self.assertIn("Conflict de concurenta", str(conflict.json().get("detail") or ""))

    def test_delete_patient_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "DeleteIdem", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        get_res = self.client.get(f"/api/v1/patients/{patient_id}", headers=self.admin_headers)
        self.assertEqual(200, get_res.status_code)
        updated_at = str(get_res.json().get("updated_at") or "")
        self.assertTrue(updated_at)
        idem_headers = {
            **self.admin_headers,
            "Idempotency-Key": "idem-delete-patient-001",
            "X-Expected-Updated-At": updated_at,
        }

        first = self.client.delete(f"/api/v1/patients/{patient_id}", headers=idem_headers)
        self.assertEqual(200, first.status_code)
        self.assertTrue(bool(first.json().get("deleted")))

        second = self.client.delete(f"/api/v1/patients/{patient_id}", headers=idem_headers)
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.delete(
            f"/api/v1/patients/{patient_id}",
            headers={
                **self.admin_headers,
                "Idempotency-Key": "idem-delete-patient-001",
                "X-Expected-Updated-At": "1900-01-01 00:00:00",
            },
        )
        self.assertEqual(409, mismatch.status_code)

    def test_patient_admissions_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Internat", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)

        list_res = self.client.get(
            f"/api/v1/patients/{patient_id}/admissions?include_closed=1&limit=50",
            headers=self.medic_headers,
        )
        self.assertEqual(200, list_res.status_code)
        body = list_res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(admission_id, ids)

        active_res = self.client.get(
            f"/api/v1/patients/{patient_id}/admissions/active",
            headers=self.medic_headers,
        )
        self.assertEqual(200, active_res.status_code)
        active_item = active_res.json().get("item") or {}
        self.assertEqual(admission_id, int(active_item.get("id") or 0))

    def test_create_admission_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Internare", "last_name": "Idem"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        payload = {
            "admission_type": "inpatient",
            "triage_level": "2",
            "department": "Ortopedie",
            "ward": "A2",
            "bed": "12",
            "attending_clinician": "Dr Test",
            "chief_complaint": "Durere acuta",
            "admitted_at": "2026-03-07 08:00:00",
        }
        headers = {**self.admin_headers, "Idempotency-Key": "idem-create-admission-001"}

        first = self.client.post(
            f"/api/v1/patients/{patient_id}/admissions",
            json=payload,
            headers=headers,
        )
        self.assertEqual(201, first.status_code)
        first_body = first.json()
        self.assertGreater(int(first_body.get("admission_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/patients/{patient_id}/admissions",
            json=payload,
            headers=headers,
        )
        self.assertEqual(201, second.status_code)
        self.assertEqual(first_body.get("admission_id"), second.json().get("admission_id"))

        mismatch = self.client.post(
            f"/api/v1/patients/{patient_id}/admissions",
            json={**payload, "bed": "13"},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_discharge_admission_contract_with_idempotency(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Externare", "last_name": "Idem"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])

        admission_res = self.client.post(
            f"/api/v1/patients/{patient_id}/admissions",
            json={
                "admission_type": "inpatient",
                "triage_level": "2",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "21",
                "attending_clinician": "Dr Test",
                "chief_complaint": "Durere",
                "admitted_at": "2026-03-07 09:00:00",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(201, admission_res.status_code)
        admission_id = int(admission_res.json().get("admission_id") or 0)
        self.assertGreater(admission_id, 0)

        missing_booking = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "fara booking"},
            headers=self.admin_headers,
        )
        self.assertEqual(409, missing_booking.status_code)

        db = Database(self.db_path)
        now_dt = datetime.now()
        starts_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        ends_at = (now_dt + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        _ = db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "21",
                "operating_room": "",
                "attending_clinician": "Dr Test",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "notes": "booking externare",
            },
            user_id=1,
        )
        headers = {**self.admin_headers, "Idempotency-Key": "idem-discharge-admission-001"}

        first = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "externare test"},
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        first_body = first.json()
        self.assertEqual("discharged", str(first_body.get("status") or ""))
        self.assertGreaterEqual(int(first_body.get("booking_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "externare test"},
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first_body, second.json())

        mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "alt rezumat"},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_admission_transfers_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Transfer", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        transfer_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/transfers?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, transfer_res.status_code)
        body = transfer_res.json()
        self.assertIn("items", body)
        self.assertGreaterEqual(len(body["items"]), 1)
        first = body["items"][0]
        self.assertEqual(admission_id, int(first.get("admission_id") or 0))
        self.assertIn(first.get("action_type"), {"admit", "transfer", "discharge"})

    def test_transfer_admission_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "TransferWrite", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        headers = {**self.admin_headers, "Idempotency-Key": "idem-transfer-admission-001"}
        payload = {
            "to_department": "ATI",
            "to_ward": "B1",
            "to_bed": "5",
            "transferred_at": "2026-03-07 12:00:00",
            "notes": "transfer idempotent",
        }

        first = self.client.post(
            f"/api/v1/admissions/{admission_id}/transfer",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual("ATI", str(first.json().get("department") or ""))

        second = self.client.post(
            f"/api/v1/admissions/{admission_id}/transfer",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/transfer",
            json={**payload, "to_bed": "6"},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_case_validation_and_finalize_case_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Finalize", "last_name": "Case"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)

        before = self.client.get(
            f"/api/v1/admissions/{admission_id}/case-validation?require_financial_closure=0&require_siui_drg_submission=0",
            headers=self.medic_headers,
        )
        self.assertEqual(200, before.status_code)
        before_body = before.json()
        self.assertFalse(bool(before_body.get("eligible")))
        self.assertGreater(len(before_body.get("errors") or []), 0)

        finalize_fail = self.client.post(
            f"/api/v1/admissions/{admission_id}/finalize-case",
            json={"require_financial_closure": False, "require_siui_drg_submission": False},
            headers=self.admin_headers,
        )
        self.assertEqual(400, finalize_fail.status_code)

        db = Database(self.db_path)
        now_dt = datetime.now()
        starts_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        ends_at = (now_dt + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        _ = db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "12",
                "operating_room": "",
                "attending_clinician": "Dr Test",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "notes": "booking externare",
            },
            user_id=1,
        )
        discharge = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "externare pentru finalizare"},
            headers=self.admin_headers,
        )
        self.assertEqual(200, discharge.status_code)

        db.upsert_admission_diagnoses(
            admission_id,
            {
                "referral_diagnosis": "R51",
                "admission_diagnosis": "I10",
                "discharge_diagnosis": "I10",
                "secondary_diagnoses": "E11",
                "dietary_regimen": "standard",
                "admission_criteria": "durere, valori tensionale crescute",
                "discharge_criteria": "stabil hemodinamic",
            },
            user_id=1,
        )
        _ = db.create_billing_record(
            admission_id=admission_id,
            record_type="final",
            amount=100.0,
            issued_at=(now_dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            notes="decont final",
            user_id=1,
        )

        headers = {**self.admin_headers, "Idempotency-Key": "idem-finalize-case-001"}
        finalize_ok = self.client.post(
            f"/api/v1/admissions/{admission_id}/finalize-case",
            json={"require_financial_closure": False, "require_siui_drg_submission": False},
            headers=headers,
        )
        self.assertEqual(200, finalize_ok.status_code)
        self.assertTrue(bool(finalize_ok.json().get("finalized")))

        finalize_retry = self.client.post(
            f"/api/v1/admissions/{admission_id}/finalize-case",
            json={"require_financial_closure": False, "require_siui_drg_submission": False},
            headers=headers,
        )
        self.assertEqual(200, finalize_retry.status_code)
        self.assertEqual(finalize_ok.json(), finalize_retry.json())

        finalize_mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/finalize-case",
            json={"require_financial_closure": True, "require_siui_drg_submission": False},
            headers=headers,
        )
        self.assertEqual(409, finalize_mismatch.status_code)

    def test_save_admission_diagnoses_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Diag", "last_name": "Contract"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        headers = {**self.admin_headers, "Idempotency-Key": "idem-adm-diagnoses-001"}
        payload = {
            "referral_diagnosis": "R51",
            "admission_diagnosis": "I10",
            "discharge_diagnosis": "I10",
            "secondary_diagnoses": "E11",
            "dietary_regimen": "standard",
            "admission_criteria": "criteria A",
            "discharge_criteria": "criteria B",
        }

        first = self.client.post(
            f"/api/v1/admissions/{admission_id}/diagnoses",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual(admission_id, int(first.json().get("admission_id") or 0))

        second = self.client.post(
            f"/api/v1/admissions/{admission_id}/diagnoses",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/diagnoses",
            json={**payload, "admission_diagnosis": "J18"},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_issue_billing_record_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "BillingWrite", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        now_dt = datetime.now()
        starts_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        ends_at = (now_dt + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        _ = db.create_care_booking(
            {
                "patient_id": str(patient_id),
                "booking_type": "discharge",
                "department": "Ortopedie",
                "ward": "A2",
                "bed": "12",
                "operating_room": "",
                "attending_clinician": "Dr Test",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "notes": "booking externare",
            },
            user_id=1,
        )
        discharge = self.client.post(
            f"/api/v1/admissions/{admission_id}/discharge",
            json={"discharge_summary": "externare pentru decont final"},
            headers=self.admin_headers,
        )
        self.assertEqual(200, discharge.status_code)

        headers = {**self.admin_headers, "Idempotency-Key": "idem-issue-billing-001"}
        payload = {
            "record_type": "final",
            "amount": 222.5,
            "issued_at": (now_dt + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            "notes": "decont final",
            "cost_center_id": 0,
        }
        first = self.client.post(
            f"/api/v1/admissions/{admission_id}/billing-records",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        self.assertGreater(int(first.json().get("billing_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/admissions/{admission_id}/billing-records",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/billing-records",
            json={**payload, "amount": 333.0},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_issue_case_invoice_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "InvoiceWrite", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        headers = {**self.admin_headers, "Idempotency-Key": "idem-issue-invoice-001"}
        payload = {
            "invoice_type": "proforma",
            "series": "PF",
            "invoice_number": "INV-IDEM-001",
            "subtotal": 100.0,
            "tax_amount": 19.0,
            "total_amount": 119.0,
            "issued_at": "2026-03-07 14:00:00",
            "due_date": "2026-03-15",
            "status": "issued",
            "notes": "invoice idem",
            "partner_id": 0,
            "cost_center_id": 0,
        }
        first = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-invoices",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        self.assertGreater(int(first.json().get("invoice_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-invoices",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-invoices",
            json={**payload, "invoice_number": "INV-IDEM-002"},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_register_invoice_payment_idempotency_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "PaymentWrite", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        invoice_id = db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PF",
            invoice_number="INV-PAY-IDEM-001",
            subtotal=100.0,
            tax_amount=19.0,
            total_amount=119.0,
            issued_at="2026-03-07 15:00:00",
            due_date="2026-03-16",
            status="issued",
            notes="invoice for payment idem",
            user_id=1,
        )

        headers = {**self.admin_headers, "Idempotency-Key": "idem-register-payment-001"}
        payload = {
            "amount": 59.5,
            "paid_at": "2026-03-07 15:10:00",
            "payment_method": "card",
            "reference_no": "PAY-IDEM-001",
            "notes": "partial payment",
        }
        first = self.client.post(
            f"/api/v1/case-invoices/{invoice_id}/payments",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, first.status_code)
        self.assertGreater(int(first.json().get("payment_id") or 0), 0)

        second = self.client.post(
            f"/api/v1/case-invoices/{invoice_id}/payments",
            json=payload,
            headers=headers,
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json(), second.json())

        mismatch = self.client.post(
            f"/api/v1/case-invoices/{invoice_id}/payments",
            json={**payload, "amount": 60.0},
            headers=headers,
        )
        self.assertEqual(409, mismatch.status_code)

    def test_admission_orders_and_vitals_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "AdmissionData", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        order_id = db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma completa",
            user_id=1,
        )
        vital_id = db.add_vital(
            patient_id=patient_id,
            admission_id=admission_id,
            payload={
                "recorded_at": "2026-03-06 12:00:00",
                "temperature_c": "37.2",
                "systolic_bp": "120",
                "diastolic_bp": "80",
                "pulse": "82",
                "respiratory_rate": "18",
                "spo2": "98",
                "pain_score": "2",
                "notes": "admission vitals",
            },
            user_id=1,
        )

        orders_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/orders?limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, orders_res.status_code)
        orders_items = orders_res.json().get("items") or []
        order_ids = {int(item.get("id") or 0) for item in orders_items}
        self.assertIn(int(order_id), order_ids)

        vitals_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/vitals?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, vitals_res.status_code)
        vitals_items = vitals_res.json().get("items") or []
        vital_ids = {int(item.get("id") or 0) for item in vitals_items}
        self.assertIn(int(vital_id), vital_ids)

    def test_institutional_reports_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Raport", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        report_id = db.create_institutional_report(
            admission_id=admission_id,
            report_type="siui",
            user_id=1,
        )

        list_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/institutional-reports?limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, list_res.status_code)
        body = list_res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(report_id), ids)

        status_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/institutional-reports/status",
            headers=self.medic_headers,
        )
        self.assertEqual(200, status_res.status_code)
        status_body = status_res.json()
        self.assertIn("siui", status_body)
        self.assertIn("drg", status_body)
        self.assertIsInstance(status_body["siui"], bool)
        self.assertIsInstance(status_body["drg"], bool)

    def test_billing_records_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Billing", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        billing_id = db.create_billing_record(
            admission_id=admission_id,
            record_type="partial",
            amount=123.45,
            issued_at="2026-03-06 10:15:00",
            notes="test billing",
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/admissions/{admission_id}/billing-records?limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(billing_id), ids)

    def test_case_invoices_and_payments_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Invoice", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        invoice_id = db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PF",
            invoice_number="INV-1",
            subtotal=100.0,
            tax_amount=19.0,
            total_amount=None,
            issued_at="2026-03-06 10:40:00",
            due_date="2026-03-15",
            status="issued",
            notes="invoice test",
            user_id=1,
        )
        payment_id = db.register_invoice_payment(
            invoice_id=invoice_id,
            amount=50.0,
            paid_at="2026-03-06 10:45:00",
            payment_method="cash",
            reference_no="R-INV-1",
            notes="partial",
            user_id=1,
        )

        inv_res = self.client.get(
            f"/api/v1/admissions/{admission_id}/case-invoices?limit=500",
            headers=self.medic_headers,
        )
        self.assertEqual(200, inv_res.status_code)
        inv_items = inv_res.json().get("items") or []
        inv_ids = {int(item.get("id") or 0) for item in inv_items}
        self.assertIn(int(invoice_id), inv_ids)

        pay_res = self.client.get(
            f"/api/v1/case-invoices/{invoice_id}/payments?limit=500",
            headers=self.medic_headers,
        )
        self.assertEqual(200, pay_res.status_code)
        pay_items = pay_res.json().get("items") or []
        pay_ids = {int(item.get("id") or 0) for item in pay_items}
        self.assertIn(int(payment_id), pay_ids)

    def test_offer_contracts_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Offer", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        offer_id = db.create_offer_contract(
            patient_id=patient_id,
            admission_id=admission_id,
            doc_type="offer",
            package_name="Pachet Test",
            accommodation_type="single",
            base_price=1000.0,
            discount_amount=100.0,
            final_price=None,
            status="draft",
            notes="offer test",
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/admissions/{admission_id}/offer-contracts?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(offer_id), ids)

    def test_medical_leaves_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Leave", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        leave_id = db.create_medical_leave(
            admission_id=admission_id,
            series="CM",
            leave_number="1001",
            issued_at="2026-03-06 11:20:00",
            start_date="2026-03-07",
            end_date="2026-03-10",
            diagnosis_code="M16",
            notes="leave test",
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/admissions/{admission_id}/medical-leaves?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(leave_id), ids)

    def test_case_consumptions_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Consumption", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        consumption_id = db.add_case_consumption(
            admission_id=admission_id,
            item_type="material",
            item_name="Bandaj",
            unit="buc",
            quantity=2.0,
            unit_price=10.0,
            source="ward_stock",
            notes="consumption test",
            recorded_at="2026-03-06 11:30:00",
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/admissions/{admission_id}/case-consumptions?limit=500",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(consumption_id), ids)

    def test_orders_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Order", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        order_id = db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma completa",
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/patients/{patient_id}/orders?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(order_id), ids)

    def test_vitals_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Vitals", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        vital_id = db.add_vital(
            patient_id=patient_id,
            admission_id=admission_id,
            payload={
                "recorded_at": "2026-03-06 12:00:00",
                "temperature_c": "37.2",
                "systolic_bp": "120",
                "diastolic_bp": "80",
                "pulse": "82",
                "respiratory_rate": "18",
                "spo2": "98",
                "pain_score": "2",
                "notes": "vitals test",
            },
            user_id=1,
        )

        res = self.client.get(
            f"/api/v1/patients/{patient_id}/vitals?limit=300",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(vital_id), ids)

    def test_visits_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Visits", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        db = Database(self.db_path)
        visit_id = db.add_visit(
            patient_id=patient_id,
            visit_date="2026-03-06",
            reason="Control",
            diagnosis="J20.9",
            treatment="Simptomatic",
            notes="visit test",
        )

        res = self.client.get(
            f"/api/v1/patients/{patient_id}/visits?limit=200",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(visit_id), ids)

    def test_val2_write_endpoints_idempotency_and_rbac_contract(self) -> None:
        asistent_headers = {"X-Role": "asistent", "X-User-Id": "3"}
        receptie_headers = {"X-Role": "receptie", "X-User-Id": "4"}
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Val2", "last_name": "Writes"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)

        visit_headers = {**self.medic_headers, "Idempotency-Key": "idem-val2-visit-001"}
        visit_payload = {
            "visit_date": "2026-03-08",
            "reason": "Control periodic",
            "diagnosis": "I10",
            "treatment": "Monitorizare",
            "notes": "note val2",
        }
        visit_1 = self.client.post(
            f"/api/v1/patients/{patient_id}/visits",
            json=visit_payload,
            headers=visit_headers,
        )
        self.assertEqual(200, visit_1.status_code)
        visit_id = int(visit_1.json().get("visit_id") or 0)
        self.assertGreater(visit_id, 0)
        visit_2 = self.client.post(
            f"/api/v1/patients/{patient_id}/visits",
            json=visit_payload,
            headers=visit_headers,
        )
        self.assertEqual(200, visit_2.status_code)
        self.assertEqual(visit_id, int(visit_2.json().get("visit_id") or 0))
        visit_mismatch = self.client.post(
            f"/api/v1/patients/{patient_id}/visits",
            json={**visit_payload, "reason": "Alt motiv"},
            headers=visit_headers,
        )
        self.assertEqual(409, visit_mismatch.status_code)
        visit_forbidden = self.client.post(
            f"/api/v1/patients/{patient_id}/visits",
            json=visit_payload,
            headers=receptie_headers,
        )
        self.assertEqual(403, visit_forbidden.status_code)

        delete_forbidden = self.client.delete(
            f"/api/v1/visits/{visit_id}",
            headers=asistent_headers,
        )
        self.assertEqual(403, delete_forbidden.status_code)
        delete_headers = {**self.medic_headers, "Idempotency-Key": "idem-val2-visit-delete-001"}
        delete_1 = self.client.delete(
            f"/api/v1/visits/{visit_id}",
            headers=delete_headers,
        )
        self.assertEqual(200, delete_1.status_code)
        self.assertTrue(bool(delete_1.json().get("deleted")))
        delete_2 = self.client.delete(
            f"/api/v1/visits/{visit_id}",
            headers=delete_headers,
        )
        self.assertEqual(200, delete_2.status_code)
        self.assertEqual(delete_1.json(), delete_2.json())

        order_headers = {**self.medic_headers, "Idempotency-Key": "idem-val2-order-001"}
        order_payload = {
            "admission_id": admission_id,
            "order_type": "lab",
            "priority": "urgent",
            "order_text": "Set analize extins",
        }
        order_1 = self.client.post(
            f"/api/v1/patients/{patient_id}/orders",
            json=order_payload,
            headers=order_headers,
        )
        self.assertEqual(200, order_1.status_code)
        order_id = int(order_1.json().get("order_id") or 0)
        self.assertGreater(order_id, 0)
        order_2 = self.client.post(
            f"/api/v1/patients/{patient_id}/orders",
            json=order_payload,
            headers=order_headers,
        )
        self.assertEqual(200, order_2.status_code)
        self.assertEqual(order_id, int(order_2.json().get("order_id") or 0))
        order_mismatch = self.client.post(
            f"/api/v1/patients/{patient_id}/orders",
            json={**order_payload, "order_text": "Alt text ordin"},
            headers=order_headers,
        )
        self.assertEqual(409, order_mismatch.status_code)
        order_forbidden = self.client.post(
            f"/api/v1/patients/{patient_id}/orders",
            json=order_payload,
            headers=asistent_headers,
        )
        self.assertEqual(403, order_forbidden.status_code)

        order_status_headers = {**asistent_headers, "Idempotency-Key": "idem-val2-order-status-001"}
        order_status_1 = self.client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "in_progress"},
            headers=order_status_headers,
        )
        self.assertEqual(200, order_status_1.status_code)
        order_status_2 = self.client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "in_progress"},
            headers=order_status_headers,
        )
        self.assertEqual(200, order_status_2.status_code)
        self.assertEqual(order_status_1.json(), order_status_2.json())
        order_status_mismatch = self.client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "done"},
            headers=order_status_headers,
        )
        self.assertEqual(409, order_status_mismatch.status_code)
        order_status_forbidden = self.client.patch(
            f"/api/v1/orders/{order_id}/status",
            json={"status": "cancelled"},
            headers=receptie_headers,
        )
        self.assertEqual(403, order_status_forbidden.status_code)

        vital_headers = {**asistent_headers, "Idempotency-Key": "idem-val2-vital-001"}
        vital_payload = {
            "admission_id": admission_id,
            "recorded_at": "2026-03-08 10:00:00",
            "temperature_c": "37.4",
            "systolic_bp": "120",
            "diastolic_bp": "80",
            "pulse": "82",
            "respiratory_rate": "18",
            "spo2": "98",
            "pain_score": "2",
            "notes": "vitals val2",
        }
        vital_1 = self.client.post(
            f"/api/v1/patients/{patient_id}/vitals",
            json=vital_payload,
            headers=vital_headers,
        )
        self.assertEqual(200, vital_1.status_code)
        self.assertGreater(int(vital_1.json().get("vital_id") or 0), 0)
        vital_2 = self.client.post(
            f"/api/v1/patients/{patient_id}/vitals",
            json=vital_payload,
            headers=vital_headers,
        )
        self.assertEqual(200, vital_2.status_code)
        vital_mismatch = self.client.post(
            f"/api/v1/patients/{patient_id}/vitals",
            json={**vital_payload, "notes": "alte vitale"},
            headers=vital_headers,
        )
        self.assertEqual(409, vital_mismatch.status_code)
        vital_forbidden = self.client.post(
            f"/api/v1/patients/{patient_id}/vitals",
            json=vital_payload,
            headers=receptie_headers,
        )
        self.assertEqual(403, vital_forbidden.status_code)

        offer_headers = {**receptie_headers, "Idempotency-Key": "idem-val2-offer-001"}
        offer_payload = {
            "doc_type": "offer",
            "package_name": "Pachet Plus",
            "accommodation_type": "single",
            "base_price": 1200.0,
            "discount_amount": 150.0,
            "final_price": None,
            "status": "draft",
            "notes": "oferta val2",
        }
        offer_1 = self.client.post(
            f"/api/v1/admissions/{admission_id}/offer-contracts",
            json=offer_payload,
            headers=offer_headers,
        )
        self.assertEqual(200, offer_1.status_code)
        offer_id = int(offer_1.json().get("offer_id") or 0)
        self.assertGreater(offer_id, 0)
        offer_2 = self.client.post(
            f"/api/v1/admissions/{admission_id}/offer-contracts",
            json=offer_payload,
            headers=offer_headers,
        )
        self.assertEqual(200, offer_2.status_code)
        self.assertEqual(offer_id, int(offer_2.json().get("offer_id") or 0))
        offer_mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/offer-contracts",
            json={**offer_payload, "package_name": "Pachet Alt"},
            headers=offer_headers,
        )
        self.assertEqual(409, offer_mismatch.status_code)

        offer_status_headers = {**self.admin_headers, "Idempotency-Key": "idem-val2-offer-status-001"}
        offer_status_1 = self.client.patch(
            f"/api/v1/offer-contracts/{offer_id}/status",
            json={"status": "approved"},
            headers=offer_status_headers,
        )
        self.assertEqual(200, offer_status_1.status_code)
        offer_status_2 = self.client.patch(
            f"/api/v1/offer-contracts/{offer_id}/status",
            json={"status": "approved"},
            headers=offer_status_headers,
        )
        self.assertEqual(200, offer_status_2.status_code)
        offer_status_mismatch = self.client.patch(
            f"/api/v1/offer-contracts/{offer_id}/status",
            json={"status": "signed"},
            headers=offer_status_headers,
        )
        self.assertEqual(409, offer_status_mismatch.status_code)

        leave_headers = {**self.medic_headers, "Idempotency-Key": "idem-val2-leave-001"}
        leave_payload = {
            "series": "CM",
            "leave_number": "9988",
            "issued_at": "2026-03-08 11:00:00",
            "start_date": "2026-03-09",
            "end_date": "2026-03-11",
            "diagnosis_code": "M16",
            "notes": "leave val2",
            "series_rule_id": None,
        }
        leave_1 = self.client.post(
            f"/api/v1/admissions/{admission_id}/medical-leaves",
            json=leave_payload,
            headers=leave_headers,
        )
        self.assertEqual(200, leave_1.status_code)
        leave_id = int(leave_1.json().get("leave_id") or 0)
        self.assertGreater(leave_id, 0)
        leave_2 = self.client.post(
            f"/api/v1/admissions/{admission_id}/medical-leaves",
            json=leave_payload,
            headers=leave_headers,
        )
        self.assertEqual(200, leave_2.status_code)
        self.assertEqual(leave_id, int(leave_2.json().get("leave_id") or 0))
        leave_mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/medical-leaves",
            json={**leave_payload, "leave_number": "9989"},
            headers=leave_headers,
        )
        self.assertEqual(409, leave_mismatch.status_code)

        leave_cancel_forbidden = self.client.patch(
            f"/api/v1/medical-leaves/{leave_id}/cancel",
            headers=receptie_headers,
        )
        self.assertEqual(403, leave_cancel_forbidden.status_code)
        leave_cancel_headers = {**self.medic_headers, "Idempotency-Key": "idem-val2-leave-cancel-001"}
        leave_cancel_1 = self.client.patch(
            f"/api/v1/medical-leaves/{leave_id}/cancel",
            headers=leave_cancel_headers,
        )
        self.assertEqual(200, leave_cancel_1.status_code)
        leave_cancel_2 = self.client.patch(
            f"/api/v1/medical-leaves/{leave_id}/cancel",
            headers=leave_cancel_headers,
        )
        self.assertEqual(200, leave_cancel_2.status_code)
        self.assertEqual(leave_cancel_1.json(), leave_cancel_2.json())

        consumption_headers = {**asistent_headers, "Idempotency-Key": "idem-val2-consumption-001"}
        consumption_payload = {
            "item_type": "material",
            "item_name": "Bandaj steril",
            "unit": "buc",
            "quantity": 3.0,
            "unit_price": 10.0,
            "source": "ward_stock",
            "notes": "consum val2",
            "recorded_at": "2026-03-08 12:00:00",
            "partner_id": None,
            "cost_center_id": None,
        }
        consumption_1 = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-consumptions",
            json=consumption_payload,
            headers=consumption_headers,
        )
        self.assertEqual(200, consumption_1.status_code)
        consumption_id = int(consumption_1.json().get("consumption_id") or 0)
        self.assertGreater(consumption_id, 0)
        consumption_2 = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-consumptions",
            json=consumption_payload,
            headers=consumption_headers,
        )
        self.assertEqual(200, consumption_2.status_code)
        self.assertEqual(consumption_id, int(consumption_2.json().get("consumption_id") or 0))
        consumption_mismatch = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-consumptions",
            json={**consumption_payload, "item_name": "Compresa"},
            headers=consumption_headers,
        )
        self.assertEqual(409, consumption_mismatch.status_code)

        consumption_status_headers = {**receptie_headers, "Idempotency-Key": "idem-val2-consumption-status-001"}
        consumption_status_1 = self.client.patch(
            f"/api/v1/case-consumptions/{consumption_id}/status",
            json={"status": "sent_pharmacy"},
            headers=consumption_status_headers,
        )
        self.assertEqual(200, consumption_status_1.status_code)
        consumption_status_2 = self.client.patch(
            f"/api/v1/case-consumptions/{consumption_id}/status",
            json={"status": "sent_pharmacy"},
            headers=consumption_status_headers,
        )
        self.assertEqual(200, consumption_status_2.status_code)
        consumption_status_mismatch = self.client.patch(
            f"/api/v1/case-consumptions/{consumption_id}/status",
            json={"status": "dispensed"},
            headers=consumption_status_headers,
        )
        self.assertEqual(409, consumption_status_mismatch.status_code)

        db = Database(self.db_path)
        invoice_id = db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PF",
            invoice_number="INV-VAL2-1",
            subtotal=100.0,
            tax_amount=19.0,
            total_amount=None,
            issued_at="2026-03-08 12:10:00",
            due_date="2026-03-20",
            status="issued",
            notes="invoice val2",
            user_id=1,
        )
        invoice_status_headers = {**receptie_headers, "Idempotency-Key": "idem-val2-invoice-status-001"}
        invoice_status_1 = self.client.patch(
            f"/api/v1/case-invoices/{invoice_id}/status",
            json={"status": "cancelled"},
            headers=invoice_status_headers,
        )
        self.assertEqual(200, invoice_status_1.status_code)
        invoice_status_2 = self.client.patch(
            f"/api/v1/case-invoices/{invoice_id}/status",
            json={"status": "cancelled"},
            headers=invoice_status_headers,
        )
        self.assertEqual(200, invoice_status_2.status_code)
        invoice_status_mismatch = self.client.patch(
            f"/api/v1/case-invoices/{invoice_id}/status",
            json={"status": "issued"},
            headers=invoice_status_headers,
        )
        self.assertEqual(409, invoice_status_mismatch.status_code)
        invoice_status_forbidden = self.client.patch(
            f"/api/v1/case-invoices/{invoice_id}/status",
            json={"status": "issued"},
            headers=asistent_headers,
        )
        self.assertEqual(403, invoice_status_forbidden.status_code)

    def test_val2_write_error_mapping_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Val2Err", "last_name": "Map"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)

        miss_visit = self.client.delete(
            "/api/v1/visits/999999",
            headers=self.medic_headers,
        )
        self.assertEqual(404, miss_visit.status_code)

        invalid_order_status = self.client.patch(
            "/api/v1/orders/999999/status",
            json={"status": "no_such_status"},
            headers=self.medic_headers,
        )
        self.assertEqual(404, invalid_order_status.status_code)

        order_create_missing_patient = self.client.post(
            "/api/v1/patients/999999/orders",
            json={"admission_id": admission_id, "order_type": "lab", "priority": "normal", "order_text": "x"},
            headers=self.medic_headers,
        )
        self.assertEqual(404, order_create_missing_patient.status_code)

        offer_missing_admission = self.client.post(
            "/api/v1/admissions/999999/offer-contracts",
            json={
                "doc_type": "offer",
                "package_name": "P",
                "accommodation_type": "single",
                "base_price": 100.0,
                "discount_amount": 0.0,
                "final_price": None,
                "status": "draft",
                "notes": "",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(404, offer_missing_admission.status_code)

        medical_leave_bad_payload = self.client.post(
            f"/api/v1/admissions/{admission_id}/medical-leaves",
            json={
                "series": "CM",
                "leave_number": "BAD-1",
                "issued_at": "bad date",
                "start_date": "2026-03-10",
                "end_date": "2026-03-09",
                "diagnosis_code": "M16",
                "notes": "",
                "series_rule_id": None,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(400, medical_leave_bad_payload.status_code)

        consumption_create = self.client.post(
            f"/api/v1/admissions/{admission_id}/case-consumptions",
            json={
                "item_type": "material",
                "item_name": "Test",
                "unit": "buc",
                "quantity": 1.0,
                "unit_price": 5.0,
                "source": "ward_stock",
                "notes": "",
                "recorded_at": "2026-03-08 12:30:00",
                "partner_id": None,
                "cost_center_id": None,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(200, consumption_create.status_code)
        cid = int(consumption_create.json().get("consumption_id") or 0)
        self.assertGreater(cid, 0)
        consumption_invalid_status = self.client.patch(
            f"/api/v1/case-consumptions/{cid}/status",
            json={"status": "invalid_status"},
            headers=self.admin_headers,
        )
        self.assertEqual(400, consumption_invalid_status.status_code)

        invoice_missing = self.client.patch(
            "/api/v1/case-invoices/999999/status",
            json={"status": "issued"},
            headers=self.admin_headers,
        )
        self.assertEqual(404, invoice_missing.status_code)

        db = Database(self.db_path)
        invoice_id = db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PF",
            invoice_number="ERR-INV-1",
            subtotal=200.0,
            tax_amount=38.0,
            total_amount=None,
            issued_at="2026-03-08 12:40:00",
            due_date="2026-03-21",
            status="issued",
            notes="invoice for error mapping",
            user_id=1,
        )
        invoice_not_fully_paid = self.client.patch(
            f"/api/v1/case-invoices/{invoice_id}/status",
            json={"status": "paid"},
            headers=self.admin_headers,
        )
        self.assertEqual(409, invoice_not_fully_paid.status_code)

    def test_medis_investigations_contract(self) -> None:
        create_res = self.client.post(
            "/api/v1/patients",
            json={"first_name": "Medis", "last_name": "Demo"},
            headers=self.admin_headers,
        )
        self.assertEqual(201, create_res.status_code)
        patient_id = int(create_res.json()["id"])
        admission_id = self._seed_active_admission(patient_id)
        db = Database(self.db_path)
        order_id = db.add_order(
            patient_id=patient_id,
            admission_id=admission_id,
            order_type="lab",
            priority="urgent",
            order_text="Hemoleucograma completa",
            user_id=1,
        )
        investigation_id = db.create_medis_investigation(
            order_id=order_id,
            provider="MEDIS",
            external_request_id="REQ-XYZ-1",
            requested_at="2026-03-06 12:20:00",
            request_payload="{\"panel\":\"cbc\"}",
            user_id=1,
            initial_status="sent",
        )

        res = self.client.get(
            f"/api/v1/patients/{patient_id}/medis-investigations?limit=500&admission_id={admission_id}",
            headers=self.medic_headers,
        )
        self.assertEqual(200, res.status_code)
        body = res.json()
        self.assertIn("items", body)
        ids = {int(item.get("id") or 0) for item in body["items"]}
        self.assertIn(int(investigation_id), ids)

    def test_ops_queue_requires_admin(self) -> None:
        forbidden = self.client.get("/api/v1/ops/integration-queue", headers=self.medic_headers)
        self.assertEqual(403, forbidden.status_code)
        allowed = self.client.get("/api/v1/ops/integration-queue", headers=self.admin_headers)
        self.assertEqual(200, allowed.status_code)
        payload = allowed.json()
        self.assertIn("items", payload)
        jobs_forbidden = self.client.get("/api/v1/ops/job-executions", headers=self.medic_headers)
        self.assertEqual(403, jobs_forbidden.status_code)
        jobs_allowed = self.client.get("/api/v1/ops/job-executions", headers=self.admin_headers)
        self.assertEqual(200, jobs_allowed.status_code)
        self.assertIn("items", jobs_allowed.json())

    def test_shadow_sync_ops_contract(self) -> None:
        db = Database(self.db_path)
        db.set_settings(
            {
                "API_INTERNAL_POSTGRES_SHADOW_ENABLED": "1",
                "API_INTERNAL_POSTGRES_SHADOW_MAX_RETRIES": "0",
            }
        )
        _ = db.enqueue_shadow_write_event(
            action_key="POST /api/v1/patients",
            source="unit_test",
            payload_json='{\"demo\":1}',
        )

        status_res = self.client.get("/api/v1/ops/shadow-sync/status", headers=self.admin_headers)
        self.assertEqual(200, status_res.status_code)
        status_body = status_res.json()
        self.assertIn("shadow_mode_enabled", status_body)
        self.assertIn("shadow_backlog_pending", status_body)

        process_res = self.client.post("/api/v1/ops/shadow-sync/process?max_jobs=10", headers=self.admin_headers)
        self.assertEqual(200, process_res.status_code)
        process_body = process_res.json()
        self.assertIn("processed", process_body)

        errors_res = self.client.get("/api/v1/ops/shadow-sync/errors?limit=20", headers=self.admin_headers)
        self.assertEqual(200, errors_res.status_code)
        self.assertIn("items", errors_res.json())

        forbidden = self.client.get("/api/v1/ops/shadow-sync/status", headers=self.medic_headers)
        self.assertEqual(403, forbidden.status_code)


if __name__ == "__main__":
    unittest.main()
