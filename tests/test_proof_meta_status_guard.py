"""Estados críticos sintéticos: rechazo antes del baseline, sin oráculos ni HTTP."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import proof_hybrid as hybrid
import proof_meta_experiment as experiment


class StatusGuardTests(unittest.TestCase):
    def setUp(self):
        self.case = deepcopy(experiment.load_cases()[2])
        self.extraction = {"case_id": self.case["case_id"],
                           "documents": experiment.load_verified_extraction(self.case["case_id"])}

    def tracking(self, text, value, quote, *, complete=None):
        self.case["documents"][0]["text"] = "Envío: SYN-PM-103. " + text
        doc = self.extraction["documents"][0]
        doc["status"] = {"value": value, "quote": quote}
        doc["delivery_complete"] = complete or {"value": None, "quote": None}

    def reject_before_baseline(self):
        before = deepcopy(self.extraction)
        with patch.object(experiment, "evaluate", side_effect=AssertionError("Baseline no debe ejecutarse")) as engine:
            result = hybrid.run(self.case, self.extraction)
        engine.assert_not_called()
        self.assertEqual(self.extraction, before)
        self.assertEqual(result["extraction_validation"], "FAIL")
        self.assertEqual(result["engine_status"], "NOT_RUN")
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIsNone(result["operational_result"]["quantity_difference"])
        self.assertFalse(result["operational_result"]["automatic_closure_allowed"])
        self.assertTrue(result["review_required"])
        self.assertIn("REQUEST_ADDITIONAL_EVIDENCE", result["operational_result"]["proposed_actions"])

    def test_delivered_quote_and_value_match_without_promoting_completeness(self):
        self.tracking("Estado informado: ENTREGADO.", "ENTREGADO", "ENTREGADO")
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["extraction_validation"], "PASS_LOCAL_CHECKS_ONLY")
        self.assertEqual(result["operational_result"]["quantity_difference"], 2)
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        tracking = result["baseline_input"]["sources"][0]["observations"][0]
        self.assertEqual(tracking["status"], "ENTREGADO")
        self.assertIsNone(tracking["delivery_complete"])

    def test_delivered_quote_cannot_support_complete_delivery(self):
        self.tracking("Estado informado: ENTREGADO.", "ENTREGA_COMPLETA", "ENTREGADO")
        experiment.parse_response(json.dumps(self.extraction), extraction_only=True)  # Formalmente válido.
        self.reject_before_baseline()
        self.assertEqual(self.extraction["documents"][0]["status"]["value"], "ENTREGA_COMPLETA")

    def test_explicit_complete_status_preserves_existing_baseline_meaning(self):
        self.tracking("Estado informado: ENTREGA_COMPLETA.", "ENTREGA_COMPLETA", "ENTREGA_COMPLETA")
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["engine_status"], "COMPUTED_BY_BASELINE")
        self.assertEqual(result["operational_result"]["documentary_conformity"], "CONTRADICTORY")
        self.assertIn("DOCUMENTARY_CONFLICT", result["operational_result"]["uncertainties"])
        self.assertIsNone(result["baseline_input"]["sources"][0]["observations"][0]["delivery_complete"])

    def test_incompatible_status_declarations_never_select_one(self):
        for value in ("ENTREGADO", "NO_ENTREGADO"):
            with self.subTest(value=value):
                self.tracking("Estado informado: ENTREGADO. Estado informado: NO_ENTREGADO.", value, value)
                self.reject_before_baseline()

    def test_negated_conditional_ambiguous_and_unrecognized_contexts_require_review(self):
        for text in ("No ENTREGADO.", "Estado informado: no ENTREGADO.",
                     "Estado informado: ENTREGADO?", "Estado informado: ENTREGADO o NO_ENTREGADO.",
                     "Si llega, estado informado: ENTREGADO.", "Estado informado: ENTREGADO (sin confirmar).",
                     "Se niega la siguiente declaración. Estado informado: ENTREGADO.",
                     'Ejemplo: Estado informado: ENTREGADO.', 'Estado informado: "ENTREGADO".'):
            with self.subTest(text=text):
                self.tracking(text, "ENTREGADO", "ENTREGADO")
                self.reject_before_baseline()

    def test_missing_declaration_and_substring_of_not_delivered_do_not_confirm_delivery(self):
        for text, quote in (("Estado informado: PENDIENTE.", "PENDIENTE"),
                            ("Estado informado: NO_ENTREGADO.", "ENTREGADO")):
            with self.subTest(text=text):
                self.tracking(text, "ENTREGADO", quote)
                self.reject_before_baseline()

    def test_unknown_status_remains_null_when_document_is_ambiguous(self):
        self.tracking("Estado informado: ENTREGADO. Estado informado: NO_ENTREGADO.", None, None)
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["engine_status"], "COMPUTED_BY_BASELINE")
        self.assertIsNone(result["operational_result"]["delivery_reported"])
        self.assertEqual(result["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIn("TRACKING_UNKNOWN", result["operational_result"]["uncertainties"])
        self.assertTrue(result["review_required"])

    def test_explicit_not_delivered_is_a_supported_status_not_a_negated_delivered(self):
        self.tracking("Estado informado: NO_ENTREGADO.", "NO_ENTREGADO", "NO_ENTREGADO")
        result = hybrid.run(self.case, self.extraction)
        self.assertEqual(result["engine_status"], "COMPUTED_BY_BASELINE")
        self.assertIs(result["operational_result"]["delivery_reported"], False)
        self.assertIs(result["operational_result"]["physical_delivery_verified"], False)

    def test_citations_from_other_source_or_wrong_authority_are_rejected(self):
        other_quote = "Estado informado: ENTREGA_COMPLETA"
        self.case["documents"][1]["text"] += " " + other_quote + "."
        self.extraction["documents"][0]["status"] = {"value": "ENTREGA_COMPLETA", "quote": other_quote}
        self.reject_before_baseline()
        self.extraction["documents"][0]["status"] = {"value": "ENTREGADO", "quote": "ENTREGADO"}
        self.extraction["documents"][1]["status"] = {"value": "ENTREGA_COMPLETA", "quote": other_quote}
        self.reject_before_baseline()

    def test_foreign_shipment_quote_cannot_be_used_for_target_shipment(self):
        self.extraction["documents"][0]["status"] = {
            "value": "ENTREGADO", "quote": "Envío: SYN-OTRO-999. Estado informado: ENTREGADO"}
        self.reject_before_baseline()
        self.case["documents"][0]["text"] = "Envío: SYN-OTRO-999. Estado informado: ENTREGADO."
        self.extraction["documents"][0]["shipment_id"] = {"value": "SYN-PM-103", "quote": "SYN-OTRO-999"}
        self.extraction["documents"][0]["status"] = {"value": "ENTREGADO", "quote": "ENTREGADO"}
        self.reject_before_baseline()

    def test_delivery_complete_requires_a_separate_declaration_even_with_complete_status(self):
        for state in ("ENTREGADO", "ENTREGA_COMPLETA", "NO_ENTREGADO"):
            with self.subTest(state=state):
                self.tracking("Estado informado: " + state + ".", state, state,
                              complete={"value": state != "NO_ENTREGADO", "quote": state})
                self.reject_before_baseline()

    def test_separate_completion_true_or_false_preserves_independent_status(self):
        for value, word in ((True, "sí"), (False, "no")):
            with self.subTest(value=value):
                self.tracking("Estado informado: ENTREGADO. Entrega completa: " + word + ".",
                              "ENTREGADO", "ENTREGADO", complete={"value": value, "quote": "Entrega completa: " + word})
                result = hybrid.run(self.case, self.extraction)
                self.assertEqual(result["engine_status"], "COMPUTED_BY_BASELINE")
                observation = result["baseline_input"]["sources"][0]["observations"][0]
                self.assertEqual(observation["status"], "ENTREGADO")
                self.assertIs(observation["delivery_complete"], value)

    def test_incompatible_or_negated_completion_does_not_get_confirmed(self):
        for text in ("Entrega completa: sí. Entrega completa: no.", "No es cierto: Entrega completa: sí."):
            with self.subTest(text=text):
                self.tracking("Estado informado: ENTREGADO. " + text, "ENTREGADO", "ENTREGADO",
                              complete={"value": True, "quote": "Entrega completa: sí"})
                self.reject_before_baseline()

    def test_supported_spelling_and_repeated_consistent_status_do_not_change_semantics(self):
        for text, quote in (("ENTREGADO.", "ENTREGADO"), ("Estado: ENTREGADO; Estado informado: ENTREGADO.", "ENTREGADO"),
                            ("estado informado: entregado.", "entregado"), ("Estado informado: ENTREGADO.", "Estado informado: ENTREGADO.")):
            with self.subTest(text=text):
                self.tracking(text, "ENTREGADO", quote)
                self.assertEqual(hybrid.run(self.case, self.extraction)["operational_result"]["documentary_conformity"], "UNKNOWN")

    def test_operational_guard_does_not_load_expected_answers(self):
        original_read = Path.read_text

        def no_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("Oráculo no permitido")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", no_oracle), patch.object(
                experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("No HTTP")):
            self.tracking("Estado informado: ENTREGADO.", "ENTREGADO", "ENTREGADO")
            self.assertEqual(hybrid.run(self.case, self.extraction)["engine_status"], "COMPUTED_BY_BASELINE")
            self.extraction["documents"][0]["status"]["value"] = "ENTREGA_COMPLETA"
            self.reject_before_baseline()


if __name__ == "__main__":
    unittest.main()
