import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class Manual1DocumentNumberingTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual1_docnum_{uuid4().hex}.db"
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
                "first_name": "Nicu",
                "last_name": "Numerotare",
                "cnp": "1800101223344",
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
                "bed": "8",
                "attending_clinician": "Dr Numerotare",
                "chief_complaint": "test",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def test_allocate_sequence(self) -> None:
        self.db.save_document_numbering_rule(
            document_type="case_invoice",
            location="",
            series="INV",
            prefix="",
            suffix="",
            next_number=1,
            pad_length=4,
            reset_policy="yearly",
            active=True,
        )
        n1 = self.db.allocate_document_number("case_invoice", "", "admission", 1, None)
        n2 = self.db.allocate_document_number("case_invoice", "", "admission", 2, None)
        n3 = self.db.allocate_document_number("case_invoice", "", "admission", 3, None)
        self.assertEqual("0001", n1["number"])
        self.assertEqual("0002", n2["number"])
        self.assertEqual("0003", n3["number"])
        self.assertEqual("INV0001", n1["full_number"])

    def test_allocate_concurrent_without_duplicates(self) -> None:
        self.db.save_document_numbering_rule(
            document_type="medical_leave",
            location="",
            series="CM",
            next_number=1,
            pad_length=5,
            reset_policy="yearly",
            active=True,
        )
        results: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def worker(entity_id: int) -> None:
            try:
                allocated = self.db.allocate_document_number("medical_leave", "", "medical_leave", entity_id, None)
                with lock:
                    results.append(str(allocated["number"]))
            except Exception as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(idx + 1,)) for idx in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual([], errors)
        self.assertEqual(16, len(results))
        self.assertEqual(16, len(set(results)))

    def test_yearly_reset_uses_new_year_sequence(self) -> None:
        self.db.save_document_numbering_rule(
            document_type="medical_leave",
            location="",
            series="CM",
            next_number=30,
            pad_length=4,
            reset_policy="yearly",
            active=True,
        )
        with self.db._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_numbering_audit (
                    document_type, location, series, allocated_number, allocated_at,
                    allocated_by, entity_type, entity_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("medical_leave", "", "CM", 29, "2025-12-31 23:59:59", None, "manual", 1),
            )
            conn.commit()

        allocated = self.db.allocate_document_number("medical_leave", "", "medical_leave", 2, None)
        self.assertEqual("0001", allocated["number"])

    def test_invoice_auto_numbering_when_enabled(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        self.db.set_setting("DOCNUM_ENABLE_AUTO", "1")
        self.db.save_document_numbering_rule(
            document_type="case_invoice",
            location="",
            series="FCT",
            next_number=11,
            pad_length=5,
            reset_policy="yearly",
            active=True,
        )
        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="",
            invoice_number="",
            subtotal=200,
            tax_amount=38,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="auto numbering",
            user_id=None,
        )
        invoices = self.db.list_case_invoices(admission_id)
        row = next((r for r in invoices if int(r["id"]) == int(invoice_id)), None)
        self.assertIsNotNone(row)
        self.assertEqual("FCT", row["series"])
        self.assertEqual("00011", row["invoice_number"])


if __name__ == "__main__":
    unittest.main()

