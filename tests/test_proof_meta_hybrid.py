"""Flujo híbrido con datos sintéticos y transporte prohibido; no usa evidencia privada."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proof_hybrid as hybrid
import proof_meta_experiment as experiment


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.cases = experiment.load_cases()
        self.oracles = experiment.load_oracles()
        self.case, self.oracle = deepcopy(self.cases[2]), deepcopy(self.oracles[2])
        self.extraction = self.extract(self.oracle)

    @staticmethod
    def extract(oracle):
        response = oracle["expected_response"]
        return {"case_id": response["case_id"], "documents": deepcopy(response["documents"])}

    def assert_abstention(self, result):
        self.assertEqual(result["extraction_validation"], "FAIL")
        self.assertEqual(result["engine_status"], "NOT_RUN")
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIsNone(result["operational_result"]["quantity_difference"])
        self.assertFalse(result["operational_result"]["automatic_closure_allowed"])
        self.assertTrue(result["review_required"])
        self.assertIn("REQUEST_ADDITIONAL_EVIDENCE", result["operational_result"]["proposed_actions"])

    def test_contracts_are_separate_and_legacy_schema_unchanged_by_projection(self):
        original = experiment.response_schema()
        local = experiment.extraction_schema()
        self.assertEqual(set(local["properties"]), {"case_id", "documents"})
        self.assertEqual(local["properties"]["documents"], original["properties"]["documents"])
        self.assertEqual(experiment.response_schema(), original)
        self.assertIn("reasoning", experiment.response_schema()["properties"])
        self.assertEqual(experiment.parse_response(json.dumps(self.extraction), extraction_only=True), self.extraction)
        with self.assertRaises(ValueError):
            experiment.parse_response(json.dumps(self.extraction))
        with self.assertRaises(ValueError):
            experiment.parse_response(json.dumps(self.oracle["expected_response"]), extraction_only=True)

    def test_transport_is_closed_required_compatible_and_within_known_limits(self):
        def nodes(schema, depth=1):
            yield schema, depth
            for child in schema.get("properties", {}).values():
                yield from nodes(child, depth + 1)
            if "items" in schema:
                yield from nodes(schema["items"], depth + 1)

        sent = list(nodes(experiment.transport_extraction_schema()))
        self.assertLessEqual(max(depth for _, depth in sent), 10)
        self.assertLessEqual(sum(len(n.get("properties", {})) for n, _ in sent), 5000)
        self.assertLessEqual(sum(len(n.get("enum", [])) for n, _ in sent), 1000)
        for node, _ in sent:
            self.assertFalse(set(node) & {"uniqueItems", "minimum", "minLength", "const", "$schema"})
            self.assertTrue(set(node) <= {"type", "properties", "required", "additionalProperties", "items", "enum"})
            if node["type"] == "object":
                self.assertIs(node["additionalProperties"], False)
                self.assertEqual(set(node["required"]), set(node["properties"]))
        count = experiment.extraction_schema()["properties"]["documents"]["items"]["properties"]["received_packages"]
        self.assertEqual(count["properties"]["value"]["minimum"], 0)
        self.assertEqual(count["properties"]["quote"]["minLength"], 1)

    def test_request_has_schema_once_no_answers_and_no_oracle_or_http(self):
        self.case["expected_response"] = self.oracle["expected_response"]
        original_read = Path.read_text

        def no_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("No leer oráculos para preparar o ejecutar el flujo")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", no_oracle), patch.object(
                experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("No HTTP")):
            output = StringIO()
            with patch("sys.argv", ["proof_hybrid.py", "prepare", "PM01-03"]), redirect_stdout(output):
                hybrid.main()
            request = json.loads(output.getvalue())
            hybrid.run(self.case, self.extraction)
        self.assertEqual(request, hybrid.build_extraction_request(self.case))
        self.assertEqual(request["max_completion_tokens"], 4096)
        self.assertEqual(request["reasoning_effort"], "minimal")
        self.assertIs(request["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(request["response_format"]["json_schema"]["schema"], experiment.transport_extraction_schema())
        self.assertEqual(json.loads(request["messages"][1]["content"]), {"case": self.cases[2]})
        messages = json.dumps(request["messages"])
        self.assertNotIn('"properties"', messages)
        self.assertNotIn("expected_response", messages)
        self.assertNotIn("quantity_difference", json.dumps(request))
        self.assertNotIn("proposed_actions", json.dumps(request))

    def test_partial_case_uses_engine_for_difference_uncertainties_and_actions(self):
        result = hybrid.run(self.case, self.extraction)
        operational = result["operational_result"]
        self.assertEqual(result["engine_status"], "COMPUTED_BY_BASELINE")
        self.assertEqual(operational["quantity_difference"], 2)
        self.assertIn("QUANTITY_MISMATCH", operational["uncertainties"])
        self.assertNotIn("QUANTITY_UNKNOWN", operational["uncertainties"])
        self.assertEqual(operational["documentary_conformity"], "UNKNOWN")
        self.assertFalse(operational["automatic_closure_allowed"])
        self.assertFalse(operational["physical_delivery_verified"])
        self.assertIn("VERIFY_SIGNER_IDENTITY", operational["proposed_actions"])
        self.assertFalse(result["external_actions_executed"])
        self.assertTrue(result["semantic_review_required"])
        difference = result["baseline_result"]["discrepancies"][0]
        self.assertEqual(difference["source_ids"], ["pod"])
        self.assertIn("/shipment/expected_packages", difference["evidence_paths"])

    def test_legacy_failure_is_preserved_while_hybrid_reuses_only_its_facts(self):
        legacy = deepcopy(self.oracle["expected_response"])
        legacy["reasoning"]["quantity_difference"] = None
        legacy["reasoning"]["uncertainties"].remove("QUANTITY_MISMATCH")
        legacy["reasoning"]["uncertainties"].append("QUANTITY_UNKNOWN")
        before = deepcopy(legacy)
        text = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(legacy)}}]})
        replay = hybrid.replay(self.case, text, self.oracle)
        self.assertEqual(replay["historical_reasoning_result"], "FAIL")
        self.assertFalse(replay["historical_metrics"]["operational_exact"])
        self.assertTrue(replay["hybrid_metrics"]["offline_case_exact"])
        self.assertEqual(legacy, before)
        self.assertIsNone(legacy["reasoning"]["quantity_difference"])
        self.assertEqual(experiment.score(self.case, legacy, self.oracle), replay["historical_metrics"])

    def test_all_eight_frozen_extractions_produce_expected_operational_results(self):
        for case, oracle in zip(self.cases, self.oracles):
            with self.subTest(case=case["case_id"]):
                measured = hybrid.measure(case, self.extract(oracle), oracle)
                self.assertTrue(measured["extraction_accuracy"]["exact"])
                self.assertTrue(measured["engine_consistency"]["given_correct_extraction"])
                self.assertTrue(measured["offline_case_exact"])
                self.assertEqual(measured["result"]["META_MODEL_EVALUATION"], "NOT_RUN_HYBRID_CONTRACT")

    def test_complete_evidence_only_confirms_structured_documentary_conformity(self):
        result = hybrid.run(self.cases[0], self.extract(self.oracles[0]))
        self.assertEqual(result["operational_result"]["documentary_conformity"], "CONFIRMED")
        self.assertFalse(result["operational_result"]["automatic_closure_allowed"])
        self.assertFalse(result["operational_result"]["physical_delivery_verified"])
        self.assertTrue(result["review_required"])
        self.assertEqual(result["operational_result"]["proposed_actions"], ["REVIEW_DOCUMENTARY_CLOSURE"])

    def test_insufficient_evidence_preserves_nulls_and_requests_review(self):
        result = hybrid.run(self.cases[4], self.extract(self.oracles[4]))
        self.assertEqual(result["extraction_validation"], "PASS_LOCAL_CHECKS_ONLY")
        self.assertIsNone(result["operational_result"]["quantity_difference"])
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIn("QUANTITY_UNKNOWN", result["operational_result"]["uncertainties"])
        self.assertIn("REQUEST_ADDITIONAL_EVIDENCE", result["operational_result"]["proposed_actions"])
        self.assertTrue(result["review_required"])

    def test_foreign_or_unknown_shipment_is_excluded_not_reassigned(self):
        result = hybrid.run(self.cases[6], self.extract(self.oracles[6]))
        self.assertEqual(result["excluded_sources"], [{"source_id": "pod", "reason": "FOREIGN_DOCUMENT"}])
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.extraction["documents"][1]["shipment_id"] = {"value": None, "quote": None}
        result = hybrid.run(self.case, self.extraction)
        self.assertIn("SHIPMENT_ID_UNKNOWN", result["operational_result"]["uncertainties"])
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIsNone(result["operational_result"]["quantity_difference"])
        foreign = self.extract(self.oracles[6])
        foreign["documents"][1]["shipment_id"]["value"] = self.cases[6]["shipment"]["id"]
        self.assert_abstention(hybrid.run(self.cases[6], foreign))

    def test_invalid_quantities_types_and_empty_known_fields_abstain(self):
        for value in (-1, True, 8.0, "8"):
            with self.subTest(value=value):
                bad = deepcopy(self.extraction)
                bad["documents"][1]["received_packages"]["value"] = value
                self.assert_abstention(hybrid.run(self.case, bad))
        for field in ("quote", "value"):
            with self.subTest(field=field):
                bad = deepcopy(self.extraction)
                bad["documents"][1]["shipment_id"][field] = ""
                self.assert_abstention(hybrid.run(self.case, bad))

    def test_invented_omitted_duplicate_and_cross_source_evidence_abstains(self):
        bad_responses = []
        for change in ("invented_source", "omitted_source", "duplicate_source", "invented_quote", "wrong_authority", "null_with_quote", "wrong_case"):
            bad = deepcopy(self.extraction)
            if change == "invented_source":
                bad["documents"][1]["source_id"] = "invented"
            elif change == "omitted_source":
                bad["documents"].pop()
            elif change == "duplicate_source":
                bad["documents"].append(deepcopy(bad["documents"][1]))
            elif change == "invented_quote":
                bad["documents"][1]["received_packages"]["quote"] = "Recibidos: nueve"
            elif change == "wrong_authority":
                bad["documents"][1]["status"] = {"value": "ENTREGADO", "quote": "Envío"}
            elif change == "null_with_quote":
                bad["documents"][1]["status"]["quote"] = "Envío"
            else:
                bad["case_id"] = "PM01-99"
            bad_responses.append((change, bad))
        for change, bad in bad_responses:
            with self.subTest(change=change):
                self.assert_abstention(hybrid.run(self.case, bad))

    def test_uncertainty_cannot_be_replaced_with_an_invented_number(self):
        bad = self.extract(self.oracles[4])
        bad["documents"][1]["received_packages"] = {"value": 10, "quote": "ilegible"}
        self.assert_abstention(hybrid.run(self.cases[4], bad))

    def test_model_operational_assertions_are_rejected_not_used(self):
        for field, value in (("reasoning", self.oracle["expected_response"]["reasoning"]),
                             ("automatic_closure_allowed", True), ("physical_delivery_verified", True)):
            with self.subTest(field=field):
                bad = {**deepcopy(self.extraction), field: value}
                with patch.object(experiment, "evaluate", side_effect=AssertionError("No calcular sobre extracción inválida")):
                    self.assert_abstention(hybrid.run(self.case, bad))

    def test_dates_and_multiple_authorities_keep_existing_baseline_limits(self):
        bad_case = deepcopy(self.case)
        bad_case["documents"][1]["at"] = "2026-10-27T15:00:00-03:00"
        self.assert_abstention(hybrid.run(bad_case, self.extraction))
        bad_case = deepcopy(self.case)
        bad_case["documents"].append({**deepcopy(bad_case["documents"][1]), "source_id": "pod2"})
        bad = deepcopy(self.extraction)
        bad["documents"].append({**deepcopy(bad["documents"][1]), "source_id": "pod2"})
        self.assert_abstention(hybrid.run(bad_case, bad))

    def test_engine_handles_explicit_completeness_conflict(self):
        self.case["documents"][0]["text"] = "Envío: SYN-PM-103. Estado informado: ENTREGA_COMPLETA."
        self.extraction["documents"][0]["status"] = {"value": "ENTREGA_COMPLETA", "quote": "Estado informado: ENTREGA_COMPLETA"}
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["operational_result"]["quantity_difference"], 2)
        self.assertEqual(result["operational_result"]["documentary_conformity"], "CONTRADICTORY")
        self.assertIn("DOCUMENTARY_CONFLICT", result["operational_result"]["uncertainties"])

    def test_excess_is_a_negative_difference_not_a_negative_received_count(self):
        self.case["documents"][1]["text"] = self.case["documents"][1]["text"].replace("ocho", "doce")
        self.extraction["documents"][1]["received_packages"] = {"value": 12, "quote": "Recibidos: doce"}
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["operational_result"]["quantity_difference"], -2)
        self.assertIn("QUANTITY_MISMATCH", result["operational_result"]["uncertainties"])

    def test_accuracy_is_not_inferred_from_structural_validity_or_engine_execution(self):
        # Una omisión innecesaria puede ser JSON válido: es error de extracción, no del cálculo.
        self.extraction["documents"][1]["received_packages"] = {"value": None, "quote": None}
        measured = hybrid.measure(self.case, self.extraction, self.oracle)
        self.assertFalse(measured["extraction_accuracy"]["exact"])
        self.assertIsNone(measured["engine_consistency"]["given_correct_extraction"])
        self.assertFalse(measured["offline_case_exact"])
        self.assertEqual(measured["result"]["operational_result"]["documentary_conformity"], "UNKNOWN")

    def test_truncation_refusal_and_duplicate_json_keys_never_become_accepted_extraction(self):
        for choice in ({"finish_reason": "length", "message": {"content": json.dumps(self.extraction)}},
                       {"finish_reason": "stop", "message": {"content": json.dumps(self.extraction), "refusal": "synthetic"}}):
            with self.subTest(choice=choice["finish_reason"]), self.assertRaises(ValueError):
                experiment.parse_response(json.dumps({"choices": [choice]}), extraction_only=True)
        with self.assertRaises(ValueError):
            experiment.parse_response('{"case_id":"PM01-03","case_id":"PM01-03"}', extraction_only=True)

    def test_cli_invalid_json_returns_review_without_http(self):
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as directory:
            source = Path(directory) / "invalid.json"
            source.write_text('{"case_id":')
            output = StringIO()
            with patch("sys.argv", ["proof_hybrid.py", "evaluate", "PM01-03", str(source)]), patch(
                    "urllib.request.build_opener", side_effect=AssertionError("No HTTP")), redirect_stdout(output):
                hybrid.main()
            self.assert_abstention(json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
