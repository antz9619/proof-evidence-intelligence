"""Render simulado por HTTP local: no crea servicios ni usa recursos externos."""

import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import proof_baseline
import proof_meta_experiment as experiment
import proof_web as web


HOST = "proof-test.example"


class RenderConfigurationTests(unittest.TestCase):
    def test_local_default_ignores_render_environment_and_keeps_local_port(self):
        with patch.object(web.os.environ, "get", side_effect=AssertionError("LOCAL no lee entorno Render")), patch.object(web, "make_server") as make:
            web.configured_server()
            make.assert_called_once_with(8765)
            make.reset_mock()
            web.configured_server(port=8123)
            make.assert_called_once_with(8123)

    def test_render_requires_explicit_mode_and_validated_port_hosts(self):
        with patch.object(web, "make_server") as make:
            web.configured_server(mode="render", environ={"PORT": "10000", "PROOF_ALLOWED_HOSTS": "PROOF-test.example, another.example"})
        make.assert_called_once_with(10000, mode="render", allowed_hosts=frozenset({HOST, "another.example"}))

    def test_invalid_or_missing_render_configuration_never_binds(self):
        base = {"PORT": "10000", "PROOF_ALLOWED_HOSTS": HOST}
        samples = [{}, {"PORT": "10000"}, {"PROOF_ALLOWED_HOSTS": HOST}]
        samples += [{**base, "PORT": value} for value in ("0", "-1", "65536", "10000.0", " 10000", "bad")]
        samples += [{**base, "PROOF_ALLOWED_HOSTS": value} for value in ("*", "*.onrender.com", "https://proof.example", "proof.example:443", "127.0.0.1", "localhost", "proof.example,", "user@proof.example", "a..example")]
        with patch.object(web, "make_server") as make:
            for config in samples:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    web.configured_server(mode="render", environ=config)
            make.assert_not_called()

    def test_meta_key_blocks_render_start_without_echoing_credential(self):
        fake = "SYNTHETIC_NOT_A_REAL_KEY"
        with patch.object(web, "make_server") as make, self.assertRaises(ValueError) as error:
            web.configured_server(mode="render", environ={"PORT": "10000", "PROOF_ALLOWED_HOSTS": HOST, "META_MODEL_API_KEY": fake})
        self.assertNotIn(fake, str(error.exception))
        make.assert_not_called()

    def test_render_cannot_override_port_or_fall_back_to_local(self):
        for kwargs in ({"mode": "Render"}, {"mode": "render", "port": 8765}):
            with self.subTest(kwargs=kwargs), patch.object(web, "make_server") as make, self.assertRaises(ValueError):
                web.configured_server(**kwargs, environ={"PORT": "10000", "PROOF_ALLOWED_HOSTS": HOST})
            make.assert_not_called()

    def test_bind_addresses_are_distinct_and_public_hosts_never_expand_local(self):
        with web.make_server(0) as local:
            self.assertEqual(local.server_address[0], "127.0.0.1")
            self.assertEqual(local.proof_mode, "local")
        with web.make_server(0, mode="render", allowed_hosts={HOST}) as public:
            self.assertEqual(public.server_address[0], "0.0.0.0")
            self.assertEqual(public.allowed_hosts, frozenset({HOST}))
        with self.assertRaises(ValueError):
            web.make_server(0, allowed_hosts={HOST})


class RenderHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.make_server(0, mode="render", allowed_hosts={HOST, "another.example"})
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        configured = {"Host": HOST, **(headers or {})}
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            configured.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=configured)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_authorized_hosts_https_origins_and_default_tls_port_are_accepted(self):
        for host, origin in ((HOST, "https://" + HOST), (HOST.upper() + ":443", "https://" + HOST + ":443"), ("another.example", "https://another.example")):
            with self.subTest(host=host):
                status, _, raw = self.request("GET", "/healthz", headers={"Host": host, "Origin": origin})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw), {"status": "ok", "mode": "render", "live_inference_enabled": False})

    def test_unauthorized_host_cannot_be_authorized_by_proxy_headers(self):
        for host in ("evil.example", HOST + ".evil.example", HOST + ":80", HOST + ".", "127.0.0.1", "localhost", "*"):
            with self.subTest(host=host):
                status, _, _ = self.request("GET", "/api/cases", headers={"Host": host, "X-Forwarded-Host": HOST, "X-Forwarded-Proto": "https", "Forwarded": f"host={HOST};proto=https"})
                self.assertEqual(status, 403)

    def test_http_null_foreign_or_cross_host_origins_are_rejected_even_with_proxy_headers(self):
        for origin in ("http://" + HOST, "null", "https://evil.example", "https://another.example", "https://" + HOST + "/", "https://" + HOST + ":8443"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("POST", "/api/evaluate", {"case_id": "A"}, {"Origin": origin, "X-Forwarded-Proto": "https"})[0], 403)
        self.assertEqual(self.request("GET", "/healthz", headers={"X-Forwarded-Host": "evil.example"})[0], 200)

    def test_render_never_reads_private_history_or_oracles_or_keys_or_meta_client(self):
        original_read = Path.read_text

        def no_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("No oráculo en operación")
            return original_read(path, *args, **kwargs)

        with patch.object(web, "safe_historical_extraction", side_effect=AssertionError("Render no lee historia privada")), patch.object(
                Path, "read_text", no_oracle), patch.object(experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch.object(
                web.os.environ, "get", side_effect=AssertionError("No leer entorno por request")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("No Meta HTTP")), patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
            status, _, raw = self.request("GET", "/api/cases")
            self.assertEqual(status, 200)
            self.assertEqual([c["id"] for c in json.loads(raw)["cases"]], ["A", "B", "C"])
            for key in ("A", "B", "C"):
                before = engine.call_count
                status, _, raw = self.request("POST", "/api/evaluate", {"case_id": key}, {"Origin": "https://" + HOST})
                self.assertEqual(status, 200)
                response = json.loads(raw)
                self.assertEqual(response["origin"]["kind"], "OFFLINE")
                self.assertFalse(response["live_inference_enabled"])
                self.assertEqual(response["execution"]["scope"], "PUBLIC_WEB_OFFLINE_NO_NEW_INFERENCE")
                self.assertFalse(response["evaluation"]["operational_result"]["automatic_closure_allowed"])
                if key == "B":
                    self.assertEqual(engine.call_count, before)
                    self.assertIsNone(response["quantities"])
                    self.assertIn("Reproducción sintética", response["origin"]["detail"])
                else:
                    self.assertEqual(engine.call_count, before + 1)
                    self.assertEqual(response["evaluation"]["operational_result"]["documentary_conformity"], "UNKNOWN")
                    self.assertEqual(response["quantities"]["difference"], 2 if key == "A" else None)

    def test_assets_private_routes_and_health_do_not_expose_internal_files(self):
        for path in web.ASSETS:
            status, headers, _ = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/artifacts/proof-meta-01/hybrid-live-01/response.json", "/.env", "/proof_web.py", "/experiments/proof_meta_01/expected.json", "/api/live", "/../MEMORY.md"):
            self.assertEqual(self.request("GET", path)[0], 404)
        status, _, body = self.request("HEAD", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_public_input_limits_and_schema_still_reject_invalid_payloads(self):
        for payload in ({"case_id": "A", "mode": "live"}, {"case_id": []}, {"case_id": "../.env"}, {"case_id": "x" * 5000}):
            self.assertEqual(self.request("POST", "/api/evaluate", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/live", {"case_id": "A"})[0], 404)

    def test_duplicate_host_and_origin_headers_are_not_selected_arbitrarily(self):
        for field in ("Host", "Origin"):
            with self.subTest(field=field):
                conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
                try:
                    conn.putrequest("GET", "/healthz", skip_host=True)
                    conn.putheader("Host", HOST)
                    if field == "Host":
                        conn.putheader("Host", "evil.example")
                    else:
                        conn.putheader("Origin", "https://" + HOST)
                        conn.putheader("Origin", "https://evil.example")
                    conn.endheaders()
                    response = conn.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
