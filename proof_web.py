"""PROOF Visual MVP: modos local/Render explícitos, sin inferencia ni oráculos."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

import proof_hybrid
import proof_meta_experiment as experiment
import proof_theater


ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "artifacts/proof-meta-01/hybrid-live-01/response.json"
HISTORY_SHA256 = "43b7fdcc7af7eb32fa1b994594dffe1eb8b2e5f2e2d07d6b06c67051661020dd"
CASES = {
    "A": ("PM01-03", "Evidencia válida", "La extracción es válida. La entrega conforme sigue pendiente."),
    "B": ("PM01-03", "Una interpretación que no pasa", "ENTREGADO no significa ENTREGA_COMPLETA."),
    "C": ("PM01-05", "Lo que todavía no sabemos", "Sin cantidad legible, desconocido no significa cero."),
}
ASSETS = {"/proof-newsreader.woff": ("proof-newsreader.woff", "font/woff"),
          "/proof-manrope.woff": ("proof-manrope.woff", "font/woff"),
          "/": ("theater.html", "text/html; charset=utf-8"),
          "/classic": ("index.html", "text/html; charset=utf-8"),
          "/theater.css": ("theater.css", "text/css; charset=utf-8"),
          "/theater.js": ("theater.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/i18n-catalogs.js": ("i18n-catalogs.js", "text/javascript; charset=utf-8"),
          "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
          "/i18n.css": ("i18n.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


def safe_historical_extraction(case, annotated):
    """Solo una proyección del registro sintético conocido; nunca servir artifacts/."""
    path = HISTORY_PATH
    if path is None or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        return None
    try:
        if path.stat().st_size > 262144:
            return None
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != HISTORY_SHA256:
            return None
        extracted = experiment.parse_response(raw.decode("utf-8"), extraction_only=True)
        if extracted["case_id"] != case["case_id"]:
            return None
        sources = {d["source_id"]: d for d in case["documents"]}
        reference = {d["source_id"]: d for d in annotated["documents"]}
        ids = [d["source_id"] for d in extracted["documents"]]
        if len(ids) != len(set(ids)) or set(ids) != set(sources):
            return None
        for doc in extracted["documents"]:
            for field in experiment.FIELDS:
                item = doc[field]
                expected = reference[doc["source_id"]][field]["value"]
                if doc["source_id"] == "tracking" and field == "status":
                    expected = "ENTREGA_COMPLETA"  # Patrón histórico defectuoso, sin corregirlo.
                if type(item["value"]) is not type(expected) or item["value"] != expected:
                    return None
                if item["value"] is None:
                    if item["quote"] is not None:
                        return None
                elif not item["quote"] or item["quote"] not in sources[doc["source_id"]]["text"]:
                    return None
        return deepcopy(extracted)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load_demo(case_id, *, historical=True):
    input_id, title, summary = CASES[case_id]
    case = experiment.public_case(next(c for c in experiment.load_cases() if c["case_id"] == input_id))
    extraction = {"case_id": input_id, "documents": experiment.load_verified_extraction(input_id)}
    origin = {"kind": "OFFLINE", "label": "DEMO OFFLINE",
              "detail": "Evidencia y extracción sintéticas previamente anotadas. Sin inferencia nueva."}
    if case_id == "B":
        recorded = safe_historical_extraction(case, extraction) if historical else None
        if recorded is not None:
            extraction = recorded
            origin = {"kind": "HISTORICAL", "label": "INFERENCIA HISTÓRICA REGISTRADA",
                      "detail": "Proyección sintética de hybrid-live-01. Su FAIL histórico permanece intacto. Esta evaluación es local."}
        else:
            extraction["documents"][0]["status"]["value"] = "ENTREGA_COMPLETA"
            origin["detail"] = "Reproducción sintética del patrón ENTREGADO → ENTREGA_COMPLETA. No es una salida real nueva de Meta."
    return {"id": case_id, "title": title, "summary": summary, "origin": origin,
            "input": case, "extraction": extraction}


def rejection_reason(case, extraction):
    """Recuperar el motivo del mismo validador de citas, sin volver a calcular."""
    originals = {d["source_id"]: d for d in case["documents"]}
    try:
        experiment._validate(extraction, experiment.extraction_schema())
        for doc in extraction["documents"]:
            for field in experiment.FIELDS:
                try:
                    experiment._check_citation(field, doc[field], originals[doc["source_id"]])
                except ValueError as error:
                    return {"source_id": doc["source_id"], "field": field,
                            "value": doc[field]["value"], "quote": doc[field]["quote"], "message": str(error)}
    except (ValueError, KeyError, TypeError):
        pass
    return {"source_id": None, "field": None, "message": "La evidencia no superó los controles; requiere revisión."}


def evaluate_demo(case_id, *, mode="local"):
    demo = load_demo(case_id, historical=mode == "local")
    started = time.perf_counter()
    result = proof_hybrid.run(demo["input"], demo["extraction"])
    computed = result["engine_status"] == "COMPUTED_BY_BASELINE"
    quantities, reason = None, None
    if computed:
        baseline_input = result["baseline_input"]
        document = next((s for s in baseline_input["sources"] if s["authority"] == "document_count"), None)
        received = document["observations"][0].get("received_packages") if document else None
        quantities = {"expected": baseline_input["shipment"]["expected_packages"], "documented": received,
                      "difference": result["operational_result"]["quantity_difference"]}
    else:
        reason = rejection_reason(demo["input"], demo["extraction"])
    outcome = "rejected" if not computed else "incomplete" if quantities["difference"] is None else "review"
    return {"case_id": case_id, "demo": demo, "outcome": outcome, "origin": demo["origin"],
            "quantities": quantities, "reason": reason, "evaluation": result,
            "execution": {"id": uuid.uuid4().hex[:8], "at": datetime.now(timezone.utc).isoformat(),
                          "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                          "baseline_executed": computed,
                          "scope": "PUBLIC_WEB_OFFLINE_NO_NEW_INFERENCE" if mode == "render" else "LOCAL_WEB_OFFLINE_NO_NEW_INFERENCE"},
            "META_MODEL_EVALUATION": "NOT_RUN_THIS_MISSION", "live_inference_enabled": False}


class ProofHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        if self.server.proof_mode == "render":
            self.connection.settimeout(10)

    def log_message(self, *_args):
        pass

    def _allowed_request(self):
        # No se usan Forwarded ni X-Forwarded-* para decidir host, origen o permisos.
        if len(self.headers.get_all("Host", [])) != 1 or len(self.headers.get_all("Origin", [])) > 1:
            self._json(403, {"error": "Host/Origin ambiguo."})
            return False
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if self.server.proof_mode == "local":
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host_allowed = host in allowed
            origins = {"http://" + item for item in allowed}
        else:
            hostname = host[:-4] if host.endswith(":443") else host
            host_allowed = hostname in self.server.allowed_hosts
            origins = {"https://" + hostname, "https://" + hostname + ":443"}
        if not host_allowed:
            self._json(403, {"error": "Host no autorizado."})
            return False
        if origin and origin not in origins:
            self._json(403, {"error": "Origen no permitido."})
            return False
        return True

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._allowed_request():
            return
        path = urlsplit(self.path).path
        if path in ASSETS:
            name, mime = ASSETS[path]
            self._send(200, (ROOT / "web" / name).read_bytes(), mime)
        elif path == "/api/cases":
            self._json(200, {"cases": [load_demo(key, historical=self.server.proof_mode == "local") for key in CASES],
                             "live_inference_enabled": False, "deployment_mode": self.server.proof_mode})
        elif path == "/api/theater/cases":
            try:
                self._json(200, {"cases": proof_theater.catalog(), "live_inference_enabled": False})
            except Exception:
                self._json(500, {"error": "No se pudo cargar la proyección pública verificada."})
        elif path == "/healthz":
            self._json(200, {"status": "ok", "mode": self.server.proof_mode, "live_inference_enabled": False})
        else:
            self._json(404, {"error": "Ruta no disponible."})

    def do_POST(self):
        if not self._allowed_request():
            return
        path = urlsplit(self.path).path
        if path not in {"/api/evaluate", "/api/theater/evaluate"}:
            self._json(404, {"error": "Ruta no disponible."})
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if (len(self.headers.get_all("Content-Length", [])) != 1 or size < 0 or size > 4096
                    or self.headers.get("Transfer-Encoding")):
                raise ValueError("Tamaño no permitido.")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Se requiere JSON.")
            payload = experiment.strict_json(self.rfile.read(size).decode("utf-8"))
            available = proof_theater.CASE_IDS if path == "/api/theater/evaluate" else CASES
            if type(payload) is not dict or set(payload) != {"case_id"} or payload["case_id"] not in available:
                raise ValueError("Caso no disponible.")
        except (ValueError, KeyError, TypeError, TimeoutError):
            self._json(400, {"error": "Solicitud inválida. Elegí un caso de demostración disponible."})
            return
        try:
            self._json(200, proof_theater.evaluate(payload["case_id"]) if path == "/api/theater/evaluate"
                       else evaluate_demo(payload["case_id"], mode=self.server.proof_mode))
        except Exception:
            self._json(500, {"error": "No se pudo completar la evaluación local. No se generó una decisión."})


def parse_allowed_hosts(value):
    """FQDN exactos; no esquemas, puertos, comodines ni IP/localhost implícitos."""
    if not isinstance(value, str) or not value:
        raise ValueError("PROOF_ALLOWED_HOSTS es obligatorio en modo render")
    hosts = frozenset(item.strip().lower() for item in value.split(","))
    pattern = r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if not all(re.fullmatch(pattern, host) for host in hosts):
        raise ValueError("PROOF_ALLOWED_HOSTS requiere nombres DNS exactos, sin puertos ni comodines")
    return hosts


def make_server(port=8765, *, mode="local", allowed_hosts=()):
    if mode not in {"local", "render"} or type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Modo o puerto de servidor inválido")
    if mode == "local" and allowed_hosts:
        raise ValueError("Los hosts públicos solo se configuran en modo render")
    hosts = parse_allowed_hosts(",".join(allowed_hosts)) if mode == "render" else frozenset()
    server = ThreadingHTTPServer(("0.0.0.0" if mode == "render" else "127.0.0.1", port), ProofHandler)
    server.proof_mode = mode
    server.allowed_hosts = hosts
    return server


def configured_server(*, mode="local", port=None, environ=None):
    if mode == "local":
        return make_server(8765 if port is None else port)
    if mode != "render" or port is not None:
        raise ValueError("En modo render se requiere PORT; no usar --port")
    config = os.environ if environ is None else environ
    if config.get("META_MODEL_API_KEY"):
        raise ValueError("Eliminar META_MODEL_API_KEY del servicio Render: la inferencia está deshabilitada")
    configured_port = config.get("PORT", "")
    if not re.fullmatch(r"[0-9]{1,5}", configured_port) or not 1 <= int(configured_port) <= 65535:
        raise ValueError("PORT es obligatorio y debe ser un entero entre 1 y 65535")
    hosts = parse_allowed_hosts(config.get("PROOF_ALLOWED_HOSTS", ""))
    return make_server(int(configured_port), mode="render", allowed_hosts=hosts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "render"), default="local")
    parser.add_argument("--port", type=int, help="Puerto local; en modo render se usa PORT del entorno")
    args = parser.parse_args()
    try:
        server = configured_server(mode=args.mode, port=args.port)
    except ValueError as error:
        parser.error(str(error))
    with server:
        location = f"http://127.0.0.1:{server.server_port}" if server.proof_mode == "local" else f"0.0.0.0:{server.server_port} (TLS en Render)"
        print(f"PROOF · {location} · modo {server.proof_mode} · demo offline sin inferencia", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
