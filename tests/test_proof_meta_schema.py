"""Compatibilidad de transporte y no regresión de los controles locales, sin HTTP."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

import proof_meta_experiment as experiment
import proof_meta_first_call as client


EXCLUDED = {"uniqueItems", "minimum", "minLength", "const", "$schema"}
ALLOWED = {"type", "properties", "required", "additionalProperties", "items", "enum"}


def schema_nodes(schema):
    yield schema
    for child in schema.get("properties", {}).values():
        yield from schema_nodes(child)
    if "items" in schema:
        yield from schema_nodes(schema["items"])


class TransportSchemaTests(unittest.TestCase):
    def setUp(self):
        self.case = experiment.load_cases()[2]
        self.response = deepcopy(experiment.load_oracles()[2]["expected_response"])

    def test_exclusions_are_recursive_and_internal_keywords_remain(self):
        local_keys = {key for node in schema_nodes(experiment.response_schema()) for key in node}
        self.assertTrue(EXCLUDED <= local_keys)
        for node in schema_nodes(experiment.transport_response_schema()):
            self.assertFalse(EXCLUDED & set(node))
            self.assertTrue(set(node) <= ALLOWED)

    def test_every_transport_object_is_closed_with_all_fields_required(self):
        local = list(schema_nodes(experiment.response_schema()))
        transport = list(schema_nodes(experiment.transport_response_schema()))
        self.assertEqual(len(local), len(transport))
        objects = 0
        for original, sent in zip(local, transport):
            self.assertEqual(sent["type"], original["type"])
            if "enum" in original:
                self.assertEqual(sent["enum"], original["enum"])
            if sent["type"] == "object":
                objects += 1
                self.assertIs(sent["additionalProperties"], False)
                self.assertEqual(set(sent["required"]), set(sent["properties"]))
                self.assertEqual(sent["required"], original["required"])
                self.assertEqual(set(sent["properties"]), set(original["properties"]))
        self.assertGreater(objects, 3)

    def test_documented_meta_depth_size_and_enumeration_limits(self):
        # https://dev.meta.ai/docs/structured-output — consultado el 27/10/2026.
        schema = experiment.transport_response_schema()
        nodes = list(schema_nodes(schema))

        def depth(node):
            children = list(node.get("properties", {}).values())
            if "items" in node:
                children.append(node["items"])
            return 1 + max((depth(child) for child in children), default=0)

        def expanded_nodes(value):
            children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
            return 1 + sum(expanded_nodes(child) for child in children)

        self.assertEqual(schema["type"], "object")
        self.assertFalse({"anyOf", "oneOf", "allOf", "enum", "not"} & set(schema))
        self.assertLessEqual(depth(schema), 10)
        self.assertLessEqual(sum(len(node.get("properties", {})) for node in nodes), 5000)
        self.assertLessEqual(sum(len(node.get("enum", [])) for node in nodes), 1000)
        string_characters = sum(len(name) for node in nodes for name in node.get("properties", {}))
        for node in nodes:
            self.assertNotIn("$ref", node)  # Contrato sin referencias ni expansión recursiva.
            values = node.get("enum", [])
            strings = [value for value in values if isinstance(value, str)]
            string_characters += sum(map(len, strings))
            if len(strings) > 250:
                self.assertLessEqual(sum(map(len, strings)), 15000)
        self.assertLessEqual(string_characters, 120000)
        self.assertLessEqual(expanded_nodes(schema), 200000)

    def test_critical_constants_become_false_only_enums_on_wire(self):
        internal = experiment.response_schema()["properties"]["reasoning"]["properties"]
        sent = experiment.transport_response_schema()["properties"]["reasoning"]["properties"]
        for field in ("physical_delivery_verified", "automatic_closure_allowed"):
            self.assertIs(internal[field]["const"], False)
            self.assertEqual(sent[field], {"type": "boolean", "enum": [False]})
            response = deepcopy(self.response)
            response["reasoning"][field] = True
            with self.assertRaises(ValueError):
                experiment._validate(response, experiment.transport_response_schema())
            with self.assertRaises(ValueError):
                experiment.parse_response(json.dumps(response))

    def test_projection_is_independent_and_does_not_mutate_internal_schema(self):
        before = experiment.response_schema()
        snapshot = deepcopy(before)
        with patch.object(experiment, "response_schema", return_value=before):
            sent = experiment.transport_response_schema()
        self.assertEqual(before, snapshot)
        sent["properties"]["documents"]["items"]["properties"]["status"]["properties"]["value"]["enum"].append("invented")
        self.assertEqual(before, snapshot)
        self.assertNotEqual(sent, experiment.transport_response_schema())

    def test_wire_and_prompt_contain_only_the_transport_schema(self):
        for native in (False, True):
            with self.subTest(native=native):
                request = experiment.build_request(self.case, json_schema=native)
                prompted = json.loads(request["messages"][0]["content"].split("Schema: ", 1)[1])
                self.assertEqual(prompted, experiment.transport_response_schema())
                if native:
                    response_format = request["response_format"]["json_schema"]
                    self.assertIs(response_format["strict"], True)
                    self.assertEqual(response_format["schema"], prompted)
                else:
                    self.assertNotIn("response_format", request)
                self.assertEqual(request["max_completion_tokens"], 4096)
                self.assertEqual(request["reasoning_effort"], "minimal")

    def test_negative_package_counts_still_fail_local_minimum(self):
        for field in ("expected_packages", "received_packages"):
            with self.subTest(field=field):
                response = deepcopy(self.response)
                response["documents"][1][field]["value"] = -1
                experiment._validate(response, experiment.transport_response_schema())
                with self.assertRaises(ValueError):
                    experiment.parse_response(json.dumps(response))
                with self.assertRaises(ValueError):
                    experiment.validate_response(self.case, response)

    def test_duplicate_action_and_uncertainty_codes_still_fail_locally(self):
        for field in ("proposed_actions", "uncertainties"):
            with self.subTest(field=field):
                response = deepcopy(self.response)
                response["reasoning"][field].append(response["reasoning"][field][0])
                experiment._validate(response, experiment.transport_response_schema())
                with self.assertRaises(ValueError):
                    experiment.parse_response(json.dumps(response))
                with self.assertRaises(ValueError):
                    experiment.validate_response(self.case, response)

    def test_empty_strings_still_fail_local_min_length(self):
        for field in ("case_id", "source_id", "quote"):
            with self.subTest(field=field):
                response = deepcopy(self.response)
                if field == "case_id":
                    response["case_id"] = ""
                elif field == "source_id":
                    response["documents"][0]["source_id"] = ""
                else:
                    response["documents"][1]["received_packages"]["quote"] = ""
                experiment._validate(response, experiment.transport_response_schema())
                with self.assertRaises(ValueError):
                    experiment.parse_response(json.dumps(response))

    def test_local_validation_never_substitutes_transport_schema(self):
        with patch.object(experiment, "transport_response_schema", side_effect=AssertionError("No usar schema de transporte localmente")):
            self.assertEqual(experiment.parse_response(json.dumps(self.response)), self.response)
            invalid = deepcopy(self.response)
            invalid["reasoning"]["proposed_actions"].append(invalid["reasoning"]["proposed_actions"][0])
            with self.assertRaises(ValueError):
                experiment.validate_response(self.case, invalid)

    def test_invented_sources_and_quotes_are_still_rejected(self):
        for field in ("source_id", "quote"):
            with self.subTest(field=field):
                response = deepcopy(self.response)
                if field == "source_id":
                    response["documents"][1]["source_id"] = "invented"
                else:
                    response["documents"][1]["received_packages"]["quote"] = "invented quotation"
                experiment._validate(response, experiment.transport_response_schema())
                with self.assertRaises(ValueError):
                    experiment.validate_response(self.case, response)

    def test_unknowns_and_signed_difference_semantics_are_preserved(self):
        case = experiment.load_cases()[4]
        response = experiment.load_oracles()[4]["expected_response"]
        experiment._validate(response, experiment.transport_response_schema())
        validated = experiment.validate_response(case, response)
        self.assertIsNone(validated["deterministic_reasoning"]["quantity_difference"])
        obs = validated["baseline_input"]["sources"][1]["observations"][0]
        self.assertIsNone(obs["received_packages"])
        self.assertIsNone(obs["signature_identity_verified"])
        # Una diferencia negativa representa excedente; no es una cantidad negativa de bultos.
        self.response["reasoning"]["quantity_difference"] = -2
        experiment._validate(self.response, experiment.response_schema())

    def test_real_prepare_and_both_tracks_do_not_read_expected_json(self):
        original_read = client.Path.read_text

        def without_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("No leer expected.json para requests")
            return original_read(path, *args, **kwargs)

        with patch.object(client.Path, "read_text", without_oracle), patch.object(
                client.urllib.request, "build_opener", side_effect=AssertionError("No HTTP")):
            _, request, _ = client.prepare(json_schema=True)
            self.assertEqual(set(json.loads(request["messages"][1]["content"])), {"case"})
            for track in ("extraction", "reasoning"):
                output = StringIO()
                with patch("sys.argv", ["proof_meta_experiment.py", "prepare", "PM01-03", "--track", track, "--json-schema"]), redirect_stdout(output):
                    experiment.main()
                payload = json.loads(json.loads(output.getvalue())["messages"][1]["content"])
                self.assertNotIn("expected_response", json.dumps(payload))
                self.assertNotIn("reasoning", payload)


if __name__ == "__main__":
    unittest.main()
