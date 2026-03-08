import unittest
from datetime import date

from pacienti_ai_independent.pacienti_ai_app import (
    _apply_cnp_autofill_to_payload,
    _cnp_control_digit,
    _derive_cnp_data,
)


class CnpDerivationTests(unittest.TestCase):
    @staticmethod
    def _make_cnp(s: int, yy: int, mm: int, dd: int, county: int, nnn: int) -> str:
        first12 = f"{s}{yy:02d}{mm:02d}{dd:02d}{county:02d}{nnn:03d}"
        return first12 + str(_cnp_control_digit(first12))

    def test_valid_cnp_derives_birth_date_and_gender(self) -> None:
        cnp = self._make_cnp(1, 80, 1, 15, 40, 123)
        derived = _derive_cnp_data(cnp, today=date(2026, 3, 5))
        self.assertTrue(derived["valid"])
        self.assertEqual("1980-01-15", derived["birth_date"])
        self.assertEqual("M", derived["gender"])
        self.assertEqual("40", derived["county_code"])
        self.assertEqual("Bucuresti", derived["county_label"])
        self.assertEqual(46, derived["age_years"])
        self.assertTrue(derived["checksum_valid"])

    def test_invalid_checksum_rejected(self) -> None:
        cnp = self._make_cnp(2, 86, 7, 12, 23, 222)
        wrong_last_digit = (int(cnp[-1]) + 1) % 10
        invalid = cnp[:12] + str(wrong_last_digit)
        derived = _derive_cnp_data(invalid, today=date(2026, 3, 5))
        self.assertFalse(derived["valid"])
        self.assertIn("control", derived["error"].lower())

    def test_invalid_calendar_date_rejected(self) -> None:
        first12 = "180133150001"
        cnp = first12 + str(_cnp_control_digit(first12))
        derived = _derive_cnp_data(cnp, today=date(2026, 3, 5))
        self.assertFalse(derived["valid"])
        self.assertIn("data nasterii", derived["error"].lower())

    def test_unknown_county_code_is_allowed_with_unknown_label(self) -> None:
        cnp = self._make_cnp(5, 5, 6, 20, 50, 321)
        derived = _derive_cnp_data(cnp, today=date(2026, 3, 5))
        self.assertTrue(derived["valid"])
        self.assertEqual("50", derived["county_code"])
        self.assertEqual("Necunoscut", derived["county_label"])

    def test_policy_only_fill_empty_fields(self) -> None:
        cnp = self._make_cnp(1, 90, 8, 10, 12, 111)
        payload = {
            "cnp": cnp,
            "birth_date": "1970-01-01",
            "gender": "F",
            "address": "Adresa manuala",
        }
        _apply_cnp_autofill_to_payload(payload)
        self.assertEqual("1970-01-01", payload["birth_date"])
        self.assertEqual("F", payload["gender"])
        self.assertEqual("Adresa manuala", payload["address"])

    def test_address_autofill_only_when_empty(self) -> None:
        cnp = self._make_cnp(2, 85, 11, 21, 23, 512)
        payload = {
            "cnp": cnp,
            "birth_date": "",
            "gender": "",
            "address": "",
        }
        _apply_cnp_autofill_to_payload(payload)
        self.assertEqual("1985-11-21", payload["birth_date"])
        self.assertEqual("F", payload["gender"])
        self.assertIn("Judet (din CNP):", payload["address"])
        self.assertIn("Ilfov", payload["address"])

    def test_s9_does_not_autofill_gender(self) -> None:
        cnp = self._make_cnp(9, 0, 1, 1, 40, 123)
        payload = {
            "cnp": cnp,
            "birth_date": "",
            "gender": "",
            "address": "",
        }
        _apply_cnp_autofill_to_payload(payload)
        self.assertEqual("2000-01-01", payload["birth_date"])
        self.assertEqual("", payload["gender"])
        self.assertIn("Bucuresti", payload["address"])


if __name__ == "__main__":
    unittest.main()
