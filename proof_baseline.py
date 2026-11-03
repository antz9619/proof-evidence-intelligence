"""Baseline PROOF para evidencia estructurada sintética; solo biblioteca estándar."""

import argparse
from datetime import datetime
import json
from pathlib import Path


def _count(value, field):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{field}: se requiere entero no negativo o null")
    return value


def _time(value):
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("Fecha ISO-8601 inválida") from None
    if result.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria")
    return result


def evaluate(scenario):
    """No interpreta texto libre, autentica documentos ni ejecuta acciones.

    Admite un envío, una fuente por autoridad y una observación por fuente.
    La pertenencia de las fuentes al envío es una precondición del input.
    No consulta expected_checks, prohibited_assertions ni otros oráculos.
    """
    if scenario.get("synthetic") is not True:
        raise ValueError("Solo se admiten escenarios marcados synthetic: true")
    as_of = _time(scenario["as_of"])
    shipment = scenario["shipment"]
    expected = _count(shipment.get("expected_packages"), "shipment.expected_packages")
    sources = scenario.get("sources", [])
    ids = [s["id"] for s in sources]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Los identificadores de fuente deben ser únicos y no vacíos")

    evidence = {}
    facts, uncertainties, discrepancies, contradictions = [], [], [], []
    for index, source in enumerate(sources):
        role = source.get("authority")
        if role not in {"carrier_status", "document_count"}:
            raise ValueError(f"Autoridad no soportada: {role}")
        if role in evidence:
            raise ValueError("Varias fuentes de la misma autoridad: reconciliación no soportada")
        observations = source.get("observations", [])
        if len(observations) > 1:
            raise ValueError("Varias observaciones por fuente: seleccionar evidencia explícitamente")
        observation = observations[0] if observations else {}
        if observation and _time(observation.get("at")) > as_of:
            raise ValueError("Una observación es posterior al corte del escenario")
        evidence[role] = (observation, source["id"], f"/sources/{index}/observations/0")

    tracking, tracking_id, tracking_path = evidence.get("carrier_status", ({}, None, None))
    pod, pod_id, pod_path = evidence.get("document_count", ({}, None, None))

    def fact(code, statement, source_ids, paths):
        facts.append({"code": code, "statement": statement, "status": "CONFIRMED",
                      "source_ids": source_ids, "evidence_paths": paths})

    def finding(code, statement, refs, paths, status):
        return {"code": code, "statement": statement, "status": status,
                "source_ids": refs, "evidence_paths": paths}

    if expected is not None:
        fact("EXPECTED_QUANTITY", f"El escenario requiere {expected} bultos.",
             [], ["/shipment/expected_packages"])
    else:
        uncertainties.append("Cantidad esperada del envío desconocida.")

    status = tracking.get("status")
    reported = None
    if status is not None:
        if not isinstance(status, str):
            raise ValueError("tracking.status debe ser texto")
        fact("TRACKING_STATUS", f"El tracking informa {status}.",
             [tracking_id], [tracking_path + "/status"])
        if status in {"ENTREGADO", "ENTREGA_COMPLETA"}:
            reported = True
        elif status == "NO_ENTREGADO":
            reported = False
        else:
            uncertainties.append("Semántica del estado de tracking no soportada.")
    else:
        uncertainties.append("No hay estado de tracking estructurado.")

    complete = tracking.get("delivery_complete")
    if complete is not None and type(complete) is not bool:
        raise ValueError("tracking.delivery_complete debe ser booleano o null")
    received = _count(pod.get("received_packages"), "pod.received_packages")
    pod_expected = _count(pod.get("expected_packages"), "pod.expected_packages")
    if received is not None:
        fact("DOCUMENTED_QUANTITY", f"El comprobante registra {received} bultos recibidos.",
             [pod_id], [pod_path + "/received_packages"])
    else:
        uncertainties.append("Cantidad recibida no disponible como dato estructurado.")

    signature = pod.get("signature_present")
    identity = pod.get("signature_identity_verified")
    for field, value in (("signature_present", signature), ("signature_identity_verified", identity)):
        if value is not None:
            if type(value) is not bool:
                raise ValueError(f"pod.{field} debe ser booleano o null")
            fact(field.upper(), f"El comprobante registra {field}={value}.",
                 [pod_id], [pod_path + "/" + field])
    if signature is not True or identity is not True:
        uncertainties.append("La evidencia no establece firma presente con identidad verificada.")

    difference = expected - received if expected is not None and received is not None else None
    if difference is not None and difference != 0:
        discrepancies.append(finding(
            "QUANTITY_MISMATCH", f"Diferencia esperado menos documentado: {difference} bultos.",
            [pod_id], ["/shipment/expected_packages", pod_path + "/received_packages"], "CONFIRMED"))
        uncertainties.append("El destino físico de la diferencia documental no está determinado.")
        if reported is True:
            discrepancies.append(finding(
                "REPORTED_DELIVERY_WITH_QUANTITY_MISMATCH",
                "La entrega informada no establece recepción conforme de la cantidad esperada.",
                [tracking_id, pod_id], [tracking_path + "/status", pod_path + "/received_packages"],
                "INFERRED"))

    if expected is not None and pod_expected is not None and expected != pod_expected:
        contradictions.append(finding(
            "EXPECTED_QUANTITY_CONFLICT", "Envío y comprobante indican cantidades esperadas diferentes.",
            [pod_id], ["/shipment/expected_packages", pod_path + "/expected_packages"], "CONTRADICTORY"))
    explicit_complete = complete is True or status == "ENTREGA_COMPLETA"
    if explicit_complete and difference is not None and difference > 0:
        claim = "/delivery_complete" if complete is True else "/status"
        contradictions.append(finding(
            "COMPLETE_DELIVERY_VS_PARTIAL_DOCUMENT", "Tracking afirma entrega completa; el comprobante registra menos bultos.",
            [tracking_id, pod_id], [tracking_path + claim, pod_path + "/received_packages"], "CONTRADICTORY"))
    if signature is False and identity is True:
        contradictions.append(finding(
            "SIGNATURE_CONFLICT", "El comprobante declara identidad de firma verificada sin firma presente.",
            [pod_id], [pod_path + "/signature_present", pod_path + "/signature_identity_verified"], "CONTRADICTORY"))
    if (complete is False and status == "ENTREGA_COMPLETA") or (complete is True and reported is False):
        contradictions.append(finding(
            "TRACKING_CONFLICT", "Los campos de tracking discrepan sobre entrega completa.",
            [tracking_id], [tracking_path + "/status", tracking_path + "/delivery_complete"], "CONTRADICTORY"))

    supported = (difference == 0 and expected is not None and expected > 0
                 and reported is True and complete is not False
                 and signature is True and identity is True and not contradictions)
    conformity = "CONTRADICTORY" if contradictions else ("CONFIRMED" if supported else "UNKNOWN")
    if expected == 0:
        uncertainties.append("Un envío sin bultos esperados no establece una entrega conforme.")
    if complete is False:
        uncertainties.append("Tracking declara entrega completa=false.")
    uncertainties.append("No hay verificación física independiente; se evalúan declaraciones del input sintético.")

    def action(code, text, verifications):
        return {"code": code, "action": text,
                "preconditions": ["Solo propuesta; sin ejecución externa ni cierre automático."],
                "required_verifications": verifications}

    if supported:
        actions = [action("REVIEW_DOCUMENTARY_CLOSURE", "Someter la conformidad documental a revisión humana.",
                          ["Autenticidad, pertenencia al envío y vigencia de las evidencias."])]
    else:
        actions = [action("KEEP_CLOSURE_PENDING", "Mantener pendiente el cierre conforme.",
                          ["Resolver diferencias, contradicciones y evidencia faltante."]),
                   action("REQUEST_ADDITIONAL_EVIDENCE", "Proponer solicitar evidencia adicional de recepción.",
                          ["Cantidad, pertenencia al envío y explicación de cualquier diferencia documental."])]
        if signature is not True or identity is not True:
            actions.append(action("VERIFY_SIGNER_IDENTITY", "Proponer verificar firma e identidad.",
                                  ["Firma e identidad verificadas por una fuente autorizada."]))

    return {"scenario_id": scenario["id"], "as_of": scenario["as_of"], "evaluation": "DETERMINISTIC_BASELINE",
            "facts": facts, "uncertainties": uncertainties, "discrepancies": discrepancies,
            "contradictions": contradictions,
            "assessment": {"delivery_reported": reported, "quantity_difference": difference,
                           "documentary_conformity": conformity, "physical_delivery_verified": False,
                           "automatic_closure_allowed": False},
            "proposed_actions": actions,
            "must_not_assert": ["Entrega física verificada por este baseline.",
                                "Pérdida o daño deducidos de una diferencia documental.",
                                "Identidad autenticada por este baseline."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", type=Path,
                        default=Path(__file__).parent / "scenarios" / "PROOF-01.json")
    args = parser.parse_args()
    try:
        result = evaluate(json.loads(args.scenario.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Entrada no soportada: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
