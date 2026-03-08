import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import (
    Database,
    _parse_json_street_rows,
    _parse_xml_street_rows,
    _split_osm_street_name_type,
)


class StreetCatalogSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_streets_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_parse_json_rows_with_default_location(self) -> None:
        payload = '[{"denumire":"Memorandumului","categorie":"strada"}]'
        rows = _parse_json_street_rows(
            payload_text=payload,
            default_county="Cluj",
            default_locality="Cluj-Napoca",
            source_name="test",
            source_url="http://example.test/streets.json",
            locality_to_county={"Cluj-Napoca": "Cluj"},
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Cluj", rows[0]["county"])
        self.assertEqual("Cluj-Napoca", rows[0]["locality"])
        self.assertEqual("Memorandumului", rows[0]["street_name"])
        self.assertEqual("strada", rows[0]["street_type"])

    def test_parse_xml_rows_with_bucharest_sector(self) -> None:
        payload = """<?xml version="1.0" encoding="UTF-8"?>
<NomenclatorArtereBucuresti>
  <Artere>
    <Categorie>bulevard</Categorie>
    <Denumire>1 Decembrie 1918</Denumire>
    <Sector>3</Sector>
  </Artere>
</NomenclatorArtereBucuresti>
"""
        rows = _parse_xml_street_rows(
            payload_text=payload,
            default_county="",
            default_locality="",
            source_name="test",
            source_url="http://example.test/streets.xml",
            locality_to_county={},
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Bucuresti", rows[0]["county"])
        self.assertEqual("Bucuresti Sector 3", rows[0]["locality"])
        self.assertEqual("1 Decembrie 1918", rows[0]["street_name"])
        self.assertEqual("bulevard", rows[0]["street_type"])

    def test_replace_and_query_street_catalog(self) -> None:
        inserted = self.db.replace_street_catalog(
            [
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "strada",
                    "street_name": "Memorandumului",
                    "source_name": "test",
                    "source_url": "http://example.test/1",
                },
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "bulevard",
                    "street_name": "Eroilor",
                    "source_name": "test",
                    "source_url": "http://example.test/2",
                },
            ]
        )
        self.assertEqual(2, inserted)
        rows = self.db.list_street_catalog_entries(county="Cluj", locality="Cluj-Napoca", query="memo")
        self.assertEqual(1, len(rows))
        self.assertEqual("Memorandumului", rows[0]["street_name"])

    def test_replace_street_catalog_does_not_clear_on_empty_payload(self) -> None:
        inserted = self.db.replace_street_catalog(
            [
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "strada",
                    "street_name": "Memorandumului",
                    "source_name": "test",
                    "source_url": "http://example.test/1",
                }
            ]
        )
        self.assertEqual(1, inserted)
        inserted_empty = self.db.replace_street_catalog([])
        self.assertEqual(0, inserted_empty)
        rows = self.db.list_street_catalog_entries(county="Cluj", locality="Cluj-Napoca")
        self.assertEqual(1, len(rows))
        self.assertEqual("Memorandumului", rows[0]["street_name"])

    def test_list_entries_flexible_locality_matching_for_bucharest(self) -> None:
        inserted = self.db.replace_street_catalog(
            [
                {
                    "county": "Bucuresti",
                    "locality": "Bucuresti Sector 1+2",
                    "street_type": "strada",
                    "street_name": "Exemplu",
                    "source_name": "test",
                    "source_url": "http://example.test/1",
                }
            ]
        )
        self.assertEqual(1, inserted)
        rows = self.db.list_street_catalog_entries(county="Bucuresti", locality="Bucuresti")
        self.assertEqual(1, len(rows))
        self.assertEqual("Exemplu", rows[0]["street_name"])

    def test_list_localities_returns_catalog_values_for_county(self) -> None:
        inserted = self.db.replace_street_catalog(
            [
                {
                    "county": "Bucuresti",
                    "locality": "Bucuresti Sector 3",
                    "street_type": "strada",
                    "street_name": "Nerva Traian",
                    "source_name": "test",
                    "source_url": "http://example.test/1",
                },
                {
                    "county": "Bucuresti",
                    "locality": "Bucuresti Sector 1",
                    "street_type": "strada",
                    "street_name": "Paris",
                    "source_name": "test",
                    "source_url": "http://example.test/2",
                },
            ]
        )
        self.assertEqual(2, inserted)
        localities = self.db.list_street_catalog_localities(county="Bucuresti")
        self.assertIn("Bucuresti Sector 1", localities)
        self.assertIn("Bucuresti Sector 3", localities)

    def test_merge_street_catalog_entries_upserts_without_delete(self) -> None:
        inserted = self.db.replace_street_catalog(
            [
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "strada",
                    "street_name": "Memorandumului",
                    "source_name": "seed",
                    "source_url": "http://example.test/seed",
                }
            ]
        )
        self.assertEqual(1, inserted)
        merged = self.db.merge_street_catalog_entries(
            [
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "Str.",
                    "street_name": "Memorandumului",
                    "source_name": "osm",
                    "source_url": "http://example.test/osm",
                },
                {
                    "county": "Cluj",
                    "locality": "Cluj-Napoca",
                    "street_type": "Str.",
                    "street_name": "Eroilor",
                    "source_name": "osm",
                    "source_url": "http://example.test/osm",
                },
            ]
        )
        self.assertEqual(2, merged)
        rows = self.db.list_street_catalog_entries(county="Cluj", locality="Cluj-Napoca", limit=50)
        names = {str(row["street_name"]) for row in rows}
        self.assertIn("Memorandumului", names)
        self.assertIn("Eroilor", names)

    def test_split_osm_street_name_type(self) -> None:
        st_type, st_name = _split_osm_street_name_type("Strada Unirii")
        self.assertEqual("Str.", st_type)
        self.assertEqual("Unirii", st_name)
        st_type2, st_name2 = _split_osm_street_name_type("Calea Bucuresti")
        self.assertEqual("Calea", st_type2)
        self.assertEqual("Bucuresti", st_name2)


if __name__ == "__main__":
    unittest.main()
