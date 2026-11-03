"""Pruebas locales con respuestas simuladas; no prueban un modelo de Meta."""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import proof_meta_experiment as experiment


class ProofMetaExperimentTests(unittest.TestCase):
    def setUp(self):
        self.cases = experiment.load_cases()
        self.truth = experiment.load_oracles()
        self.case = deepcopy(self.cases[2])
        self.oracle = deepcopy(self.truth[2])
        self.response = deepcopy(self.oracle["expected_response"])

    def test_eight_cases_and_separate_balanced_oracles(self):
        self.assertEqual(len(self.cases), 8)
        self.assertEqual(len(self.truth), 8)
        self.assertEqual(Counter(t["category"] for t in self.truth),
                         {"complete": 2, "partial": 2, "ambiguous": 2, "foreign_document": 2})
        self.assertEqual({c["case_id"] for c in self.cases}, {t["case_id"] for t in self.truth})
        self.assertEqual(len({c["shipment"]["id"] for c in self.cases}), 8)
        for case in self.cases:
            self.assertTrue(case["synthetic"])
            self.assertEqual(set(case), {"case_id", "synthetic", "as_of", "shipment", "documents"})
            self.assertEqual(len(case["documents"]), 2)

    def test_legacy_fixture_integrity_explicitly_scoped_to_original_three(self):
        root = Path(__file__).resolve().parents[1] / "scenarios"
        initial = {}
        for scenario_id in ("RESCUE-01", "PROOF-01", "STOCK-01"):
            data = json.loads((root / (scenario_id + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(data["id"], scenario_id)
            self.assertIs(data["synthetic"], True)
            cutoff = datetime.fromisoformat(data["as_of"])
            self.assertIsNotNone(cutoff.tzinfo)
            self.assertEqual(len({s["id"] for s in data["sources"]}), len(data["sources"]))
            for source in data["sources"]:
                for obs in source.get("observations", []):
                    at = datetime.fromisoformat(obs["at"])
                    self.assertIsNotNone(at.tzinfo)
                    self.assertLessEqual(at, cutoff)
            initial[scenario_id] = data
        rescue = initial["RESCUE-01"]
        self.assertEqual((datetime.fromisoformat(rescue["shipment"]["sla_deadline"]) - datetime.fromisoformat(rescue["as_of"])).total_seconds(), 4500)
        proof = initial["PROOF-01"]
        pod = next(s for s in proof["sources"] if s["id"] == "pod")["observations"][0]
        self.assertEqual(proof["shipment"]["expected_packages"], pod["expected_packages"])
        self.assertEqual(pod["expected_packages"] - pod["received_packages"], 2)
        stock = initial["STOCK-01"]
        lots = next(s for s in stock["sources"] if s["id"] == "wms")["lots"]
        free = {lot["lot"]: lot["on_hand"] - lot["reserved"] for lot in lots}
        self.assertEqual(free, {"A": 70, "B": 15})
        self.assertEqual(sum(free.values()), stock["deterministic_expectation"]["total_free"])
        self.assertEqual(stock["order"]["requested_units"] - sum(free.values()), stock["deterministic_expectation"]["shortage_units"])

    def test_all_frozen_simulations_match_independent_operational_expectations(self):
        for case, truth in zip(self.cases, self.truth):
            with self.subTest(case=case["case_id"]):
                response = deepcopy(truth["expected_response"])
                result = experiment.score(case, response, truth)
                self.assertIsNone(result["validation_error"])
                self.assertTrue(result["extraction"]["exact"])
                self.assertTrue(result["operational_exact"])
                self.assertTrue(result["validation"]["model_proposals_consistent"])
                self.assertTrue(result["validation"]["semantic_review_required"])
                self.assertFalse(result["validation"]["external_actions_executed"])

    def test_request_excludes_answers_and_does_not_load_oracles(self):
        self.case.update(category="private-category", expected_response=self.response,
                         uncertainty_conditions=["private-condition"])
        with patch.object(experiment, "load_oracles", side_effect=AssertionError("Oráculo leído")):
            request = experiment.build_request(self.case)
        payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(set(payload), {"case"})
        self.assertEqual(payload["case"], self.cases[2])
        self.assertNotIn("private-", json.dumps(request))

    def test_reasoning_track_provides_extraction_but_not_expected_decisions(self):
        docs = self.response["documents"]
        docs[0]["private_label"] = "not-for-model"
        docs[0]["status"]["private_label"] = "nested-private"
        request = experiment.build_request(self.case, verified_extraction=docs)
        payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(set(payload), {"case", "verified_extraction"})
        self.assertNotIn("not-for-model", json.dumps(payload))
        self.assertNotIn("nested-private", json.dumps(payload))
        self.assertNotIn("reasoning", payload)
        self.assertEqual(set(payload["verified_extraction"][0]), {"source_id", *experiment.FIELDS})

    def test_json_schema_is_opt_in_and_model_is_fixed(self):
        plain = experiment.build_request(self.case)
        native = experiment.build_request(self.case, json_schema=True)
        self.assertNotIn("response_format", plain)
        self.assertEqual(native["response_format"]["json_schema"]["schema"], experiment.transport_response_schema())
        self.assertTrue(native["response_format"]["json_schema"]["strict"])
        self.assertEqual(plain["model"], "muse-spark-1.3")
        self.assertEqual(plain["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", plain)
        self.assertEqual(plain["reasoning_effort"], "minimal")
        self.assertEqual(plain, experiment.build_request(self.case))

    def test_missing_received_quantity_remains_null_not_zero_or_expected(self):
        result = experiment.convert(self.cases[4], self.truth[4]["expected_response"])
        obs = result["baseline_input"]["sources"][1]["observations"][0]
        self.assertIsNone(obs["received_packages"])
        self.assertIsNone(obs["signature_identity_verified"])
        self.assertIsNone(result["baseline_result"]["assessment"]["quantity_difference"])

    def test_foreign_document_excluded_without_losing_its_extraction_record(self):
        for index, source in ((6, "pod"), (7, "tracking")):
            with self.subTest(case=index):
                result = experiment.convert(self.cases[index], self.truth[index]["expected_response"])
                self.assertEqual(result["excluded_sources"], [{"source_id": source, "reason": "FOREIGN_DOCUMENT"}])
                self.assertNotIn(source, {s["id"] for s in result["baseline_input"]["sources"]})

    def test_foreign_document_cannot_be_reassigned_to_target(self):
        response = deepcopy(self.truth[6]["expected_response"])
        response["documents"][1]["shipment_id"]["value"] = self.cases[6]["shipment"]["id"]
        with self.assertRaises(ValueError):
            experiment.convert(self.cases[6], response)

    def test_unknown_shipment_id_does_not_default_to_target(self):
        self.response["documents"][1]["shipment_id"] = {"value": None, "quote": None}
        result = experiment.convert(self.case, self.response)
        self.assertEqual(result["excluded_sources"][0]["reason"], "SHIPMENT_ID_UNKNOWN")
        self.assertIsNone(result["baseline_result"]["assessment"]["quantity_difference"])

    def test_unknown_requires_null_quote(self):
        self.response["documents"][0]["received_packages"]["quote"] = "ENTREGADO"
        with self.assertRaises(ValueError):
            experiment.convert(self.case, self.response)

    def test_nonnull_requires_real_quote_from_correct_source(self):
        for quote in (None, "texto inventado", "Estado informado: ENTREGADO"):
            with self.subTest(quote=quote):
                self.response["documents"][1]["received_packages"]["quote"] = quote
                with self.assertRaises(ValueError):
                    experiment.convert(self.case, self.response)

    def test_quantity_absent_from_quote_is_rejected(self):
        self.response["documents"][1]["received_packages"]["value"] = 7
        with self.assertRaises(ValueError):
            experiment.convert(self.case, self.response)

    def test_unknown_marker_cannot_be_converted_to_false(self):
        response = deepcopy(self.truth[4]["expected_response"])
        response["documents"][1]["signature_identity_verified"] = {
            "value": False, "quote": "No consta verificación de identidad"}
        result = experiment.score(self.cases[4], response, self.truth[4])
        self.assertIsNotNone(result["validation_error"])
        self.assertFalse(result["extraction"]["exact"])
        self.assertLess(result["extraction"]["unknown_preserved"], result["extraction"]["unknown_total"])

    def test_citation_existence_does_not_prove_semantics_and_oracle_catches_it(self):
        # La cita contiene diez, pero dice ESPERADOS: un chequeo léxico no distingue el significado.
        self.response["documents"][1]["received_packages"] = {"value": 10, "quote": "Esperados: diez bultos"}
        result = experiment.score(self.case, self.response, self.oracle)
        self.assertIsNone(result["validation_error"])
        self.assertFalse(result["extraction"]["exact"])
        self.assertTrue(result["validation"]["semantic_review_required"])
        self.assertFalse(result["validation"]["model_proposals_consistent"])

    def test_invalid_counts_and_bool_instead_of_int_are_rejected(self):
        for value in (-1, True, 8.0, "ocho"):
            with self.subTest(value=value):
                self.response["documents"][1]["received_packages"]["value"] = value
                with self.assertRaises(ValueError):
                    experiment.convert(self.case, self.response)

    def test_unknown_duplicate_and_missing_sources_are_rejected(self):
        for mode in ("unknown", "duplicate", "missing"):
            response = deepcopy(self.response)
            if mode == "unknown":
                response["documents"][1]["source_id"] = "invented"
            elif mode == "duplicate":
                response["documents"][1]["source_id"] = "tracking"
            else:
                response["documents"].pop()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                experiment.convert(self.case, response)

    def test_wrong_case_and_wrong_authority_field_are_rejected(self):
        wrong = deepcopy(self.response)
        wrong["case_id"] = "OTHER"
        with self.assertRaises(ValueError):
            experiment.convert(self.case, wrong)
        self.response["documents"][0]["received_packages"] = {"value": 10, "quote": "ENTREGADO"}
        with self.assertRaises(ValueError):
            experiment.convert(self.case, self.response)

    def test_prohibited_actions_physical_claims_and_extra_fields_are_rejected(self):
        for field, value in (("automatic_closure_allowed", True), ("physical_delivery_verified", True),
                             ("proposed_actions", ["CLOSE_SHIPMENT"]), ("invented", True)):
            with self.subTest(field=field):
                response = deepcopy(self.response)
                response["reasoning"][field] = value
                with self.assertRaises(ValueError):
                    experiment.convert(self.case, response)

    def test_operational_arithmetic_mismatch_blocks_model_proposals(self):
        self.response["reasoning"]["quantity_difference"] = 0
        result = experiment.validate_response(self.case, self.response)
        self.assertFalse(result["model_proposals_consistent"])
        self.assertEqual(result["model_actions_for_review"], [])
        self.assertEqual(result["deterministic_reasoning"]["quantity_difference"], 2)

    def test_allowed_vocabulary_action_still_requires_operational_preconditions(self):
        self.response["reasoning"]["proposed_actions"] = ["REVIEW_DOCUMENTARY_CLOSURE"]
        result = experiment.validate_response(self.case, self.response)
        self.assertFalse(result["model_proposals_consistent"])
        self.assertEqual(result["model_actions_for_review"], [])

    def test_metrics_separate_extraction_and_isolated_reasoning(self):
        extract = experiment.score(self.case, self.response, self.oracle)
        reason = experiment.score(self.case, self.response, self.oracle, "reasoning")
        self.assertIsNone(extract["isolated_reasoning_exact"])
        self.assertTrue(reason["isolated_reasoning_exact"])
        self.response["reasoning"]["quantity_difference"] = 0
        wrong = experiment.score(self.case, self.response, self.oracle, "reasoning")
        self.assertTrue(wrong["extraction"]["exact"])
        self.assertFalse(wrong["operational_exact"])
        self.assertFalse(wrong["isolated_reasoning_exact"])

    def test_future_naive_and_nonsynthetic_input_is_rejected(self):
        for field, value in (("at", "2026-10-26T16:00:00-03:00"), ("at", "2026-10-26T14:13:00"), ("synthetic", False)):
            with self.subTest(value=value):
                case = deepcopy(self.case)
                if field == "at":
                    case["documents"][0][field] = value
                else:
                    case[field] = value
                with self.assertRaises(ValueError):
                    experiment.convert(case, self.response)

    def test_chat_envelope_and_direct_json_produce_same_response(self):
        direct = json.dumps(self.response)
        envelope = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": direct}}]})
        self.assertEqual(experiment.parse_response(direct), experiment.parse_response(envelope))

    def test_truncated_refused_and_multiple_chat_choices_are_rejected(self):
        for choices in ([{"finish_reason": "length", "message": {"content": json.dumps(self.response)}}],
                        [{"finish_reason": "stop", "message": {"refusal": "refused", "content": "{}"}}], [], [{}, {}]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                experiment.parse_response(json.dumps({"choices": choices}))

    def test_duplicate_json_nan_and_markdown_wrappers_are_rejected(self):
        for text in ('{"case_id":"a","case_id":"b"}', '{"case_id":NaN}', '```json\n{}\n```'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                experiment.parse_response(text)

    def test_malformed_chat_envelope_is_rejected_without_guessing(self):
        for choice in (None, [], {"message": []}, {"message": {"content": []}, "finish_reason": "stop"}):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                experiment.parse_response(json.dumps({"choices": [choice]}))

    def test_wrong_extraction_is_not_counted_as_a_fully_correct_case(self):
        self.response["documents"][1]["received_packages"] = {"value": 10, "quote": "Esperados: diez bultos"}
        result = experiment.score(self.case, self.response, self.oracle, "reasoning")
        self.assertFalse(result["case_exact"])
        self.assertIsNone(result["isolated_reasoning_exact"])

    def test_inputs_and_responses_are_not_mutated(self):
        before = deepcopy((self.case, self.response))
        experiment.validate_response(self.case, self.response)
        self.assertEqual((self.case, self.response), before)

    def test_simulation_never_reports_meta_pass(self):
        result = experiment.simulate()
        self.assertEqual(result["simulated_cases_validated"], 8)
        self.assertEqual(result["response_origin"], "SIMULATED_FROM_FROZEN_ORACLE")
        self.assertEqual(result["META_MODEL_EVALUATION"], "NOT_RUN")
        self.assertEqual(result["END_TO_END_DEMO"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
