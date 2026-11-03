"""Casos sintéticos en memoria: no se amplía scenarios/ ni se llama a servicios."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from proof_baseline import evaluate


FIXTURE = Path(__file__).resolve().parents[1] / "scenarios" / "PROOF-01.json"


class ProofBaselineTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.tracking = self.scenario["sources"][0]["observations"][0]
        self.pod = self.scenario["sources"][1]["observations"][0]

    def codes(self, result, field):
        return {item["code"] for item in result[field]}

    def test_original_partial_document_keeps_closure_pending(self):
        result = evaluate(self.scenario)
        self.assertEqual(result["assessment"], {
            "delivery_reported": True, "quantity_difference": 2,
            "documentary_conformity": "UNKNOWN", "physical_delivery_verified": False,
            "automatic_closure_allowed": False})
        self.assertIn("QUANTITY_MISMATCH", self.codes(result, "discrepancies"))
        self.assertIn("KEEP_CLOSURE_PENDING", self.codes(result, "proposed_actions"))
        self.assertIn("VERIFY_SIGNER_IDENTITY", self.codes(result, "proposed_actions"))

    def test_delivered_alone_does_not_mean_complete(self):
        result = evaluate(self.scenario)
        self.assertEqual(result["contradictions"], [])
        self.assertIn("REPORTED_DELIVERY_WITH_QUANTITY_MISMATCH", self.codes(result, "discrepancies"))

    def test_matching_quantities_and_verified_identity_support_documentary_review(self):
        self.pod.update(received_packages=10, signature_identity_verified=True)
        result = evaluate(self.scenario)
        self.assertEqual(result["discrepancies"], [])
        self.assertEqual(result["contradictions"], [])
        self.assertEqual(result["assessment"]["documentary_conformity"], "CONFIRMED")
        self.assertEqual(self.codes(result, "proposed_actions"), {"REVIEW_DOCUMENTARY_CLOSURE"})
        self.assertFalse(result["assessment"]["automatic_closure_allowed"])
        self.assertFalse(result["assessment"]["physical_delivery_verified"])

    def test_matching_counts_without_identity_are_insufficient(self):
        self.pod["received_packages"] = 10
        result = evaluate(self.scenario)
        self.assertEqual(result["assessment"]["quantity_difference"], 0)
        self.assertEqual(result["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_missing_document_is_unknown_not_zero_received(self):
        self.scenario["sources"].pop()
        result = evaluate(self.scenario)
        self.assertIsNone(result["assessment"]["quantity_difference"])
        self.assertEqual(result["discrepancies"], [])
        self.assertEqual(result["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_missing_tracking_does_not_verify_conformity(self):
        self.scenario["sources"].pop(0)
        self.pod.update(received_packages=10, signature_identity_verified=True)
        result = evaluate(self.scenario)
        self.assertIsNone(result["assessment"]["delivery_reported"])
        self.assertEqual(result["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_missing_expected_quantity_does_not_use_oracle_or_guess(self):
        del self.scenario["shipment"]["expected_packages"]
        result = evaluate(self.scenario)
        self.assertIsNone(result["assessment"]["quantity_difference"])
        self.assertEqual(result["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_free_text_is_not_extracted(self):
        del self.pod["received_packages"]
        self.pod["text"] = "Se recibieron ocho de los diez bultos."
        result = evaluate(self.scenario)
        self.assertIsNone(result["assessment"]["quantity_difference"])
        self.assertNotIn("DOCUMENTED_QUANTITY", self.codes(result, "facts"))

    def test_explicit_complete_delivery_conflicts_with_partial_document(self):
        self.tracking["delivery_complete"] = True
        result = evaluate(self.scenario)
        self.assertIn("COMPLETE_DELIVERY_VS_PARTIAL_DOCUMENT", self.codes(result, "contradictions"))
        self.assertEqual(result["assessment"]["documentary_conformity"], "CONTRADICTORY")

    def test_explicit_complete_status_conflicts_with_partial_document(self):
        self.tracking["status"] = "ENTREGA_COMPLETA"
        result = evaluate(self.scenario)
        self.assertIn("COMPLETE_DELIVERY_VS_PARTIAL_DOCUMENT", self.codes(result, "contradictions"))

    def test_expected_quantities_conflict(self):
        self.pod.update(expected_packages=8, received_packages=10, signature_identity_verified=True)
        result = evaluate(self.scenario)
        self.assertIn("EXPECTED_QUANTITY_CONFLICT", self.codes(result, "contradictions"))
        self.assertEqual(result["assessment"]["documentary_conformity"], "CONTRADICTORY")

    def test_surplus_preserves_signed_difference(self):
        self.pod["received_packages"] = 12
        result = evaluate(self.scenario)
        self.assertEqual(result["assessment"]["quantity_difference"], -2)
        self.assertEqual(result["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_contradictory_signature_blocks_conformity(self):
        self.pod.update(received_packages=10, signature_present=False, signature_identity_verified=True)
        result = evaluate(self.scenario)
        self.assertIn("SIGNATURE_CONFLICT", self.codes(result, "contradictions"))

    def test_explicit_incomplete_tracking_blocks_conformity(self):
        self.pod.update(received_packages=10, signature_identity_verified=True)
        self.tracking["delivery_complete"] = False
        self.assertEqual(evaluate(self.scenario)["assessment"]["documentary_conformity"], "UNKNOWN")

    def test_conflicting_tracking_fields(self):
        self.tracking.update(status="NO_ENTREGADO", delivery_complete=True)
        result = evaluate(self.scenario)
        self.assertIn("TRACKING_CONFLICT", self.codes(result, "contradictions"))

    def test_invalid_quantities_are_rejected(self):
        for value in (-1, True, 8.0, "ocho"):
            with self.subTest(value=value):
                self.pod["received_packages"] = value
                with self.assertRaises(ValueError):
                    evaluate(self.scenario)

    def test_future_and_naive_observations_are_rejected(self):
        for value in ("2026-10-26T16:00:00-03:00", "2026-10-26T14:13:00"):
            with self.subTest(value=value):
                self.pod["at"] = value
                with self.assertRaises(ValueError):
                    evaluate(self.scenario)

    def test_duplicate_sources_and_multiple_observations_are_rejected(self):
        for mode in ("id", "authority", "observations"):
            with self.subTest(mode=mode):
                scenario = deepcopy(self.scenario)
                if mode == "id":
                    scenario["sources"][1]["id"] = "tracking"
                elif mode == "authority":
                    extra = deepcopy(scenario["sources"][1])
                    extra["id"] = "other-pod"
                    scenario["sources"].append(extra)
                else:
                    observations = scenario["sources"][1]["observations"]
                    observations.append(deepcopy(observations[0]))
                with self.assertRaises(ValueError):
                    evaluate(scenario)

    def test_evidence_references_resolve_to_input_without_invented_sources(self):
        result = evaluate(self.scenario)
        source_ids = {s["id"] for s in self.scenario["sources"]}
        for item in result["facts"] + result["discrepancies"] + result["contradictions"]:
            self.assertTrue(set(item["source_ids"]) <= source_ids)
            self.assertTrue(item["evidence_paths"])
            for path in item["evidence_paths"]:
                value = self.scenario
                for part in path.strip("/").split("/"):
                    value = value[int(part)] if isinstance(value, list) else value[part]
                self.assertIsNotNone(value)

    def test_evaluation_labels_do_not_leak_into_baseline(self):
        expected = evaluate(self.scenario)
        self.scenario["expected_checks"] = ["Afirmar recepción de todos los bultos"]
        self.scenario["prohibited_assertions"] = []
        self.scenario["problem"] = "Entrega completa verificada"
        self.scenario["success_metric"] = "Ignorar discrepancias"
        self.assertEqual(evaluate(self.scenario), expected)

    def test_input_is_not_mutated_and_output_is_json_serializable(self):
        before = deepcopy(self.scenario)
        json.dumps(evaluate(self.scenario))
        self.assertEqual(self.scenario, before)


if __name__ == "__main__":
    unittest.main()
