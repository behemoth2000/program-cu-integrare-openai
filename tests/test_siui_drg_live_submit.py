import unittest

from pacienti_ai_independent.integrations.contracts import TransportResult
from pacienti_ai_independent.integrations.siui_drg_client import SiuiDrgClient


class SiuiDrgLiveSubmitTest(unittest.TestCase):
    def _build_client(self) -> SiuiDrgClient:
        return SiuiDrgClient(
            base_url="https://sandbox.example",
            endpoint_siui_submit="/siui/submit",
            endpoint_drg_submit="/drg/submit",
            auth_type="api_key",
            client_id="cid",
            client_secret="secret",
            api_key="api-key",
            bearer_token="",
            timeout_seconds=10,
            max_retries=0,
            retry_base_seconds=0.1,
        )

    def test_submit_siui_extracts_reference(self) -> None:
        client = self._build_client()

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual("https://sandbox.example/siui/submit", kwargs["url"])
            return TransportResult(
                ok=True,
                http_code=200,
                retriable=False,
                response_payload='{"external_reference":"SIUI-ACK-123"}',
                ack_payload='{"external_reference":"SIUI-ACK-123"}',
            )

        client.http.request_json = _fake_request_json  # type: ignore[assignment]
        res = client.submit_report("siui", {"foo": "bar"}, "idem-1")
        self.assertTrue(res.ok)
        self.assertEqual("SIUI-ACK-123", res.external_reference)

    def test_submit_drg_extracts_reference(self) -> None:
        client = self._build_client()

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual("https://sandbox.example/drg/submit", kwargs["url"])
            return TransportResult(
                ok=True,
                http_code=200,
                retriable=False,
                response_payload='{"reference_id":"DRG-ACK-987"}',
                ack_payload='{"reference_id":"DRG-ACK-987"}',
            )

        client.http.request_json = _fake_request_json  # type: ignore[assignment]
        res = client.submit_report("drg", {"foo": "bar"}, "idem-1b")
        self.assertTrue(res.ok)
        self.assertEqual("DRG-ACK-987", res.external_reference)

    def test_submit_drg_passes_failure(self) -> None:
        client = self._build_client()

        def _fake_request_json(**kwargs):  # type: ignore[no-untyped-def]
            self.assertEqual("https://sandbox.example/drg/submit", kwargs["url"])
            return TransportResult(
                ok=False,
                http_code=503,
                retriable=True,
                error="HTTP 503",
                response_payload='{"error":"down"}',
            )

        client.http.request_json = _fake_request_json  # type: ignore[assignment]
        res = client.submit_report("drg", {"foo": "bar"}, "idem-2")
        self.assertFalse(res.ok)
        self.assertTrue(res.retriable)
        self.assertEqual(503, res.http_code)

    def test_missing_endpoint_returns_local_error(self) -> None:
        client = SiuiDrgClient(
            base_url="",
            endpoint_siui_submit="",
            endpoint_drg_submit="",
            auth_type="none",
            client_id="",
            client_secret="",
            api_key="",
            bearer_token="",
            timeout_seconds=10,
            max_retries=0,
            retry_base_seconds=0.1,
        )
        res = client.submit_report("siui", {"a": 1}, "idem-3")
        self.assertFalse(res.ok)
        self.assertFalse(res.retriable)
        self.assertIn("Endpoint", res.error)


if __name__ == "__main__":
    unittest.main()
