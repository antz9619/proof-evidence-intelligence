"""Small Owner-only adapter integrated with the existing PROOF HTTP server."""
from urllib.parse import urlsplit
import proof_live
import proof_meta_experiment as experiment


def reject(handler, error):
    # Auth challenge is browser-native. Credential is never read by JavaScript.
    if error.status == 401:
        handler.send_response(401)
        handler.send_header('WWW-Authenticate', 'Basic realm="PROOF Owner LIVE", charset="UTF-8"')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Content-Length', '0')
        handler.end_headers()
    else:
        handler._json(error.status, {'error': error.code, 'baseline_status': 'NOT_RUN'})


def authorized(handler):
    service = getattr(handler.server, 'live_service', None)
    if service is None:
        handler._json(404, {'error': 'LIVE_NOT_ENABLED'})
        return None
    try:
        service.authorize(handler.headers)
    except proof_live.Rejected as error:
        reject(handler, error)
        return None
    return service


def get(handler, path):
    service = authorized(handler)
    if service is None:
        return
    if path == '/api/live/status':
        try:
            handler._json(200, service.status())
        except Exception:
            handler._json(503, {'error': 'LIVE_STATE_UNAVAILABLE'})
    else:
        raw = (handler.server.live_root / 'web/theater.html').read_text()
        panel = (handler.server.live_root / 'web/live-panel.html').read_text()
        raw = raw.replace('</head>', '<link rel="stylesheet" href="/proof-live.css"><script src="/proof-live.js" defer></script></head>')
        raw = raw.replace('<body>', '<body>' + panel)
        handler._send(200, raw.encode(), 'text/html; charset=utf-8')


def post(handler, path):
    service = authorized(handler)
    if service is None:
        return
    if urlsplit(handler.path).query:
        handler._json(400, {'error': 'LIVE_API_QUERY_NOT_ALLOWED'})
        return
    origin = handler.headers.get('Origin')
    expected = ('http://' if handler.server.proof_mode == 'local' else 'https://') + handler.headers.get('Host', '')
    if origin != expected or handler.headers.get('X-PROOF-LIVE') != 'owner-action':
        handler._json(403, {'error': 'SAME_ORIGIN_OWNER_ACTION_REQUIRED'})
        return
    try:
        lengths = handler.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > 4096 or handler.headers.get('Transfer-Encoding'):
            raise ValueError()
        if handler.headers.get_content_type() != 'application/json':
            raise ValueError()
        handler.connection.settimeout(10)
        data = experiment.strict_json(handler.rfile.read(int(lengths[0])).decode())
        if path == '/api/live/enable':
            if data != {}: raise ValueError()
            if not getattr(service, 'owner_activation_allowed', False):
                raise proof_live.Rejected(403, 'SEPARATE_PAID_CALL_AUTHORIZATION_REQUIRED')
            service.ledger.enable()
            service.enabled = True
            handler._json(200, {'status': 'ENABLED', 'request_sent': False})
            return
        if path == '/api/live/disable':
            if data != {}:
                raise ValueError()
            service.ledger.disable()
            service.enabled = False
            handler._json(200, {'status': 'DISABLED', 'in_flight_request_not_cancelled': True})
            return
        if type(data) is not dict or set(data) != {'case_id', 'request_id'}:
            raise ValueError()
        handler._json(200, service.infer(data['case_id'], data['request_id']))
    except proof_live.Rejected as error:
        reject(handler, error)
    except (ValueError, TypeError, KeyError, UnicodeError, TimeoutError):
        handler._json(400, {'error': 'INVALID_LIVE_REQUEST', 'baseline_status': 'NOT_RUN'})
    except Exception:
        # No exception string, response header, private path or credential leak.
        handler._json(503, {'error': 'LIVE_STATE_UNAVAILABLE', 'baseline_status': 'NOT_RUN'})
