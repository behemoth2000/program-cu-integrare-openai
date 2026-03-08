import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import Database, now_ts


class Manual1PartnersRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_manual1_partners_{uuid4().hex}.db"
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
                "first_name": "Mara",
                "last_name": "Partener",
                "cnp": "2860101223344",
                "phone": "",
                "email": "",
                "birth_date": "1986-01-01",
                "address": "",
                "medical_history": "",
                "allergies": "",
                "chronic_conditions": "",
                "current_medication": "",
                "gender": "F",
                "occupation": "",
                "insurance_provider": "CNAS",
                "insurance_id": "INS-M1",
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
                "bed": "4",
                "attending_clinician": "Dr Manual1",
                "chief_complaint": "durere",
                "admitted_at": now_ts(),
            },
            user_id=None,
        )
        return patient_id, admission_id

    def test_partner_crud_contacts_and_bank_accounts(self) -> None:
        partner_id = self.db.create_business_partner(
            {
                "code": "LAB001",
                "name": "Laborator Test SRL",
                "partner_type": "lab",
                "fiscal_code": "RO12345678",
                "reg_com": "J40/123/2020",
                "country": "RO",
                "city": "Bucuresti",
                "address": "Str. Test 1",
                "email": "office@lab.test",
                "phone": "0722000000",
                "active": True,
            }
        )
        self.assertGreater(partner_id, 0)

        rows = self.db.list_business_partners(search="Laborator", partner_type="lab", active_only=True)
        self.assertTrue(any(int(r["id"]) == int(partner_id) for r in rows))

        self.db.update_business_partner(
            partner_id,
            {
                "code": "LAB001",
                "name": "Laborator Test SRL Actualizat",
                "partner_type": "lab",
                "fiscal_code": "RO12345678",
                "reg_com": "J40/123/2020",
                "country": "RO",
                "city": "Ilfov",
                "address": "Str. Test 2",
                "email": "contact@lab.test",
                "phone": "0722999999",
                "active": True,
            },
        )
        updated = self.db.get_business_partner(partner_id)
        self.assertIsNotNone(updated)
        self.assertEqual("Ilfov", updated["city"])

        contact_id = self.db.add_business_partner_contact(
            partner_id=partner_id,
            name="Dr Contact",
            role="coordonator",
            email="doc@lab.test",
            phone="0733000000",
            is_primary=True,
        )
        self.assertGreater(contact_id, 0)
        contacts = self.db.list_business_partner_contacts(partner_id)
        self.assertEqual(1, len(contacts))
        self.assertEqual("Dr Contact", contacts[0]["name"])
        self.assertEqual(1, int(contacts[0]["is_primary"] or 0))

        bank_id = self.db.add_business_partner_bank_account(
            partner_id=partner_id,
            bank_name="Banca Test",
            iban="RO09BANK0000000000000001",
            currency="RON",
            is_default=True,
        )
        self.assertGreater(bank_id, 0)
        accounts = self.db.list_business_partner_bank_accounts(partner_id)
        self.assertEqual(1, len(accounts))
        self.assertEqual("RON", accounts[0]["currency"])
        self.assertEqual(1, int(accounts[0]["is_default"] or 0))

    def test_partner_selection_works_in_invoice_and_consumption(self) -> None:
        _patient_id, admission_id = self._create_patient_and_admission()
        partner_id = self.db.create_business_partner(
            {
                "code": "SUP001",
                "name": "Furnizor Consumabile",
                "partner_type": "supplier",
                "fiscal_code": "RO99990000",
                "city": "Bucuresti",
                "active": True,
            }
        )
        cost_center_id = self.db.create_cost_center(code="CC-ORTHO", name="Ortopedie", active=True)

        consumption_id = self.db.add_case_consumption(
            admission_id=admission_id,
            item_type="material",
            item_name="Pansament",
            unit="buc",
            quantity=2,
            unit_price=25,
            source="ward_stock",
            notes="Consum test",
            recorded_at=now_ts(),
            partner_id=partner_id,
            cost_center_id=cost_center_id,
            user_id=None,
        )
        self.assertGreater(consumption_id, 0)

        invoice_id = self.db.create_case_invoice(
            admission_id=admission_id,
            invoice_type="proforma",
            series="PRF",
            invoice_number=f"{datetime.now().strftime('%H%M%S')}",
            subtotal=100,
            tax_amount=19,
            total_amount=None,
            issued_at=now_ts(),
            due_date=datetime.now().strftime("%Y-%m-%d"),
            status="issued",
            notes="Factura cu partener",
            partner_id=partner_id,
            cost_center_id=cost_center_id,
            user_id=None,
        )
        self.assertGreater(invoice_id, 0)

        consumptions = self.db.list_case_consumptions(admission_id)
        consum_row = next((r for r in consumptions if int(r["id"]) == int(consumption_id)), None)
        self.assertIsNotNone(consum_row)
        self.assertEqual(int(partner_id), int(consum_row["partner_id"] or 0))
        self.assertEqual(int(cost_center_id), int(consum_row["cost_center_id"] or 0))

        invoices = self.db.list_case_invoices(admission_id)
        inv_row = next((r for r in invoices if int(r["id"]) == int(invoice_id)), None)
        self.assertIsNotNone(inv_row)
        self.assertEqual(int(partner_id), int(inv_row["partner_id"] or 0))
        self.assertEqual(int(cost_center_id), int(inv_row["cost_center_id"] or 0))


if __name__ == "__main__":
    unittest.main()

