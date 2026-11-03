"""Una única inferencia futura, desactivada por defecto; requiere autorización del propietario."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import ssl
import time
import urllib.error
import urllib.request

import proof_hybrid
from proof_meta_experiment import (MAX_OUTPUT_TOKENS, build_request, load_cases, parse_response,
                                   transport_extraction_schema, validate_response)


ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://api.meta.ai/v1/chat/completions"
CASE_ID = "PM01-03"
SECRET_NAME = "META_MODEL_API_KEY"
MAX_REQUEST_BYTES = 32768
MAX_RESPONSE_BYTES = 262144
TIMEOUT_SECONDS = 30


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def deadline(seconds):
    """Límite total de pared para la única operación de red, en el CLI Linux."""
    if not hasattr(signal, "SIGALRM"):
        raise ValueError("La ejecución real requiere SIGALRM (entorno cloud Linux)")

    def expired(_signum, _frame):
        raise TimeoutError("Límite de tiempo agotado")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def prepare(*, json_schema=False, mode="legacy", case_id=CASE_ID):
    if mode not in {"legacy", "hybrid"}:
        raise ValueError("Modo de cliente no soportado; no se envía")
    case = next((case for case in load_cases() if case["case_id"] == case_id), None)
    if case is None:
        raise ValueError("Caso sintético desconocido; no se envía")
    if mode == "hybrid":
        request = proof_hybrid.build_extraction_request(case)
        native = request.get("response_format", {})
        contract = native.get("json_schema", {})
        if (native.get("type") != "json_schema" or contract.get("strict") is not True
                or contract.get("schema") != transport_extraction_schema()):
            raise ValueError("El modo híbrido requiere el contrato nativo estricto de extracción")
    else:
        request = build_request(case, json_schema=json_schema)
    request["stream"] = False
    body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("Payload supera el límite de bytes; no se envía")
    if request.get("max_completion_tokens") != MAX_OUTPUT_TOKENS:
        raise ValueError("El presupuesto del request no coincide con el límite autorizado del cliente")
    return case, request, body


def _save(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _redact(text, secret):
    return text.replace(secret, "[REDACTED]").replace(json.dumps(secret)[1:-1], "[REDACTED]")


def _usage(envelope):
    usage = envelope.get("usage") if isinstance(envelope, dict) else None
    if not isinstance(usage, dict):
        return None
    result = {key: value for key, value in usage.items()
              if key in {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
              and type(value) is int and value >= 0}
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
        if type(reasoning) is int and reasoning >= 0:
            result["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return result


def _record_hybrid_validation(case, extraction, destination, metadata):
    validated = proof_hybrid.run(case, extraction)
    # run() también se usa offline: registrar explícitamente el contexto HTTP de esta ejecución.
    validated.update(evaluation_mode="HYBRID_HTTP_RESPONSE", response_origin="NEW_HTTP_RESPONSE",
                     META_MODEL_EVALUATION=metadata["META_MODEL_EVALUATION"])
    metadata["response_origin"] = "NEW_HTTP_RESPONSE"
    metadata["extraction_validation"] = validated["extraction_validation"]
    metadata["deterministic_calculation"] = validated["engine_status"]
    metadata["semantic_review"] = "PENDING"
    metadata["operational_consistency"] = (
        "NOT_SCORED_AGAINST_ORACLE" if validated["engine_status"] == "COMPUTED_BY_BASELINE" else "NOT_RUN")
    _save(destination / "local_validation.json", validated)
    return validated


def execute(output_dir, *, billing_confirmed=False, protocol_confirmed=False, json_schema=False,
            mode="legacy", case_id=CASE_ID):
    """Llamar solo después de autorización expresa. Una llamada a opener.open, sin bucles."""
    if not billing_confirmed or not protocol_confirmed:
        raise ValueError("Falta confirmar pago/autorización o contrato oficial del proveedor")
    if not hasattr(signal, "SIGALRM"):
        raise ValueError("La ejecución real requiere el entorno cloud Linux")
    case, request, body = prepare(json_schema=json_schema, mode=mode, case_id=case_id)
    destination = Path(output_dir)
    destination = (ROOT / destination).resolve() if not destination.is_absolute() else destination.resolve()
    if not destination.is_relative_to(ROOT) or destination.relative_to(ROOT).parts[:1] != ("artifacts",):
        raise ValueError("Los resultados deben quedar dentro de artifacts/ del repositorio")
    secret = os.environ.get(SECRET_NAME)
    if not secret:
        raise ValueError("Falta el secreto META_MODEL_API_KEY en el entorno; no se envió ninguna solicitud")
    if any(ord(char) < 32 or ord(char) == 127 for char in secret):
        raise ValueError("El secreto no es válido para un header HTTP")
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "request.json").open("xb") as handle:
        handle.write(body)
    metadata = {"case_id": case["case_id"], "model_requested": request["model"], "endpoint": ENDPOINT,
                "client_mode": mode,
                "protocol_verification": "OPERATOR_ATTESTED_NOT_VERIFIED_BY_CODE",
                "requests_attempted": 0, "max_requests": 1, "automatic_retries": 0,
                "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
                "max_input_bytes": MAX_REQUEST_BYTES, "request_bytes": len(body),
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "http_status": None, "usage": None, "elapsed_seconds": None,
                "finish_reason": None, "response_completeness": "UNKNOWN",
                "reasoning_tokens": None, "visible_output_tokens": None,
                "visible_output_tokens_basis": "UNAVAILABLE",
                "format_validation": "NOT_RUN", "operational_consistency": "NOT_RUN",
                "cost": None, "cost_status": "NOT_CALCULATED_PRICES_UNVERIFIED",
                "META_MODEL_EVALUATION": "NOT_EVALUATED", "END_TO_END_DEMO": "NOT_RUN"}
    if mode == "hybrid":
        metadata.update(response_contract="EXTRACTION_ONLY", response_origin="NEW_HTTP_ATTEMPT",
                        extraction_validation="NOT_RUN", deterministic_calculation="NOT_RUN",
                        semantic_review="PENDING", extraction_accuracy="NOT_EVALUATED_WITH_ORACLE")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    http_request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "Authorization": "Bearer " + secret})
    started = time.monotonic()
    try:
        metadata["requests_attempted"] = 1
        _save(destination / "attempt.json", metadata)
        with deadline(TIMEOUT_SECONDS):
            # Único punto de envío. Redirecciones, reintentos y fallback están deshabilitados.
            try:
                with opener.open(http_request, timeout=TIMEOUT_SECONDS) as response:
                    metadata["http_status"] = response.status
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
            except urllib.error.HTTPError as error:
                metadata["http_status"] = error.code
                error_raw = error.read(MAX_RESPONSE_BYTES + 1)
                _save(destination / "http_error.json", {
                    "http_status": error.code,
                    "body": _redact(error_raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace"), secret),
                    "truncated": len(error_raw) > MAX_RESPONSE_BYTES})
                raise
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Respuesta supera el límite de bytes")
        text = _redact(raw.decode("utf-8"), secret)
        with (destination / "response.json").open("x", encoding="utf-8") as handle:
            handle.write(text)
        envelope = json.loads(text)
        metadata["usage"] = _usage(envelope)
        metadata["usage_status"] = "REPORTED" if metadata["usage"] else "UNKNOWN_IF_NOT_REPORTED_POSSIBLE_CHARGE"
        usage = metadata["usage"] or {}
        reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens")
        metadata["reasoning_tokens"] = reasoning
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if reasoning is not None and completion is not None and completion >= reasoning:
            metadata["visible_output_tokens"] = completion - reasoning
            metadata["visible_output_tokens_basis"] = "DERIVED_COMPLETION_MINUS_REASONING"
        if isinstance(envelope, dict):
            metadata["model_reported"] = str(envelope.get("model", ""))[:200]
            metadata["response_id"] = str(envelope.get("id", ""))[:200]
            choices = envelope.get("choices")
            if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
                finish = choices[0].get("finish_reason")
                metadata["finish_reason"] = finish[:200] if isinstance(finish, str) else None
                if finish == "length":
                    metadata["response_completeness"] = "INCOMPLETE_LENGTH"
                    metadata["META_MODEL_EVALUATION"] = "NOT_EVALUABLE_INCOMPLETE_RESPONSE"
                elif finish == "stop":
                    metadata["response_completeness"] = "COMPLETE_STOP"
        try:
            parsed = parse_response(text, extraction_only=True) if mode == "hybrid" else parse_response(text)
        except (ValueError, KeyError, TypeError):
            metadata["format_validation"] = "FAIL"
            if mode == "hybrid":
                if metadata["finish_reason"] != "length":
                    metadata["META_MODEL_EVALUATION"] = "NOT_EVALUABLE_INVALID_EXTRACTION"
                _record_hybrid_validation(case, None, destination, metadata)
            raise
        metadata["format_validation"] = "PASS"
        if mode == "hybrid":
            validated = _record_hybrid_validation(case, parsed, destination, metadata)
            if validated["extraction_validation"] != "PASS_LOCAL_CHECKS_ONLY":
                raise ValueError("Extracción inválida; se requiere revisión sin cálculo operativo")
        else:
            validated = validate_response(case, parsed)
            _save(destination / "local_validation.json", validated)
            metadata["operational_consistency"] = "PASS" if validated["model_proposals_consistent"] else "FAIL"
            if not validated["model_proposals_consistent"]:
                raise ValueError("Propuesta incompatible con los campos extraídos")
        metadata["status"] = "RESPONSE_RECEIVED_AND_LOCALLY_VALIDATED"
    except Exception as error:
        # No imprimir str(error), headers ni cuerpo de errores: pueden incluir datos sensibles.
        metadata["status"] = "FAILED_NO_RETRY"
        metadata["error_type"] = type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            metadata["http_status"] = error.code
        metadata["usage_status"] = "REPORTED" if metadata["usage"] else "UNKNOWN_IF_NOT_REPORTED_POSSIBLE_CHARGE"
    finally:
        metadata["elapsed_seconds"] = round(time.monotonic() - started, 6)
        _save(destination / "metadata.json", metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("legacy", "hybrid"), default="legacy",
                        help="legacy preserva el experimento anterior; hybrid usa solo extracción y baseline")
    parser.add_argument("--case-id", default=CASE_ID,
                        help="Identificador de un caso sintético existente; por defecto PM01-03")
    parser.add_argument("--execute", action="store_true", help="Autoriza una sola solicitud; nunca se ejecuta por defecto")
    parser.add_argument("--billing-confirmed", action="store_true", help="Propietario verificó pago y autorizó consumo")
    parser.add_argument("--protocol-confirmed", action="store_true", help="Operador verificó endpoint, parámetros y schema en documentación oficial")
    parser.add_argument("--json-schema", action="store_true", help="Solo después de confirmar soporte nativo")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/proof-meta-01/first-call-01"))
    args = parser.parse_args()
    try:
        if args.execute:
            result = execute(args.output_dir, billing_confirmed=args.billing_confirmed,
                             protocol_confirmed=args.protocol_confirmed, json_schema=args.json_schema,
                             mode=args.mode, case_id=args.case_id)
        else:
            case, request, body = prepare(json_schema=args.json_schema, mode=args.mode, case_id=args.case_id)
            result = {"mode": "DRY_RUN_NO_HTTP", "META_MODEL_EVALUATION": "NOT_RUN", "endpoint_candidate": ENDPOINT,
                      "client_mode": args.mode, "case_id": case["case_id"],
                      "protocol_verified": False, "max_requests": 1, "automatic_retries": 0,
                      "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
                      "request_bytes": len(body), "request_sha256": hashlib.sha256(body).hexdigest(),
                      "request": request}
    except (ValueError, OSError, KeyError, StopIteration) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "FAILED_NO_RETRY":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
