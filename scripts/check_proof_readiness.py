"""Arranque LOCAL y RENDER simulado por loopback. No despliega ni usa Meta."""

import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TEST_HOST = "proof-readiness.example"


def check(mode):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    environment = {"LC_ALL": "C.UTF-8", "PORT": str(free_port), "PROOF_ALLOWED_HOSTS": TEST_HOST}
    command = [sys.executable, "-B", "proof_web.py"]
    if mode == "render":
        command += ["--mode", "render"]
    else:
        # Variables ambientales públicas inválidas no deben activar ni afectar LOCAL.
        command += ["--port", "0"]
        environment.update(PORT="invalid", PROOF_ALLOWED_HOSTS="*", RENDER="true",
                           META_MODEL_API_KEY="SYNTHETIC_NOT_A_REAL_KEY")
    process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        line = process.stdout.readline()
        pattern = r"0\.0\.0\.0:(\d+)" if mode == "render" else r"http://127\.0\.0\.1:(\d+)"
        match = re.search(pattern, line)
        assert match, "Falló el arranque de prueba; no hay despliegue"
        port = int(match.group(1))
        if mode == "render":
            assert port == free_port
        headers = {"Host": TEST_HOST, "Origin": "https://" + TEST_HOST} if mode == "render" else {}

        def request(method, path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            configured = dict(headers)
            body = json.dumps(payload).encode() if payload is not None else None
            if body:
                configured["Content-Type"] = "application/json"
            try:
                connection.request(method, path, body=body, headers=configured)
                response = connection.getresponse()
                assert response.status == 200
                return json.loads(response.read())
            finally:
                connection.close()

        health = request("GET", "/healthz")
        assert health["mode"] == mode and health["live_inference_enabled"] is False
        results = []
        for key in ("A", "B", "C"):
            data = request("POST", "/api/evaluate", {"case_id": key})
            assert data["live_inference_enabled"] is False
            if key == "A":
                assert data["quantities"] == {"expected": 10, "documented": 8, "difference": 2}
            elif key == "B":
                assert data["quantities"] is None and data["execution"]["baseline_executed"] is False
                if mode == "render":
                    assert data["origin"]["kind"] == "OFFLINE"
            else:
                assert data["quantities"]["documented"] is None and data["quantities"]["difference"] is None
            assert data["evaluation"]["operational_result"]["automatic_closure_allowed"] is False
            results.append({"case": key, "outcome": data["outcome"], "baseline_executed": data["execution"]["baseline_executed"]})
        return {"mode": mode, "startup": "PASS", "health": health, "cases": results,
                "transport": "LOOPBACK_HTTP_TEST_NOT_RENDER_DEPLOYMENT"}
    finally:
        process.terminate()
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/normandia-01/startup-checks.json")
    args = parser.parse_args()
    results = [check(mode) for mode in ("local", "render")]
    report = {"startup_checks": results, "RENDER_DEPLOYMENT": "NOT_RUN", "new_meta_calls": 0,
              "public_tls_or_dns_verified": False, "readiness": "PASS_LOCAL_AND_SIMULATED_PUBLIC_STARTUP"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
