# src/backend/security_log.py
# Structured JSON security event logging.
import json
import logging
from datetime import datetime, timezone

from flask import request

_handler = logging.FileHandler('security_events.log')
_handler.setFormatter(logging.Formatter('%(message)s'))
_sec = logging.getLogger('security')
_sec.addHandler(_handler)
_sec.setLevel(logging.INFO)
_sec.propagate = False


def log_security(event, **kwargs):
    """Emit a JSON line to security_events.log."""
    _sec.info(json.dumps({
        'ts': datetime.now(timezone.utc).isoformat(),
        'event': event,
        'ip': getattr(request, 'remote_addr', None),
        **kwargs,
    }))
