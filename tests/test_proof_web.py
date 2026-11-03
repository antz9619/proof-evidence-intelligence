"""HTTP local real y motor real; casos sintéticos, sin oráculos, claves ni Meta."""

from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import proof_baseline
import proof_meta_experiment as experiment
import proof_web as web


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.history = patch.object(web, "HISTORY_PATH", None)
        self.history.start()
        self.addCleanup(self.history.stop)

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, path, body=body, headers=headers or ({"Content-Type": "application/json"} if body else {}))
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def evaluate(self, key):
        status, _, body = self.request("POST", "/api/evaluate", {"case_id": key})
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_catalog_previews_do_not_execute_baseline_or_fabricate_results(self):
        with patch.object(experiment, "evaluate", side_effect=AssertionError("No calcular en preview")) as engine:
            status, _, body = self.request("GET", "/api/cases")
        self.assertEqual(status, 200)
        engine.assert_not_called()
        catalog = json.loads(body)
        self.assertEqual([c["id"] for c in catalog["cases"]], ["A", "B", "C"])
        self.assertFalse(catalog["live_inference_enabled"])
        for case in catalog["cases"]:
            self.assertTrue(case["input"]["synthetic"])
            self.assertNotIn("evaluation", case)
            self.assertNotIn("reasoning", case["extraction"])

    def test_case_a_http_really_calls_baseline_once_with_validated_facts(self):
        with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
            response = self.evaluate("A")
        engine.assert_called_once()
        scenario = engine.call_args.args[0]
        self.assertEqual(scenario["shipment"]["expected_packages"], 10)
        self.assertEqual(response["quantities"], {"expected": 10, "documented": 8, "difference": 2})
        self.assertEqual(response["evaluation"]["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertTrue(response["execution"]["baseline_executed"])
        self.assertEqual(response["outcome"], "review")
        self.assertEqual(response["origin"]["kind"], "OFFLINE")
        self.assertEqual(response["demo"]["input"]["shipment"], scenario["shipment"])
        self.assertEqual(response["demo"]["extraction"]["documents"][1]["received_packages"]["value"], 8)

    def test_case_b_blocks_before_baseline_and_never_displays_calculated_quantity(self):
        with patch.object(experiment, "evaluate", side_effect=AssertionError("No motor con estado inválido")) as engine:
            response = self.evaluate("B")
        engine.assert_not_called()
        self.assertIsNone(response["quantities"])
        self.assertFalse(response["execution"]["baseline_executed"])
        self.assertEqual(response["evaluation"]["engine_status"], "NOT_RUN")
        self.assertEqual(response["reason"]["field"], "status")
        self.assertEqual(response["reason"]["value"], "ENTREGA_COMPLETA")
        self.assertEqual(response["reason"]["quote"], "ENTREGADO")
        self.assertEqual(response["outcome"], "rejected")
        self.assertIn("Reproducción sintética", response["origin"]["detail"])

    def test_case_c_preserves_unknowns_and_requests_review(self):
        response = self.evaluate("C")
        operation = response["evaluation"]["operational_result"]
        self.assertIsNone(response["quantities"]["documented"])
        self.assertIsNone(response["quantities"]["difference"])
        self.assertIn("QUANTITY_UNKNOWN", operation["uncertainties"])
        self.assertIn("REQUEST_ADDITIONAL_EVIDENCE", operation["proposed_actions"])
        self.assertEqual(operation["documentary_conformity"], "UNKNOWN")
        self.assertEqual(response["outcome"], "incomplete")

    def test_all_operational_paths_forbid_oracles_network_client_and_secret_reads(self):
        original_read = Path.read_text

        def no_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("No leer oráculos")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", no_oracle), patch.object(
                experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("No Meta HTTP")), patch(
                "os.environ.get", side_effect=AssertionError("No leer entorno ni claves")):
            for key in web.CASES:
                response = self.evaluate(key)
                self.assertFalse(response["live_inference_enabled"])
                self.assertEqual(response["META_MODEL_EVALUATION"], "NOT_RUN_THIS_MISSION")
                self.assertFalse(response["evaluation"]["operational_result"]["automatic_closure_allowed"])
                self.assertFalse(response["evaluation"]["operational_result"]["physical_delivery_verified"])

    def test_static_routes_are_allowlisted_and_private_files_are_not_served(self):
        for path in web.ASSETS:
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for path in ("/artifacts/proof-meta-01/hybrid-live-01/response.json", "/.env", "/AGENTS.md", "/../MEMORY.md", "/api/live", "/experiments/proof_meta_01/expected.json"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_arbitrary_payloads_and_cross_origin_or_host_requests_are_rejected(self):
        for payload in ({"case_id": "unknown"}, {"case_id": []}, {"case_id": "A", "mode": "live"}, {"case_id": "../.env"}):
            self.assertEqual(self.request("POST", "/api/evaluate", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/evaluate", {"case_id": "A"}, {"Content-Type": "application/json", "Origin": "https://external.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Host": "external.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/api/live", {"case_id": "A"})[0], 404)

    def test_repeated_clicks_execute_again_instead_of_returning_cached_decisions(self):
        with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
            first, second = self.evaluate("A"), self.evaluate("A")
        self.assertEqual(engine.call_count, 2)
        self.assertNotEqual(first["execution"]["id"], second["execution"]["id"])

    def test_safe_history_projects_only_known_synthetic_extraction_and_keeps_record_intact(self):
        demo = web.load_demo("B")
        extraction = deepcopy(demo["extraction"])
        raw = json.dumps({"model": "SYNTHETIC_TEST_MODEL", "private_metadata": "NEVER_EXPOSE",
                          "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(extraction)}}]}).encode()
        directory = web.ROOT / "artifacts"
        directory.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            path = Path(temporary) / "response.json"
            path.write_bytes(raw)
            with patch.object(web, "HISTORY_PATH", path), patch.object(web, "HISTORY_SHA256", hashlib.sha256(raw).hexdigest()):
                projected = web.load_demo("B")
                self.assertEqual(projected["origin"]["kind"], "HISTORICAL")
                self.assertEqual(projected["extraction"], extraction)
                self.assertNotIn("NEVER_EXPOSE", json.dumps(projected))
                self.assertEqual(path.read_bytes(), raw)
            with patch.object(web, "HISTORY_PATH", path):
                self.assertEqual(web.load_demo("B")["origin"]["kind"], "OFFLINE")

    def test_unknown_server_error_returns_no_fake_decision_or_private_error_text(self):
        with patch.object(web, "evaluate_demo", side_effect=RuntimeError("PRIVATE_TEST_DETAIL")):
            status, _, body = self.request("POST", "/api/evaluate", {"case_id": "A"})
        self.assertEqual(status, 500)
        self.assertNotIn(b"PRIVATE_TEST_DETAIL", body)
        self.assertNotIn(b"quantities", body)


if __name__ == "__main__":
    unittest.main()
