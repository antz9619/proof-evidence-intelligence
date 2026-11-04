"""One-shot web transport. No SIGALRM, retry, redirect, oracle or operational engine."""
import http.client
import os
import ssl
import time
from urllib.parse import urlsplit

# Same certified CLI bounds; intentionally no CLI/signal import on the web path.
ENDPOINT = 'https://api.meta.ai/v1/chat/completions'
MAX_REQUEST_BYTES = 32768
MAX_RESPONSE_BYTES = 262144

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
TOTAL_TIMEOUT = 30


class TransportFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def send_once(body, api_key, *, factory=None, proxy=None):
    """One POST, bounded reads; timeout does NOT cancel provider processing.

    Uses the configured HTTPS proxy/CA trust. OS DNS resolution is outside the
    socket timeout guarantee; no wall-clock/SIGALRM claim is made for DNS.
    factory is an injected connection seam for offline tests, never HTTP input.
    """
    if not isinstance(body, bytes) or len(body) > MAX_REQUEST_BYTES:
        raise TransportFailure('REQUEST_TOO_LARGE')
    if len(api_key) < 16 or any(ord(c) < 32 or ord(c) == 127 for c in api_key):
        raise TransportFailure('INVALID_API_KEY')
    endpoint = urlsplit(ENDPOINT)
    proxy = os.environ.get('HTTPS_PROXY', '') if proxy is None else proxy
    target = urlsplit(proxy) if proxy else None
    if target and (target.scheme != 'http' or not target.hostname or target.username or target.password):
        raise TransportFailure('UNSUPPORTED_PROXY')
    cls = factory or http.client.HTTPSConnection
    host, port = (target.hostname, target.port or 80) if target else (endpoint.hostname, 443)
    connection = cls(host, port, timeout=CONNECT_TIMEOUT, context=ssl.create_default_context())
    if target:
        connection.set_tunnel(endpoint.hostname, 443)
    started = time.monotonic()
    try:
        connection.connect()
        connection.auto_open = 0  # Never reconnect/retry a possibly billed request.
        remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
        if remaining <= 0:
            raise TransportFailure('TIMEOUT_POSSIBLY_BILLABLE')
        sock = connection.sock
        sock.settimeout(min(READ_TIMEOUT, remaining))
        connection.request('POST', endpoint.path, body=body, headers={
            'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json',
            'Accept': 'application/json', 'Connection': 'close'})
        remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
        if remaining <= 0:
            raise TransportFailure('TIMEOUT_POSSIBLY_BILLABLE')
        sock.settimeout(min(READ_TIMEOUT, remaining))
        response = connection.getresponse()
        chunks, size = [], 0
        while True:
            if response.isclosed():
                break
            remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                raise TransportFailure('TIMEOUT_POSSIBLY_BILLABLE')
            sock.settimeout(min(READ_TIMEOUT, remaining))
            part = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - size))
            if not part:
                break
            chunks.append(part)
            size += len(part)
            if size > MAX_RESPONSE_BYTES:
                raise TransportFailure('RESPONSE_TOO_LARGE')
        return response.status, b''.join(chunks)
    except (TimeoutError, OSError, http.client.HTTPException) as error:
        raise TransportFailure('TIMEOUT_POSSIBLY_BILLABLE' if isinstance(error, TimeoutError)
                               else 'TRANSPORT_UNCERTAIN') from None
    finally:
        connection.close()
