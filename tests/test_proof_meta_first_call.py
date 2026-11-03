"""Transporte totalmente simulado. Ningún test consume Meta Model API."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import proof_meta_experiment as experiment
import proof_meta_first_call as client


FAKE_SECRET = "SYNTHETIC_TEST_SECRET_NOT_A_CREDENTIAL"


class FirstCallTests(unittest.TestCase):
    def setUp(self):
        (client.ROOT / "artifacts").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=client.ROOT / "artifacts")
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "call"
        self.content = deepcopy(experiment.load_oracles()[2]["expected_response"])
        self.envelope = {"id": "SYN-RESPONSE-001", "model": "muse-spark-1.3",
                         "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
                         "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.content)}}]}
        self.response = MagicMock()
        self.response.status = 200
        self.response.read.return_value = json.dumps(self.envelope).encode()
        self.response.__enter__.return_value = self.response
        self.opener = MagicMock()
        self.opener.open.return_value = self.response

    def execute_mock(self, **kwargs):
        with patch.dict(client.os.environ, {client.SECRET_NAME: FAKE_SECRET}), patch.object(
                client.urllib.request, "build_opener", return_value=self.opener):
            return client.execute(self.destination, billing_confirmed=True, protocol_confirmed=True, **kwargs)

    def test_preparation_has_one_synthetic_case_and_explicit_bounds(self):
        case, request, body = client.prepare(json_schema=True)
        self.assertEqual(case["case_id"], "PM01-03")
        self.assertIs(case["synthetic"], True)
        self.assertEqual(request["model"], "muse-spark-1.3")
        self.assertEqual(request["max_completion_tokens"], 4096)
        self.assertEqual(request["max_completion_tokens"], client.MAX_OUTPUT_TOKENS)
        self.assertNotIn("max_tokens", request)
        self.assertEqual(request["reasoning_effort"], "minimal")
        self.assertIs(request["stream"], False)
        self.assertLessEqual(len(body), client.MAX_REQUEST_BYTES)
        self.assertEqual(request["response_format"]["json_schema"]["schema"], experiment.transport_response_schema())

    def test_default_cli_is_dry_run_and_never_reads_a_secret_or_sends(self):
        output = StringIO()
        original_get = client.os.environ.get

        def without_secret(name, *args):
            if name == client.SECRET_NAME:
                raise AssertionError("No leer secreto")
            return original_get(name, *args)

        with patch("sys.argv", ["proof_meta_first_call.py"]), patch.object(
                client.os.environ, "get", side_effect=without_secret), patch.object(
                client.urllib.request, "build_opener") as build, redirect_stdout(output):
            client.main()
        self.assertEqual(json.loads(output.getvalue())["mode"], "DRY_RUN_NO_HTTP")
        build.assert_not_called()

    def test_missing_confirmation_blocks_before_transport(self):
        for billing, protocol in ((False, False), (True, False), (False, True)):
            with self.subTest(billing=billing, protocol=protocol), patch.object(client.urllib.request, "build_opener") as build:
                with self.assertRaises(ValueError):
                    client.execute(self.destination, billing_confirmed=billing, protocol_confirmed=protocol)
                build.assert_not_called()

    def test_missing_environment_secret_does_not_create_attempt(self):
        with patch.dict(client.os.environ, {client.SECRET_NAME: ""}), patch.object(client.urllib.request, "build_opener") as build:
            with self.assertRaises(ValueError):
                client.execute(self.destination, billing_confirmed=True, protocol_confirmed=True)
            build.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_exactly_one_post_with_bearer_timeout_and_consumption_record(self):
        result = self.execute_mock(json_schema=True)
        self.opener.open.assert_called_once()
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, client.ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE_SECRET)
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 30})
        self.assertEqual(result["requests_attempted"], 1)
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(result["usage"]["total_tokens"], 300)
        self.assertEqual(result["usage_status"], "REPORTED")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["response_completeness"], "COMPLETE_STOP")
        self.assertIsNone(result["reasoning_tokens"])
        self.assertIsNone(result["visible_output_tokens"])
        self.assertEqual(result["status"], "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED")
        self.assertEqual(result["META_MODEL_EVALUATION"], "NOT_EVALUATED")
        self.assertIsNone(result["cost"])
        saved = (self.destination / "request.json").read_bytes()
        self.assertEqual(saved, request.data)
        self.assertEqual(hashlib.sha256(saved).hexdigest(), result["request_sha256"])
        for path in self.destination.iterdir():
            self.assertNotIn(FAKE_SECRET, path.read_text())

    def test_http_error_has_no_retry_no_sensitive_error_body_and_unknown_usage(self):
        self.opener.open.side_effect = urllib.error.HTTPError(client.ENDPOINT, 429, FAKE_SECRET, {}, None)
        result = self.execute_mock()
        self.opener.open.assert_called_once()
        self.assertEqual(result["status"], "FAILED_NO_RETRY")
        self.assertEqual(result["http_status"], 429)
        self.assertIsNone(result["usage"])
        self.assertIn("POSSIBLE_CHARGE", result["usage_status"])
        for path in self.destination.iterdir():
            self.assertNotIn(FAKE_SECRET, path.read_text())

    def test_timeout_or_connection_failure_never_retries(self):
        for index, error in enumerate((TimeoutError("synthetic"), urllib.error.URLError("synthetic"))):
            with self.subTest(error=type(error).__name__):
                self.destination = Path(self.temp.name) / str(index)
                self.opener.open.reset_mock()
                self.opener.open.side_effect = error
                result = self.execute_mock()
                self.opener.open.assert_called_once()
                self.assertEqual(result["status"], "FAILED_NO_RETRY")

    def test_http_error_body_is_saved_redacted_with_one_request(self):
        body = json.dumps({"error": {"message": "synthetic protocol error", "echo": FAKE_SECRET}}).encode()
        self.opener.open.side_effect = urllib.error.HTTPError(client.ENDPOINT, 400, "error", {}, BytesIO(body))
        result = self.execute_mock()
        self.assertEqual(result["http_status"], 400)
        self.opener.open.assert_called_once()
        saved = json.loads((self.destination / "http_error.json").read_text())
        self.assertIn("synthetic protocol error", saved["body"])
        self.assertNotIn(FAKE_SECRET, saved["body"])
        self.assertFalse(saved["truncated"])

    def test_redirect_is_not_followed(self):
        handler = client.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 307, "redirect", {}, "https://another.invalid"))
        self.opener.open.side_effect = urllib.error.HTTPError(client.ENDPOINT, 307, "redirect", {}, None)
        result = self.execute_mock()
        self.assertEqual(result["http_status"], 307)
        self.opener.open.assert_called_once()

    def test_existing_output_directory_cannot_trigger_a_second_attempt(self):
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            self.execute_mock()
        self.opener.open.assert_not_called()

    def test_output_must_be_inside_project_artifacts(self):
        with self.assertRaises(ValueError):
            client.execute(client.ROOT / ".git" / "unexpected", billing_confirmed=True, protocol_confirmed=True)
        self.opener.open.assert_not_called()

    def test_response_limit_is_enforced_without_a_second_read(self):
        self.response.read.return_value = b" " * (client.MAX_RESPONSE_BYTES + 1)
        result = self.execute_mock()
        self.assertEqual(result["status"], "FAILED_NO_RETRY")
        self.response.read.assert_called_once_with(client.MAX_RESPONSE_BYTES + 1)
        self.opener.open.assert_called_once()

    def test_truncated_response_preserves_reported_consumption_without_fallback(self):
        self.envelope["choices"][0]["finish_reason"] = "length"
        self.envelope["usage"]["completion_tokens_details"] = {"reasoning_tokens": 150}
        for index, content in enumerate((json.dumps(self.content), '{"case_id":')):
            with self.subTest(content_complete=index == 0):
                self.destination = Path(self.temp.name) / str(index)
                self.opener.open.reset_mock()
                self.envelope["choices"][0]["message"]["content"] = content
                self.response.read.return_value = json.dumps(self.envelope).encode()
                result = self.execute_mock()
                self.assertEqual(result["status"], "FAILED_NO_RETRY")
                self.assertEqual(result["usage"]["total_tokens"], 300)
                self.assertEqual(result["usage_status"], "REPORTED")
                self.assertEqual(result["finish_reason"], "length")
                self.assertEqual(result["response_completeness"], "INCOMPLETE_LENGTH")
                self.assertEqual(result["reasoning_tokens"], 150)
                self.assertEqual(result["visible_output_tokens"], 50)
                self.assertEqual(result["visible_output_tokens_basis"], "DERIVED_COMPLETION_MINUS_REASONING")
                self.assertEqual(result["format_validation"], "FAIL")
                self.assertEqual(result["operational_consistency"], "NOT_RUN")
                self.assertEqual(result["META_MODEL_EVALUATION"], "NOT_EVALUABLE_INCOMPLETE_RESPONSE")
                self.assertFalse((self.destination / "local_validation.json").exists())
                self.opener.open.assert_called_once()

    def test_success_records_reasoning_and_derived_visible_tokens(self):
        self.envelope["usage"]["completion_tokens_details"] = {"reasoning_tokens": 0}
        self.response.read.return_value = json.dumps(self.envelope).encode()
        result = self.execute_mock()
        self.assertEqual(result["status"], "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED")
        self.assertEqual(result["reasoning_tokens"], 0)
        self.assertEqual(result["visible_output_tokens"], 200)
        self.assertEqual(result["usage"]["completion_tokens_details"], {"reasoning_tokens": 0})

    def test_inconsistent_token_details_do_not_invent_visible_count(self):
        self.envelope["usage"]["completion_tokens_details"] = {"reasoning_tokens": 201}
        self.response.read.return_value = json.dumps(self.envelope).encode()
        result = self.execute_mock()
        self.assertEqual(result["reasoning_tokens"], 201)
        self.assertIsNone(result["visible_output_tokens"])
        self.assertEqual(result["visible_output_tokens_basis"], "UNAVAILABLE")

    def test_operational_mismatch_is_recorded_without_retry_or_success_claim(self):
        self.content["reasoning"]["quantity_difference"] = 0
        self.envelope["choices"][0]["message"]["content"] = json.dumps(self.content)
        self.response.read.return_value = json.dumps(self.envelope).encode()
        result = self.execute_mock()
        self.assertEqual(result["format_validation"], "PASS")
        self.assertEqual(result["operational_consistency"], "FAIL")
        self.assertEqual(result["status"], "FAILED_NO_RETRY")
        self.opener.open.assert_called_once()

    def test_echoed_secret_is_redacted_before_persisting_response_and_metadata(self):
        self.envelope["id"] = FAKE_SECRET
        self.envelope["diagnostic"] = FAKE_SECRET
        self.response.read.return_value = json.dumps(self.envelope).encode()
        result = self.execute_mock()
        self.assertEqual(result["response_id"], "[REDACTED]")
        for path in self.destination.iterdir():
            self.assertNotIn(FAKE_SECRET, path.read_text())

    def test_unknown_or_invalid_consumption_is_not_invented(self):
        self.assertIsNone(client._usage({}))
        self.assertEqual(client._usage({"usage": {"total_tokens": True, "prompt_tokens": -1, "completion_tokens": "2", "secret": "not-a-token-count"}}), {})
        for details in (None, [], {"reasoning_tokens": True}, {"reasoning_tokens": -1}, {"reasoning_tokens": "2"}):
            with self.subTest(details=details):
                self.assertEqual(client._usage({"usage": {"completion_tokens_details": details}}), {})

    def test_total_timeout_raises_and_restores_signal_handler(self):
        before = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError):
            with client.deadline(30):
                signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)

    def test_request_byte_limit_prevents_transport(self):
        with patch.object(client, "build_request", return_value={"padding": "x" * (client.MAX_REQUEST_BYTES + 1)}):
            with self.assertRaises(ValueError):
                client.prepare()
        self.opener.open.assert_not_called()

    def test_request_budget_must_match_client_limit_before_transport(self):
        with patch.object(client, "build_request", return_value={"max_completion_tokens": 4097}):
            with self.assertRaises(ValueError):
                self.execute_mock()
        self.opener.open.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_both_prepare_cli_tracks_work_when_oracle_loading_is_forbidden(self):
        for track in ("extraction", "reasoning"):
            with self.subTest(track=track), patch.object(experiment, "load_oracles", side_effect=AssertionError("Oráculo no permitido")), patch(
                    "sys.argv", ["proof_meta_experiment.py", "prepare", "PM01-03", "--track", track]), redirect_stdout(StringIO()) as output:
                experiment.main()
                payload = json.loads(json.loads(output.getvalue())["messages"][1]["content"])
                self.assertNotIn("expected_response", json.dumps(payload))
                self.assertNotIn("reasoning", payload)

    def test_verified_extraction_is_factual_and_has_no_operational_answers(self):
        for case, truth in zip(experiment.load_cases(), experiment.load_oracles()):
            facts = experiment.load_verified_extraction(case["case_id"])
            self.assertEqual(facts, truth["expected_response"]["documents"])
            for doc in facts:
                self.assertEqual(set(doc), {"source_id", *experiment.FIELDS})
                self.assertNotIn("proposed_actions", doc)
                self.assertNotIn("documentary_conformity", doc)


    def hybrid_response(self, extraction=None, finish="stop"):
        if extraction is None:
            extraction = {"case_id": self.content["case_id"], "documents": deepcopy(self.content["documents"])}
        self.envelope["choices"][0] = {"finish_reason": finish, "message": {"content": json.dumps(extraction)}}
        self.response.read.return_value = json.dumps(self.envelope).encode()
        return extraction

    def test_hybrid_preparation_uses_only_extraction_builder_and_strict_contract(self):
        with patch.object(client, "build_request", side_effect=AssertionError("No contrato legacy")), patch.object(
                client.proof_hybrid, "build_extraction_request", wraps=client.proof_hybrid.build_extraction_request) as build:
            case, request, body = client.prepare(mode="hybrid")
        build.assert_called_once_with(case)
        self.assertEqual(request, client.proof_hybrid.build_extraction_request(case))
        self.assertEqual(json.loads(body), request)
        self.assertEqual(set(request["response_format"]["json_schema"]["schema"]["properties"]), {"case_id", "documents"})
        self.assertIs(request["response_format"]["json_schema"]["strict"], True)
        self.assertNotIn("reasoning", json.loads(request["messages"][1]["content"]))
        for field in ("quantity_difference", "documentary_conformity", "proposed_actions", "uncertainties"):
            self.assertNotIn(field, json.dumps(request))
        self.assertEqual(request["max_completion_tokens"], 4096)
        self.assertEqual(request["reasoning_effort"], "minimal")

    def test_hybrid_mode_or_contract_mismatch_never_falls_back_or_sends(self):
        with self.assertRaises(ValueError):
            self.execute_mock(mode="Hybrid")
        wrong = experiment.build_request(experiment.load_cases()[2], json_schema=True)
        with patch.object(client.proof_hybrid, "build_extraction_request", return_value=wrong):
            with self.assertRaises(ValueError):
                self.execute_mock(mode="hybrid")
        self.opener.open.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_hybrid_http_routes_extraction_to_baseline_without_oracles(self):
        extraction = self.hybrid_response()
        original_read = Path.read_text

        def no_oracle(path, *args, **kwargs):
            if path.name == "expected.json":
                raise AssertionError("Oráculo leído durante inferencia o decisión")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", no_oracle), patch.object(
                experiment, "load_oracles", side_effect=AssertionError("No oráculo")), patch.object(
                client, "validate_response", side_effect=AssertionError("No razonamiento legacy")), patch.object(
                client, "parse_response", wraps=client.parse_response) as parse, patch.object(
                client.proof_hybrid, "run", wraps=client.proof_hybrid.run) as run:
            result = self.execute_mock(mode="hybrid", json_schema=True)
        parse.assert_called_once_with(json.dumps(self.envelope), extraction_only=True)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1], extraction)
        self.opener.open.assert_called_once()
        sent = self.opener.open.call_args.args[0]
        self.assertEqual(sent.full_url, client.ENDPOINT)
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 30})
        self.assertEqual(result["client_mode"], "hybrid")
        self.assertEqual(result["response_contract"], "EXTRACTION_ONLY")
        self.assertEqual(result["format_validation"], "PASS")
        self.assertEqual(result["extraction_validation"], "PASS_LOCAL_CHECKS_ONLY")
        self.assertEqual(result["deterministic_calculation"], "COMPUTED_BY_BASELINE")
        self.assertEqual(result["semantic_review"], "PENDING")
        self.assertEqual(result["operational_consistency"], "NOT_SCORED_AGAINST_ORACLE")
        self.assertEqual(result["META_MODEL_EVALUATION"], "NOT_EVALUATED")
        validated = json.loads((self.destination / "local_validation.json").read_text())
        self.assertEqual(validated["evaluation_mode"], "HYBRID_HTTP_RESPONSE")
        self.assertEqual(validated["response_origin"], "NEW_HTTP_RESPONSE")
        self.assertEqual(validated["operational_result"]["quantity_difference"], 2)
        self.assertIn("QUANTITY_MISMATCH", validated["operational_result"]["uncertainties"])
        self.assertEqual(validated["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertFalse(validated["operational_result"]["automatic_closure_allowed"])
        self.assertEqual(sent.data, (self.destination / "request.json").read_bytes())
        self.assertEqual(result["request_sha256"], hashlib.sha256(sent.data).hexdigest())
        for path in self.destination.iterdir():
            self.assertNotIn(FAKE_SECRET, path.read_text())

    def test_hybrid_valid_but_incomplete_extraction_limits_calculation(self):
        extraction = self.hybrid_response()
        extraction["documents"][1]["received_packages"] = {"value": None, "quote": None}
        self.hybrid_response(extraction)
        result = self.execute_mock(mode="hybrid")
        self.assertEqual(result["status"], "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED")
        self.assertEqual(result["extraction_accuracy"], "NOT_EVALUATED_WITH_ORACLE")
        validated = json.loads((self.destination / "local_validation.json").read_text())
        operation = validated["operational_result"]
        self.assertIsNone(operation["quantity_difference"])
        self.assertEqual(operation["documentary_conformity"], "UNKNOWN")
        self.assertIn("QUANTITY_UNKNOWN", operation["uncertainties"])
        self.assertIn("REQUEST_ADDITIONAL_EVIDENCE", operation["proposed_actions"])
        self.assertTrue(validated["review_required"])
        self.opener.open.assert_called_once()

    def test_hybrid_invalid_sources_abstain_without_using_untrusted_fields(self):
        extraction = self.hybrid_response()
        extraction["documents"][1]["source_id"] = "invented"
        self.hybrid_response(extraction)
        result = self.execute_mock(mode="hybrid")
        self.assertEqual(result["format_validation"], "PASS")
        self.assertEqual(result["extraction_validation"], "FAIL")
        self.assertEqual(result["deterministic_calculation"], "NOT_RUN")
        self.assertEqual(result["status"], "FAILED_NO_RETRY")
        validated = json.loads((self.destination / "local_validation.json").read_text())
        self.assertEqual(validated["operational_result"]["documentary_conformity"], "UNKNOWN")
        self.assertIsNone(validated["operational_result"]["quantity_difference"])
        self.assertFalse(validated["operational_result"]["automatic_closure_allowed"])
        self.opener.open.assert_called_once()

    def test_hybrid_schema_failures_and_length_save_abstention_without_retry(self):
        extraction = self.hybrid_response()
        negative = deepcopy(extraction)
        negative["documents"][1]["received_packages"]["value"] = -1
        for index, (response, finish) in enumerate(((self.content, "stop"), (negative, "stop"), (extraction, "length"))):
            with self.subTest(index=index):
                self.destination = Path(self.temp.name) / str(index)
                self.opener.open.reset_mock()
                self.hybrid_response(response, finish=finish)
                result = self.execute_mock(mode="hybrid")
                self.assertEqual(result["format_validation"], "FAIL")
                self.assertEqual(result["extraction_validation"], "FAIL")
                self.assertEqual(result["deterministic_calculation"], "NOT_RUN")
                self.assertEqual(result["status"], "FAILED_NO_RETRY")
                self.assertNotEqual(result["META_MODEL_EVALUATION"], "PASS")
                if finish == "length":
                    self.assertEqual(result["META_MODEL_EVALUATION"], "NOT_EVALUABLE_INCOMPLETE_RESPONSE")
                validated = json.loads((self.destination / "local_validation.json").read_text())
                self.assertTrue(validated["review_required"])
                self.assertEqual(validated["operational_result"]["documentary_conformity"], "UNKNOWN")
                self.opener.open.assert_called_once()

    def test_hybrid_dry_run_cli_does_not_read_secret_or_open_transport(self):
        output = StringIO()
        original_get = client.os.environ.get

        def no_secret(name, *args):
            if name == client.SECRET_NAME:
                raise AssertionError("No leer secreto en dry-run")
            return original_get(name, *args)

        with patch("sys.argv", ["proof_meta_first_call.py", "--mode", "hybrid", "--json-schema"]), patch.object(
                client.os.environ, "get", side_effect=no_secret), patch.object(
                client.urllib.request, "build_opener") as build, redirect_stdout(output):
            client.main()
        dry = json.loads(output.getvalue())
        self.assertEqual(dry["mode"], "DRY_RUN_NO_HTTP")
        self.assertEqual(dry["client_mode"], "hybrid")
        self.assertEqual(set(dry["request"]["response_format"]["json_schema"]["schema"]["properties"]), {"case_id", "documents"})
        build.assert_not_called()

    def test_explicit_legacy_preserves_default_request_and_validation(self):
        with patch.object(client.proof_hybrid, "build_extraction_request", side_effect=AssertionError("No constructor híbrido")), patch.object(
                client.proof_hybrid, "run", side_effect=AssertionError("No motor híbrido")):
            self.assertEqual(client.prepare(json_schema=True), client.prepare(json_schema=True, mode="legacy"))
            result = self.execute_mock(mode="legacy", json_schema=True)
        self.assertEqual(result["client_mode"], "legacy")
        self.assertEqual(result["operational_consistency"], "PASS")
        self.assertEqual(result["status"], "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED")

    def test_hybrid_semantic_status_error_is_rejected_before_baseline(self):
        extraction = self.hybrid_response()
        extraction["documents"][0]["status"] = {"value": "ENTREGA_COMPLETA", "quote": "ENTREGADO"}
        self.hybrid_response(extraction)
        with patch.object(experiment, "evaluate", side_effect=AssertionError("No baseline con estado inválido")) as engine:
            result = self.execute_mock(mode="hybrid", json_schema=True)
        engine.assert_not_called()
        self.assertEqual(result["format_validation"], "PASS")
        self.assertEqual(result["extraction_validation"], "FAIL")
        self.assertEqual(result["deterministic_calculation"], "NOT_RUN")
        self.assertEqual(result["status"], "FAILED_NO_RETRY")
        self.opener.open.assert_called_once()
        saved = json.loads((self.destination / "response.json").read_text())
        self.assertEqual(json.loads(saved["choices"][0]["message"]["content"]), extraction)

    def test_case_selection_prepares_only_requested_synthetic_input_without_oracle(self):
        with patch.object(experiment, "load_oracles", side_effect=AssertionError("No oráculo")):
            for case_id in ("PM01-03", "PM01-05", "PM01-02"):
                with self.subTest(case_id=case_id):
                    case, request, body = client.prepare(mode="hybrid", case_id=case_id)
                    self.assertEqual(case["case_id"], case_id)
                    self.assertIs(case["synthetic"], True)
                    self.assertEqual(json.loads(request["messages"][1]["content"])["case"]["case_id"], case_id)
                    self.assertNotIn("expected.json", body.decode())
                    self.assertEqual(set(request["response_format"]["json_schema"]["schema"]["properties"]),
                                     {"case_id", "documents"})
            self.assertEqual(client.prepare(mode="hybrid"),
                             client.prepare(mode="hybrid", case_id="PM01-03"))
            self.assertEqual(client.prepare(json_schema=True),
                             client.prepare(json_schema=True, case_id="PM01-03"))

    def test_unknown_case_blocks_before_secret_transport_or_output(self):
        with patch.object(client.os.environ, "get", side_effect=AssertionError("No secreto")):
            with self.assertRaisesRegex(ValueError, "Caso sintético desconocido"):
                self.execute_mock(mode="hybrid", case_id="PM01-99")
        self.opener.open.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_selected_case_drives_mock_http_metadata_and_baseline_without_oracle(self):
        for case_id, difference in (("PM01-05", None), ("PM01-02", 0)):
            with self.subTest(case_id=case_id):
                self.destination = Path(self.temp.name) / case_id
                self.opener.open.reset_mock()
                extraction = {"case_id": case_id, "documents": experiment.load_verified_extraction(case_id)}
                self.hybrid_response(extraction)
                with patch.object(experiment, "load_oracles", side_effect=AssertionError("No oráculo")):
                    result = self.execute_mock(mode="hybrid", case_id=case_id)
                self.opener.open.assert_called_once()
                sent = json.loads(self.opener.open.call_args.args[0].data)
                self.assertEqual(json.loads(sent["messages"][1]["content"])["case"]["case_id"], case_id)
                self.assertEqual(result["case_id"], case_id)
                self.assertEqual(result["status"], "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED")
                validation = json.loads((self.destination / "local_validation.json").read_text())
                self.assertEqual(validation["operational_result"]["quantity_difference"], difference)
                self.assertFalse(validation["operational_result"]["automatic_closure_allowed"])

    def test_case_cli_dry_run_remains_offline_and_execution_forwards_selection(self):
        original_get = client.os.environ.get

        def no_secret(name, *args):
            if name == client.SECRET_NAME:
                raise AssertionError("No secreto en dry-run")
            return original_get(name, *args)

        output = StringIO()
        with patch("sys.argv", ["proof_meta_first_call.py", "--mode", "hybrid", "--case-id", "PM01-05"]), \
                patch.object(client.os.environ, "get", side_effect=no_secret), \
                patch.object(client.urllib.request, "build_opener") as build, redirect_stdout(output):
            client.main()
        self.assertEqual(json.loads(output.getvalue())["case_id"], "PM01-05")
        build.assert_not_called()
        output = StringIO()
        with patch("sys.argv", ["proof_meta_first_call.py", "--mode", "hybrid", "--case-id", "PM01-02",
                                "--execute", "--billing-confirmed", "--protocol-confirmed", "--json-schema"]), \
                patch.object(client, "execute", return_value={"status": "SIMULATED"}) as execute, redirect_stdout(output):
            client.main()
        self.assertEqual(execute.call_args.kwargs["case_id"], "PM01-02")
        self.assertEqual(execute.call_args.kwargs["mode"], "hybrid")
        self.assertTrue(execute.call_args.kwargs["billing_confirmed"])
        self.assertTrue(execute.call_args.kwargs["protocol_confirmed"])


if __name__ == "__main__":
    unittest.main()
