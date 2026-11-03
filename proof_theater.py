"""Public synthetic projections → offline replay → existing guard and baseline. No HTTP."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
import uuid

import proof_hybrid
import proof_meta_experiment as experiment


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "demo/decision_theater.json"
DATA_SHA256 = "240290f05b563745f7955936c702664adbc5014888297fe379f2975af6b257a3"
CASE_IDS = ("PM01-03", "PM01-05", "PM01-02", "PM01-07")


def digest(value):
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def catalog():
    """Never reads private history, environment, expected.json or a stored decision."""
    raw = DATA.read_bytes()
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError("La proyección pública no coincide con su versión revisada")
    bundle = experiment.strict_json(raw.decode("utf-8"))
    if set(bundle) != {"format", "records"} or bundle["format"] != "PROOF_PUBLIC_REPLAY_01":
        raise ValueError("Proyección pública desconocida")
    if tuple(record["id"] for record in bundle["records"]) != CASE_IDS:
        raise ValueError("Catálogo público inválido")
    for record in bundle["records"]:
        if set(record) != {"id", "title", "short_title", "input", "extraction", "origin"}:
            raise ValueError("Campo público no permitido")
        record["input"] = experiment.public_case(record["input"])
        experiment._validate(record["extraction"], experiment.extraction_schema())
    return deepcopy(bundle["records"])


def _audit(case, extraction, computed, excluded):
    """Read-only explanation using the same validators, never a second engine run.

    Stops at the same first failure as convert(). A later field is UNREACHED,
    not silently accepted. Source-set rejection precedes the status guard.
    """
    originals = {doc["source_id"]: doc for doc in case["documents"]}
    rows = [{"id": doc["source_id"] + ":" + field, "source_id": doc["source_id"],
             "field": field, "value": doc[field]["value"], "quote": doc[field]["quote"],
             "validation": "UNREACHED", "used_by_engine": False}
            for doc in extraction["documents"] for field in experiment.FIELDS]
    by_id = {row["id"]: row for row in rows}
    checks = [{"id": name, "status": "NOT_RUN", "detail": "No alcanzado."}
              for name in ("schema", "sources", "citations", "status_guard", "shipment", "baseline")]
    check = {entry["id"]: entry for entry in checks}

    def mark(name, status, detail):
        check[name].update(status=status, detail=detail)

    mark("schema", "PASS", "Tipos, cantidades no negativas, campos requeridos y null verificados.")
    ids = [doc["source_id"] for doc in extraction["documents"]]
    missing = sorted(set(originals) - set(ids))
    if extraction["case_id"] != case["case_id"] or len(ids) != len(set(ids)) or set(ids) != set(originals):
        mark("sources", "FAIL", "Cada fuente debe estar presente una vez, sin fuentes inventadas.")
        return rows, checks, {"code": "SOURCE_SET_MISMATCH", "source_id": missing[0] if missing else None,
                              "field": None, "value": None, "quote": None, "missing_sources": missing,
                              "message": "Falta el comprobante pod en la extracción." if missing == ["pod"] else "Conjunto de fuentes incompatible."}
    mark("sources", "PASS", "Todas las fuentes originales están presentes, sin duplicados.")
    status_checked = False
    for doc in extraction["documents"]:
        source = originals[doc["source_id"]]
        relevant = {"shipment_id", "status", "delivery_complete"} if source["authority"] == "carrier_status" else {
            "shipment_id", "expected_packages", "received_packages", "signature_present", "signature_identity_verified"}
        for field in experiment.FIELDS:
            row = by_id[doc["source_id"] + ":" + field]
            try:
                experiment._check_citation(field, doc[field], source)
                if field not in relevant and doc[field]["value"] is not None:
                    raise ValueError("Campo atribuido a una autoridad incorrecta")
            except ValueError as error:
                row["validation"] = "FAIL"
                critical = field in {"status", "delivery_complete"}
                mark("status_guard" if critical else "citations", "FAIL", str(error))
                if critical:
                    mark("citations", "LITERAL_ONLY", "La cita existe, pero no respalda el significado propuesto.")
                return rows, checks, {"code": "UNSUPPORTED_STATUS" if critical else "INVALID_CITATION",
                                      "source_id": doc["source_id"], "field": field,
                                      "value": doc[field]["value"], "quote": doc[field]["quote"],
                                      "message": str(error), "missing_sources": []}
            row["validation"] = "UNKNOWN" if doc[field]["value"] is None else "PASS"
            if field in {"status", "delivery_complete"} and doc[field]["value"] is not None:
                status_checked = True
    mark("citations", "PASS", "Citas propias, autoridad, cantidades y pertenencia declarada verificadas.")
    mark("status_guard", "PASS" if status_checked else "ABSTAIN", "Estado explícito respaldado; no se infiere completitud independiente." if status_checked else "Sin estado conocido que confirmar.")
    excluded_ids = {entry["source_id"] for entry in excluded}
    mark("shipment", "EXCLUDED" if excluded_ids else "PASS",
         "pod pertenece a otro envío y queda fuera del motor." if excluded_ids else "Las fuentes usadas pertenecen al envío investigado.")
    for row in rows:
        row["used_by_engine"] = computed and row["source_id"] not in excluded_ids and row["validation"] == "PASS"
        if row["source_id"] in excluded_ids:
            row["validation"] = "EXCLUDED"
    mark("baseline", "PASS" if computed else "NOT_RUN", "Calculado desde hechos validados." if computed else "No se utilizaron campos rechazados.")
    return rows, checks, None


def evaluate(case_id):
    record = next((item for item in catalog() if item["id"] == case_id), None)
    if record is None:
        raise ValueError("Caso no disponible")
    start = time.perf_counter()
    result = proof_hybrid.run(record["input"], record["extraction"])
    computed = result["engine_status"] == "COMPUTED_BY_BASELINE"
    excluded = result.get("excluded_sources", [])
    rows, checks, reason = _audit(record["input"], record["extraction"], computed, excluded)
    if not computed and reason is None:
        reason = {"code": "VALIDATION_REJECTED", "source_id": None, "field": None, "value": None,
                  "quote": None, "message": "La extracción requiere revisión.", "missing_sources": []}
    operation = result["operational_result"]
    quantities = None
    if computed:
        source = next((source for source in result["baseline_input"]["sources"] if source["authority"] == "document_count"), None)
        quantities = {"expected": result["baseline_input"]["shipment"]["expected_packages"],
                      "documented": source["observations"][0].get("received_packages") if source else None,
                      "difference": operation["quantity_difference"]}
    outcome = "blocked" if not computed else "excluded" if excluded else "confirmed" if operation["documentary_conformity"] == "CONFIRMED" else "review"
    human = (["Revisar la extracción del estado contra su declaración literal.",
              "Volver a aportar una extracción respaldada antes de calcular."] if reason and reason["code"] == "UNSUPPORTED_STATUS" else
             ["Incluir el comprobante omitido sin inventar sus campos ilegibles.",
              "Revisar también el significado del estado antes de una nueva evaluación."] if reason else
             ["Aportar un comprobante correspondiente a " + record["input"]["shipment"]["id"] + ".",
              "Verificar cantidad e identidad en evidencia del envío investigado."] if excluded else
             ["Revisar autenticidad y conformidad documental antes de cualquier cierre."])
    human.append("La existencia de una entrega física requiere verificación independiente.")
    fingerprint = hashlib.sha256(b"".join((ROOT / name).read_bytes() for name in (
        "proof_baseline.py", "proof_hybrid.py", "proof_meta_experiment.py", "proof_theater.py"))).hexdigest()
    decision = {"outcome": outcome, "baseline_status": result["engine_status"], "quantities": quantities,
                "operational_result": operation, "excluded_sources": excluded, "reason": reason,
                "human_review": human,
                "contradictions": result["baseline_result"]["contradictions"] if computed else None}
    identity = {"input_sha256": digest(record["input"]), "extraction_sha256": digest(record["extraction"]),
                "validator_sha256": fingerprint, "decision_sha256": digest(decision)}
    execution = {"id": uuid.uuid4().hex[:12], "at": datetime.now(timezone.utc).isoformat(),
                 "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
    passport = {"format": "PROOF_DECISION_PASSPORT_01", "decision_id": "proof-" + digest(identity)[:20],
                "scope": "OFFLINE_REPLAY_SYNTHETIC_DOCUMENTS", "new_meta_inference": False,
                "case_id": case_id, "shipment_id": record["input"]["shipment"]["id"],
                "origin": record["origin"], "sources": record["input"]["documents"],
                "extraction": record["extraction"], "validation_checks": checks,
                "lineage": rows, "decision": decision, "reproducibility": identity,
                "execution": execution, "external_actions_executed": False,
                "limitation": "Un hash permite comprobar integridad, no autentica el documento ni demuestra una entrega física."}
    return {"case_id": case_id, "record": record, "decision": decision,
            "lineage": rows, "checks": checks, "passport": passport,
            "execution": execution, "live_inference_enabled": False,
            "META_MODEL_EVALUATION": "NOT_RUN_OFFLINE_REPLAY_ONLY"}
