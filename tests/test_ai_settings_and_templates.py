import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pacienti_ai_independent.pacienti_ai_app import AIService, Database, PacientiAIApp


class AISettingsAndTemplatesTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PACIENTI_SEED_PASS_ADMIN"] = "Admin!234"
        self.db_path = Path(tempfile.gettempdir()) / f"pacienti_ai_ai_settings_{uuid4().hex}.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db = None
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass

    def test_app_settings_roundtrip_for_ai_keys(self) -> None:
        payload = {
            "AI_ENABLED": "1",
            "OPENAI_MODEL": "gpt-5",
            "AI_TEMPERATURE": "0.3",
            "AI_MAX_OUTPUT_TOKENS": "1200",
            "AI_TIMEOUT_SECONDS": "60",
            "AI_ALLOWED_ROLES": "admin,medic",
            "AI_TEMPLATE_SUMMARY": "Template summary text",
        }
        self.db.set_settings(payload)

        loaded = self.db.get_settings(list(payload.keys()))
        for key, value in payload.items():
            self.assertEqual(loaded.get(key), value)

    def test_parse_structured_json_from_plain_and_markdown_blocks(self) -> None:
        plain = (
            '{"situatie":"S", "risc":"R", "recomandare":"Rec", '
            '"monitorizare":"M", "informatii_lipsa":"I", "disclaimer":"D"}'
        )
        parsed_plain = AIService._parse_structured_json(plain)
        self.assertIsNotNone(parsed_plain)
        self.assertEqual(parsed_plain["situatie"], "S")
        self.assertEqual(parsed_plain["recomandare"], "Rec")

        markdown = "```json\n" + plain + "\n```"
        parsed_md = AIService._parse_structured_json(markdown)
        self.assertIsNotNone(parsed_md)
        self.assertEqual(parsed_md["monitorizare"], "M")

    def test_fallback_and_safety_include_disclaimer(self) -> None:
        structured = AIService._fallback_structured("text brut")
        formatted = PacientiAIApp._format_ai_structured_reply(structured)
        safe = PacientiAIApp._safety_finalize_ai_text(formatted)

        self.assertIn("Situatie:", safe)
        self.assertIn("Recomandare:", safe)
        self.assertIn("Acest output este informativ", safe)


if __name__ == "__main__":
    unittest.main()
