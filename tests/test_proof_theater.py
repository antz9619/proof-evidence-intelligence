"""Real loopback HTTP, public projections and real baseline; never Meta or oracles."""

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
import proof_theater as theater
import proof_web as web


class TheaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = [web.make_server(0), web.make_server(0, mode="render", allowed_hosts={"theater-test.example"})]
        cls.threads = []
        for server in cls.servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers:
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=3)

    def request(self, server, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        configured = {"Host": "theater-test.example"} if server.proof_mode == "render" else {}
        configured.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            configured.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=configured)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def evaluate(self, server, case_id):
        status, body = self.request(server, "POST", "/api/theater/evaluate", {"case_id": case_id})
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_four_previews_never_calculate_and_origins_are_unambiguous(self):
        with patch.object(experiment, "evaluate", side_effect=AssertionError("No motor en preview")) as engine:
            for server in self.servers:
                status, body = self.request(server, "GET", "/api/theater/cases")
                self.assertEqual(status, 200)
                cases = json.loads(body)["cases"]
                self.assertEqual(tuple(case["id"] for case in cases), theater.CASE_IDS)
                for index, record in enumerate(cases):
                    self.assertNotIn("decision", record)
                    self.assertIs(record["input"]["synthetic"], True)
                    self.assertEqual(record["origin"]["kind"], "HISTORICAL_META" if index < 3 else "SYNTHETIC_ANNOTATION")
                    self.assertNotIn("reasoning", record["extraction"])
        engine.assert_not_called()

    def test_recorded_wrong_status_is_never_corrected_and_blocks_engine(self):
        for server in self.servers:
            with patch.object(experiment, "evaluate", side_effect=AssertionError("No motor")) as engine:
                result = self.evaluate(server, "PM01-03")
            engine.assert_not_called()
            self.assertEqual(result["record"]["extraction"]["documents"][0]["status"]["value"], "ENTREGA_COMPLETA")
            self.assertIsNone(result["decision"]["quantities"])
            self.assertEqual(result["decision"]["baseline_status"], "NOT_RUN")
            self.assertEqual(result["decision"]["reason"]["code"], "UNSUPPORTED_STATUS")
            self.assertIn("ENTREGADO", result["decision"]["reason"]["quote"])
            self.assertEqual(next(c for c in result["checks"] if c["id"] == "status_guard")["status"], "FAIL")
            self.assertTrue(all(not row["used_by_engine"] for row in result["lineage"]))

    def test_omitted_document_blocks_before_status_guard_and_does_not_fill_fields(self):
        for server in self.servers:
            with patch.object(experiment, "evaluate", side_effect=AssertionError("No motor")) as engine, patch.object(
                    experiment, "_check_carrier_declaration", side_effect=AssertionError("Guard no alcanzado")) as guard:
                result = self.evaluate(server, "PM01-05")
            engine.assert_not_called()
            guard.assert_not_called()
            self.assertEqual([d["source_id"] for d in result["record"]["extraction"]["documents"]], ["tracking"])
            self.assertEqual(result["decision"]["reason"]["missing_sources"], ["pod"])
            self.assertEqual(next(c for c in result["checks"] if c["id"] == "status_guard")["status"], "NOT_RUN")
            self.assertIsNone(result["decision"]["quantities"])

    def test_complete_historical_extraction_really_calls_baseline_once(self):
        for server in self.servers:
            with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
                result = self.evaluate(server, "PM01-02")
            engine.assert_called_once()
            self.assertEqual(result["decision"]["quantities"], {"expected": 6, "documented": 6, "difference": 0})
            self.assertEqual(result["decision"]["operational_result"]["documentary_conformity"], "CONFIRMED")
            self.assertIsNone(result["record"]["extraction"]["documents"][0]["delivery_complete"]["value"])
            self.assertEqual(result["decision"]["outcome"], "confirmed")

    def test_foreign_receipt_is_visible_but_excluded_from_baseline_and_quantity(self):
        for server in self.servers:
            with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
                result = self.evaluate(server, "PM01-07")
            engine.assert_called_once()
            sources = engine.call_args.args[0]["sources"]
            self.assertEqual([source["id"] for source in sources], ["tracking"])
            self.assertEqual(result["decision"]["quantities"], {"expected": 10, "documented": None, "difference": None})
            self.assertEqual(result["decision"]["operational_result"]["documentary_conformity"], "UNKNOWN")
            self.assertIn({"source_id": "pod", "reason": "FOREIGN_DOCUMENT"}, result["decision"]["excluded_sources"])
            self.assertEqual(result["record"]["extraction"]["documents"][1]["received_packages"]["value"], 10)
            for row in result["lineage"]:
                if row["source_id"] == "pod":
                    self.assertEqual(row["validation"], "EXCLUDED")
                    self.assertFalse(row["used_by_engine"])

    def test_no_operational_request_reads_private_history_oracle_environment_or_meta(self):
        original_read, original_bytes = Path.read_text, Path.read_bytes

        def safe(path, *args, **kwargs):
            if "artifacts" in path.parts or path.name == "expected.json":
                raise AssertionError("Lecture privée interdite")
            return original_read(path, *args, **kwargs)

        def safe_bytes(path, *args, **kwargs):
            if "artifacts" in path.parts or path.name == "expected.json":
                raise AssertionError("No historia privada")
            return original_bytes(path, *args, **kwargs)

        with patch.object(Path, "read_text", safe), patch.object(Path, "read_bytes", safe_bytes), patch.object(
                experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch.object(
                web.os.environ, "get", side_effect=AssertionError("No entorno")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("No HTTP Meta")), patch.object(
                web, "safe_historical_extraction", side_effect=AssertionError("No historia privada")):
            for server in self.servers:
                for case_id in theater.CASE_IDS:
                    result = self.evaluate(server, case_id)
                    self.assertFalse(result["live_inference_enabled"])
                    self.assertFalse(result["decision"]["operational_result"]["automatic_closure_allowed"])
                    self.assertFalse(result["decision"]["operational_result"]["physical_delivery_verified"])

    def test_passport_is_complete_safe_and_has_reproducible_decision_identifier(self):
        server = self.servers[0]
        with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
            first, second = self.evaluate(server, "PM01-02"), self.evaluate(server, "PM01-02")
        self.assertEqual(engine.call_count, 2)
        self.assertNotEqual(first["execution"]["id"], second["execution"]["id"])
        self.assertEqual(first["passport"]["decision_id"], second["passport"]["decision_id"])
        for case_id in theater.CASE_IDS:
            result = self.evaluate(server, case_id)
            passport = result["passport"]
            self.assertEqual(passport["sources"], result["record"]["input"]["documents"])
            self.assertEqual(passport["extraction"], result["record"]["extraction"])
            self.assertEqual(passport["decision"], result["decision"])
            self.assertEqual(passport["reproducibility"]["extraction_sha256"], theater.digest(passport["extraction"]))
            self.assertFalse(passport["new_meta_inference"])
            text = json.dumps(passport)
            for forbidden in ("prompt_tokens", "completion_tokens", "usage", "cost", "billing", "response_id", "artifacts/", "META_MODEL_API_KEY", "Authorization"):
                self.assertNotIn(forbidden, text)

    def test_each_lineage_quote_belongs_to_its_original_source(self):
        for case_id in theater.CASE_IDS:
            result = self.evaluate(self.servers[0], case_id)
            sources = {s["source_id"]: s for s in result["record"]["input"]["documents"]}
            for row in result["lineage"]:
                if row["quote"]:
                    self.assertIn(row["quote"], sources[row["source_id"]]["text"])
            self.assertEqual(result["passport"]["reproducibility"]["decision_sha256"], theater.digest(result["decision"]))

    def test_modified_public_projection_is_rejected_without_fake_decision(self):
        folder = web.ROOT / "artifacts"
        folder.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path = Path(temporary) / "tampered.json"
            path.write_bytes(theater.DATA.read_bytes().replace(b'ENTREGA_COMPLETA', b'ENTREGADO', 1))
            with patch.object(theater, "DATA", path), patch.object(experiment, "evaluate") as engine:
                status, raw = self.request(self.servers[0], "POST", "/api/theater/evaluate", {"case_id": "PM01-03"})
                self.assertEqual(status, 500)
                self.assertNotIn(b"passport", raw)
                engine.assert_not_called()

    def test_public_routes_keep_host_origin_and_strict_payload_controls(self):
        server = self.servers[1]
        for payload in ({"case_id": "A"}, {"case_id": []}, {"case_id": "PM01-02", "extraction": {}}, {"case_id": "PM01-02", "mode": "live"}, {"case_id": "../.env"}):
            self.assertEqual(self.request(server, "POST", "/api/theater/evaluate", payload)[0], 400)
        self.assertEqual(self.request(server, "POST", "/api/theater/evaluate", {"case_id": "PM01-02"}, {"Origin": "http://theater-test.example"})[0], 403)
        self.assertEqual(self.request(server, "GET", "/api/theater/cases", headers={"Host": "evil.example", "X-Forwarded-Host": "theater-test.example"})[0], 403)
        for path in ("/demo/decision_theater.json", "/artifacts/private-inference.json", "/proof_theater.py", "/api/theater/live"):
            self.assertEqual(self.request(server, "GET", path)[0], 404)

    def test_human_choice_is_not_an_operational_input_or_permission(self):
        for server in self.servers:
            for case_id in ("PM01-07", "PM01-02"):
                for verdict in ("yes", "no"):
                    status, _ = self.request(server, "POST", "/api/theater/evaluate",
                                             {"case_id": case_id, "human_verdict": verdict})
                    self.assertEqual(status, 400)
                with patch.object(experiment, "evaluate", wraps=proof_baseline.evaluate) as engine:
                    first = self.evaluate(server, case_id)
                    second = self.evaluate(server, case_id)
                self.assertEqual(engine.call_count, 2)
                self.assertEqual(first["decision"], second["decision"])
                self.assertEqual(first["passport"]["decision_id"], second["passport"]["decision_id"])
                self.assertFalse(first["decision"]["operational_result"]["physical_delivery_verified"])
                self.assertFalse(first["decision"]["operational_result"]["automatic_closure_allowed"])

    def test_new_and_classic_pages_are_distinct_and_assets_are_self_hosted(self):
        server = self.servers[0]
        self.assertIn(b'id="case-tabs"', self.request(server, "GET", "/")[1])
        self.assertIn(b"Lo informado.", self.request(server, "GET", "/classic")[1])
        for path in ("/theater.css", "/theater.js", "/app.css", "/app.js"):
            self.assertEqual(self.request(server, "GET", path)[0], 200)


if __name__ == "__main__":
    unittest.main()
