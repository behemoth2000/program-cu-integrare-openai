import tempfile
import unittest
from pathlib import Path

from pacienti_ai_independent.pacienti_ai_app import (
    _canonical_street_type,
    _compose_address_details_from_parts,
    _compose_structured_address,
    _flatten_ro_address_options,
    _load_ro_localities_catalog,
    _parse_address_details_to_parts,
    _parse_structured_address,
    _street_type_matches,
    _validate_structured_address_correlation,
)


class PatientAddressDropdownTests(unittest.TestCase):
    def test_load_catalog_from_csv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "localities.csv"
            csv_path.write_text(
                "county,locality\n"
                "Alba,Alba Iulia\n"
                "Alba,Aiud\n"
                "Cluj,Cluj-Napoca\n"
                "Alba,Aiud\n",
                encoding="utf-8",
            )
            catalog = _load_ro_localities_catalog(csv_path)
            self.assertIn("Alba", catalog)
            self.assertEqual(["Aiud", "Alba Iulia"], catalog["Alba"])
            self.assertEqual(["Cluj-Napoca"], catalog["Cluj"])

    def test_compose_structured_address(self) -> None:
        full = _compose_structured_address("Cluj", "Cluj-Napoca", "Str. Memorandumului 12")
        self.assertEqual("Cluj-Napoca, jud. Cluj, Str. Memorandumului 12", full)
        county_only = _compose_structured_address("Cluj", "", "")
        self.assertEqual("jud. Cluj", county_only)

    def test_parse_structured_address(self) -> None:
        parsed = _parse_structured_address("Cluj-Napoca, jud. Cluj, Str. Memorandumului 12")
        self.assertEqual("Cluj", parsed["county"])
        self.assertEqual("Cluj-Napoca", parsed["locality"])
        self.assertEqual("Str. Memorandumului 12", parsed["details"])

    def test_parse_cnp_autofill_address(self) -> None:
        parsed = _parse_structured_address("Judet (din CNP): Cluj (cod 12)")
        self.assertEqual("Cluj", parsed["county"])
        self.assertEqual("", parsed["locality"])
        self.assertEqual("", parsed["details"])

    def test_flatten_address_options(self) -> None:
        options = _flatten_ro_address_options(
            {
                "Cluj": ["Cluj-Napoca", "Turda"],
                "Alba": ["Alba Iulia"],
            }
        )
        self.assertIn("Cluj-Napoca, jud. Cluj", options)
        self.assertIn("Alba Iulia, jud. Alba", options)

    def test_compose_address_details_from_parts(self) -> None:
        details = _compose_address_details_from_parts(
            street_type="Str.",
            street_name="Memorandumului",
            number="12",
            block="A3",
            stair="2",
            floor="4",
            apartment="18",
            intercom="34",
            extra="langa parc",
        )
        self.assertEqual(
            "Str. Memorandumului, nr. 12, bl. A3, sc. 2, et. 4, ap. 18, interfon 34, langa parc",
            details,
        )

    def test_parse_address_details_to_parts(self) -> None:
        parsed = _parse_address_details_to_parts(
            "Str. Memorandumului, nr. 12, bl. A3, sc. 2, et. 4, ap. 18, interfon 34, langa parc"
        )
        self.assertEqual("Str.", parsed["street_type"])
        self.assertEqual("Memorandumului", parsed["street_name"])
        self.assertEqual("12", parsed["number"])
        self.assertEqual("A3", parsed["block"])
        self.assertEqual("2", parsed["stair"])
        self.assertEqual("4", parsed["floor"])
        self.assertEqual("18", parsed["apartment"])
        self.assertEqual("34", parsed["intercom"])
        self.assertEqual("langa parc", parsed["extra"])

    def test_validate_structured_address_correlation_ok(self) -> None:
        err = _validate_structured_address_correlation(
            address="Cluj-Napoca, jud. Cluj, Str. Memorandumului, nr. 12",
            localities_by_county={"Cluj": ["Cluj-Napoca"]},
            streets_by_name={"memorandumului": "Str."},
        )
        self.assertIsNone(err)

    def test_validate_structured_address_correlation_wrong_locality(self) -> None:
        err = _validate_structured_address_correlation(
            address="Turda, jud. Cluj, Str. Memorandumului",
            localities_by_county={"Cluj": ["Cluj-Napoca"]},
            streets_by_name={},
        )
        self.assertIsNotNone(err)
        self.assertIn("localitatea", str(err).lower())

    def test_validate_structured_address_correlation_wrong_street(self) -> None:
        err = _validate_structured_address_correlation(
            address="Cluj-Napoca, jud. Cluj, Str. Inexistenta",
            localities_by_county={"Cluj": ["Cluj-Napoca"]},
            streets_by_name={"memorandumului": "Str."},
        )
        self.assertIsNotNone(err)
        self.assertIn("strada", str(err).lower())

    def test_canonical_street_type_normalizes_common_labels(self) -> None:
        self.assertEqual("Str.", _canonical_street_type("strada"))
        self.assertEqual("B-dul", _canonical_street_type("Bulevard"))
        self.assertEqual("Sos.", _canonical_street_type("sosea"))
        self.assertEqual("Intr.", _canonical_street_type("intrare"))

    def test_street_type_matches_uses_canonicalization(self) -> None:
        self.assertTrue(_street_type_matches("Str.", "strada"))
        self.assertTrue(_street_type_matches("B-dul", "bulevard"))
        self.assertFalse(_street_type_matches("Str.", "bulevard"))


if __name__ == "__main__":
    unittest.main()
