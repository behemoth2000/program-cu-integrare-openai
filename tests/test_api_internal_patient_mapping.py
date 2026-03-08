import unittest

from pacienti_ai_independent.pacienti_ai_app import PacientiAIApp


class ApiInternalPatientMappingTest(unittest.TestCase):
    def _build_app_stub(self) -> PacientiAIApp:
        app = PacientiAIApp.__new__(PacientiAIApp)
        app.patient_vars = {
            "first_name": object(),
            "last_name": object(),
            "primary_diagnosis_icd10": object(),
            "secondary_diagnoses_icd10": object(),
            "free_diagnosis_text": object(),
            "address": object(),
        }
        return app

    def test_normalize_maps_nested_diagnosis(self) -> None:
        app = self._build_app_stub()
        src = {
            "id": 5,
            "first_name": "Ana",
            "last_name": "Pop",
            "address": "X",
            "diagnosis": {
                "primary_icd10": "I10",
                "secondary_icd10": ["E11", "J44"],
                "free_text": "text liber",
            },
        }
        out = app._normalize_patient_record_for_form(src)
        self.assertEqual("I10", out["primary_diagnosis_icd10"])
        self.assertEqual("E11,J44", out["secondary_diagnoses_icd10"])
        self.assertEqual("text liber", out["free_diagnosis_text"])
        self.assertNotIn("diagnosis", out)

    def test_normalize_keeps_existing_flat_diagnosis(self) -> None:
        app = self._build_app_stub()
        src = {
            "id": 6,
            "first_name": "Ion",
            "last_name": "Ionescu",
            "primary_diagnosis_icd10": "K52",
            "secondary_diagnoses_icd10": "E11",
            "free_diagnosis_text": "legacy",
            "diagnosis": {
                "primary_icd10": "I10",
                "secondary_icd10": ["J44"],
                "free_text": "api",
            },
        }
        out = app._normalize_patient_record_for_form(src)
        self.assertEqual("K52", out["primary_diagnosis_icd10"])
        self.assertEqual("E11", out["secondary_diagnoses_icd10"])
        self.assertEqual("legacy", out["free_diagnosis_text"])

    def test_normalize_patient_list_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_patient_list_item_for_tree(
            {
                "id": "12",
                "first_name": " Ana ",
                "last_name": " Pop ",
                "phone": None,
                "email": "  ",
            }
        )
        self.assertEqual(12, out["id"])
        self.assertEqual("Ana", out["first_name"])
        self.assertEqual("Pop", out["last_name"])
        self.assertEqual("", out["phone"])
        self.assertEqual("", out["email"])
        self.assertEqual("-", out["reception_flag"])

    def test_normalize_admission_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_admission_item_for_ui(
            {
                "id": "25",
                "mrn": " MRN-2026-000025 ",
                "department": " Ortopedie ",
                "status": " active ",
            }
        )
        self.assertEqual(25, out["id"])
        self.assertEqual("MRN-2026-000025", out["mrn"])
        self.assertEqual("Ortopedie", out["department"])
        self.assertEqual("active", out["status"])
        self.assertEqual("", out["ward"])
        self.assertEqual("", out["case_finalized_at"])

    def test_normalize_admission_transfer_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_admission_transfer_item_for_ui(
            {
                "id": "3",
                "admission_id": "9",
                "action_type": " transfer ",
                "to_department": " ATI ",
                "notes": None,
            }
        )
        self.assertEqual(3, out["id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual("transfer", out["action_type"])
        self.assertEqual("ATI", out["to_department"])
        self.assertEqual("", out["notes"])
        self.assertEqual("", out["from_department"])

    def test_normalize_institutional_report_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_institutional_report_item_for_ui(
            {
                "id": "21",
                "admission_id": "9",
                "patient_id": "5",
                "report_type": " SIUI ",
                "status": " submitted ",
                "transport_attempts": "2",
            }
        )
        self.assertEqual(21, out["id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual("SIUI", out["report_type"])
        self.assertEqual("submitted", out["status"])
        self.assertEqual(2, out["transport_attempts"])
        self.assertEqual("", out["validation_errors"])

    def test_normalize_billing_record_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_billing_record_item_for_ui(
            {
                "id": "7",
                "admission_id": "9",
                "patient_id": "5",
                "record_type": " partial ",
                "amount": "88.4",
                "currency": " ron ",
                "status": " issued ",
            }
        )
        self.assertEqual(7, out["id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual("partial", out["record_type"])
        self.assertAlmostEqual(88.4, float(out["amount"]), places=3)
        self.assertEqual("ron", out["currency"])
        self.assertEqual("issued", out["status"])
        self.assertEqual("", out["issued_at"])

    def test_normalize_case_invoice_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_case_invoice_item_for_ui(
            {
                "id": "11",
                "patient_id": "5",
                "admission_id": "9",
                "invoice_type": " proforma ",
                "subtotal": "100.0",
                "tax_amount": "19.0",
                "total_amount": "119.0",
                "currency": " RON ",
                "status": " issued ",
            }
        )
        self.assertEqual(11, out["id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual("proforma", out["invoice_type"])
        self.assertAlmostEqual(119.0, float(out["total_amount"]), places=3)
        self.assertEqual("RON", out["currency"])
        self.assertEqual("issued", out["status"])

    def test_normalize_invoice_payment_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_invoice_payment_item_for_ui(
            {
                "id": "77",
                "invoice_id": "11",
                "admission_id": "9",
                "patient_id": "5",
                "amount": "45.5",
                "payment_method": " cash ",
                "reference_no": " REF ",
            }
        )
        self.assertEqual(77, out["id"])
        self.assertEqual(11, out["invoice_id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual(5, out["patient_id"])
        self.assertAlmostEqual(45.5, float(out["amount"]), places=3)
        self.assertEqual("cash", out["payment_method"])
        self.assertEqual("REF", out["reference_no"])

    def test_normalize_offer_contract_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_offer_contract_item_for_ui(
            {
                "id": "91",
                "patient_id": "5",
                "admission_id": "9",
                "doc_type": " offer ",
                "base_price": "1000",
                "discount_amount": "50",
                "final_price": "950",
                "status": " draft ",
            }
        )
        self.assertEqual(91, out["id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual("offer", out["doc_type"])
        self.assertAlmostEqual(950.0, float(out["final_price"]), places=3)
        self.assertEqual("draft", out["status"])

    def test_normalize_medical_leave_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_medical_leave_item_for_ui(
            {
                "id": "12",
                "patient_id": "5",
                "admission_id": "9",
                "series": " CM ",
                "leave_number": " 1001 ",
                "days_count": "4",
                "status": " issued ",
            }
        )
        self.assertEqual(12, out["id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual("CM", out["series"])
        self.assertEqual("1001", out["leave_number"])
        self.assertEqual(4, out["days_count"])
        self.assertEqual("issued", out["status"])

    def test_normalize_case_consumption_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_case_consumption_item_for_ui(
            {
                "id": "22",
                "patient_id": "5",
                "admission_id": "9",
                "item_type": " material ",
                "item_name": " Bandaj ",
                "quantity": "2",
                "unit_price": "10",
                "total_price": "20",
                "source": " ward_stock ",
                "status": " recorded ",
            }
        )
        self.assertEqual(22, out["id"])
        self.assertEqual(5, out["patient_id"])
        self.assertEqual(9, out["admission_id"])
        self.assertEqual("material", out["item_type"])
        self.assertEqual("Bandaj", out["item_name"])
        self.assertAlmostEqual(20.0, float(out["total_price"]), places=3)
        self.assertEqual("ward_stock", out["source"])
        self.assertEqual("recorded", out["status"])

    def test_normalize_order_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_order_item_for_ui(
            {
                "id": "33",
                "admission_id": "401",
                "order_type": " lab ",
                "priority": " urgent ",
                "order_text": " Test ",
                "status": " ordered ",
            }
        )
        self.assertEqual(33, out["id"])
        self.assertEqual(401, out["admission_id"])
        self.assertEqual("lab", out["order_type"])
        self.assertEqual("urgent", out["priority"])
        self.assertEqual(" Test ", out["order_text"])
        self.assertEqual("ordered", out["status"])

    def test_normalize_vital_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_vital_item_for_ui(
            {
                "id": "44",
                "admission_id": "401",
                "recorded_at": " 2026-03-06 12:00:00 ",
                "temperature_c": " 37.2 ",
                "systolic_bp": " 120 ",
                "diastolic_bp": " 80 ",
                "pulse": " 82 ",
                "respiratory_rate": " 18 ",
                "spo2": " 98 ",
                "pain_score": " 2 ",
                "notes": " note ",
            }
        )
        self.assertEqual(44, out["id"])
        self.assertEqual(401, out["admission_id"])
        self.assertEqual("2026-03-06 12:00:00", out["recorded_at"])
        self.assertEqual("37.2", out["temperature_c"])
        self.assertEqual("120", out["systolic_bp"])
        self.assertEqual("80", out["diastolic_bp"])
        self.assertEqual("82", out["pulse"])
        self.assertEqual("18", out["respiratory_rate"])
        self.assertEqual("98", out["spo2"])
        self.assertEqual("2", out["pain_score"])
        self.assertEqual(" note ", out["notes"])

    def test_normalize_visit_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_visit_item_for_ui(
            {
                "id": "45",
                "visit_date": " 2026-03-06 ",
                "reason": " Control ",
                "diagnosis": " J20.9 ",
                "treatment": " Simptomatic ",
                "notes": " note ",
                "created_at": " 2026-03-06 12:10:00 ",
            }
        )
        self.assertEqual(45, out["id"])
        self.assertEqual("2026-03-06", out["visit_date"])
        self.assertEqual("Control", out["reason"])
        self.assertEqual("J20.9", out["diagnosis"])
        self.assertEqual("Simptomatic", out["treatment"])
        self.assertEqual(" note ", out["notes"])
        self.assertEqual("2026-03-06 12:10:00", out["created_at"])

    def test_normalize_medis_investigation_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_medis_investigation_item_for_ui(
            {
                "id": "46",
                "order_id": "33",
                "patient_id": "9",
                "admission_id": "401",
                "provider": " MEDIS ",
                "external_request_id": " REQ-123 ",
                "requested_at": " 2026-03-06 12:20:00 ",
                "request_payload": " {\"panel\":\"cbc\"} ",
                "status": " sent ",
                "result_summary": " summary ",
                "result_flag": " normal ",
                "external_result_id": " RES-1 ",
                "transport_state": " submitted_local ",
                "transport_attempts": "2",
                "transport_http_code": "201",
                "order_type": " lab ",
                "priority": " urgent ",
                "order_text": " Test ",
            }
        )
        self.assertEqual(46, out["id"])
        self.assertEqual(33, out["order_id"])
        self.assertEqual(9, out["patient_id"])
        self.assertEqual(401, out["admission_id"])
        self.assertEqual("MEDIS", out["provider"])
        self.assertEqual("REQ-123", out["external_request_id"])
        self.assertEqual("2026-03-06 12:20:00", out["requested_at"])
        self.assertEqual(" {\"panel\":\"cbc\"} ", out["request_payload"])
        self.assertEqual("sent", out["status"])
        self.assertEqual(" summary ", out["result_summary"])
        self.assertEqual("normal", out["result_flag"])
        self.assertEqual("RES-1", out["external_result_id"])
        self.assertEqual("submitted_local", out["transport_state"])
        self.assertEqual(2, out["transport_attempts"])
        self.assertEqual(201, out["transport_http_code"])
        self.assertEqual("lab", out["order_type"])
        self.assertEqual("urgent", out["priority"])
        self.assertEqual(" Test ", out["order_text"])

    def test_normalize_timeline_event_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_timeline_event_item_for_ui(
            {
                "event_id": " snapshot:10 ",
                "patient_id": "9",
                "admission_id": "401",
                "event_type": " patient_snapshot ",
                "category": " snapshot ",
                "occurred_at": " 2026-03-06 12:00:00 ",
                "actor_user_id": "1",
                "actor_name": " admin ",
                "title": " Snapshot v10 ",
                "summary": " text ",
                "payload_json": " {\"k\":\"v\"} ",
            }
        )
        self.assertEqual("snapshot:10", out["event_id"])
        self.assertEqual(9, out["patient_id"])
        self.assertEqual(401, out["admission_id"])
        self.assertEqual("patient_snapshot", out["event_type"])
        self.assertEqual("snapshot", out["category"])
        self.assertEqual("2026-03-06 12:00:00", out["occurred_at"])
        self.assertEqual(1, out["actor_user_id"])
        self.assertEqual("admin", out["actor_name"])
        self.assertEqual("Snapshot v10", out["title"])
        self.assertEqual(" text ", out["summary"])

    def test_normalize_snapshot_item_defaults(self) -> None:
        out = PacientiAIApp._normalize_snapshot_item_for_ui(
            {
                "id": "10",
                "patient_id": "9",
                "version_no": "2",
                "trigger_action": " update_patient ",
                "trigger_source": " save_patient ",
                "trigger_ref_id": " patient_id:9 ",
                "snapshot_json": "{\"first_name\":\"Ana\"}",
                "changed_fields_json": "[\"first_name\",\"phone\"]",
                "snapshot_hash": " abc ",
                "created_at": " 2026-03-06 12:00:00 ",
                "created_by_user_id": "1",
                "created_by_username": " admin ",
            }
        )
        self.assertEqual(10, out["id"])
        self.assertEqual(9, out["patient_id"])
        self.assertEqual(2, out["version_no"])
        self.assertEqual("update_patient", out["trigger_action"])
        self.assertEqual("save_patient", out["trigger_source"])
        self.assertEqual("patient_id:9", out["trigger_ref_id"])
        self.assertEqual("abc", out["snapshot_hash"])
        self.assertEqual("2026-03-06 12:00:00", out["created_at"])
        self.assertEqual(1, out["created_by_user_id"])
        self.assertEqual("admin", out["created_by_username"])
        self.assertEqual(["first_name", "phone"], out["changed_fields"])

    def test_pretty_json_text(self) -> None:
        pretty = PacientiAIApp._pretty_json_text("{\"b\":2,\"a\":1}")
        self.assertIn("\n", pretty)
        self.assertIn("\"a\": 1", pretty)
        self.assertIn("\"b\": 2", pretty)
        raw = "not-json"
        self.assertEqual(raw, PacientiAIApp._pretty_json_text(raw))

    def test_extract_admission_id_from_timeline_row(self) -> None:
        self.assertEqual(401, PacientiAIApp._extract_admission_id_from_timeline_row({"admission_id": "401"}))
        self.assertEqual(0, PacientiAIApp._extract_admission_id_from_timeline_row({"admission_id": "0"}))
        self.assertEqual(0, PacientiAIApp._extract_admission_id_from_timeline_row({"admission_id": "abc"}))
        self.assertEqual(0, PacientiAIApp._extract_admission_id_from_timeline_row({}))
        self.assertEqual(0, PacientiAIApp._extract_admission_id_from_timeline_row(None))  # type: ignore[arg-type]

    def test_timeline_context_menu_flags(self) -> None:
        row = {
            "event_id": "snapshot:1",
            "admission_id": "401",
            "payload_json": "{\"a\":1}",
            "summary": "text",
        }
        flags = PacientiAIApp._timeline_context_menu_flags(row)
        self.assertTrue(flags["has_row"])
        self.assertTrue(flags["has_admission"])
        self.assertTrue(flags["has_event_id"])
        self.assertTrue(flags["has_payload"])
        self.assertTrue(flags["has_summary"])

        flags_empty = PacientiAIApp._timeline_context_menu_flags({})
        self.assertFalse(flags_empty["has_row"])
        self.assertFalse(flags_empty["has_admission"])
        self.assertFalse(flags_empty["has_event_id"])
        self.assertFalse(flags_empty["has_payload"])
        self.assertFalse(flags_empty["has_summary"])

    def test_snapshot_context_menu_flags(self) -> None:
        row = {
            "id": "15",
            "snapshot_hash": "abc123",
            "snapshot_json": "{\"x\":1}",
        }
        flags = PacientiAIApp._snapshot_context_menu_flags(row)
        self.assertTrue(flags["has_row"])
        self.assertTrue(flags["has_snapshot_id"])
        self.assertTrue(flags["has_hash"])
        self.assertTrue(flags["has_snapshot_json"])
        self.assertTrue(flags["has_diff_json"])

        flags_empty = PacientiAIApp._snapshot_context_menu_flags({})
        self.assertFalse(flags_empty["has_row"])
        self.assertFalse(flags_empty["has_snapshot_id"])
        self.assertFalse(flags_empty["has_hash"])
        self.assertFalse(flags_empty["has_snapshot_json"])
        self.assertFalse(flags_empty["has_diff_json"])

    def test_timeline_context_menu_state_mapping(self) -> None:
        mapping = PacientiAIApp._timeline_context_menu_state_mapping()
        self.assertEqual(
            [
                (0, "has_admission"),
                (2, "has_event_id"),
                (3, "has_payload"),
                (4, "has_admission"),
                (5, "has_summary"),
            ],
            mapping,
        )

    def test_snapshot_context_menu_state_mapping(self) -> None:
        mapping = PacientiAIApp._snapshot_context_menu_state_mapping()
        self.assertEqual(
            [
                (0, "has_snapshot_id"),
                (1, "has_hash"),
                (2, "has_snapshot_json"),
                (3, "has_diff_json"),
            ],
            mapping,
        )


if __name__ == "__main__":
    unittest.main()
