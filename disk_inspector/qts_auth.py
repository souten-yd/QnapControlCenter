"""QTS administrator login for Web updates.

Never store NAS credentials. Session cookies are memory-only and expire.
The login endpoint requires an HTTPS reverse proxy to avoid password exposure.
"""
import base64
import hmac
import secrets
import time
import xml.etree.ElementTree as ET
from http.cookies import SimpleCookie
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_SESSIONS = {}
_TTL = 900
_QTS_AUTH_URL = "http://127.0.0.1:8080/cgi-bin/authLogin.cgi"

def validate_qts_admin(username, password):
    if not (isinstance(username, str) and isinstance(password, str)
            and 0 < len(username) <= 100 and 0 < len(password) <= 512):
        return False
    # QTS authentication endpoint on NAS loopback only; no credentials persisted.
    form = urlencode({"user": username,
        "pwd": base64.b64encode(password.encode("utf-8")).decode("ascii")}).encode()
    req = Request(_QTS_AUTH_URL, data=form, method="POST")
    with urlopen(req, timeout=5) as response:
        xml = response.read(16384)
    root = ET.fromstring(xml)
    return root.findtext(".//authPassed") == "1" and root.findtext(".//isAdmin") == "1"

def new_session():
    key = secrets.token_urlsafe(32)
    now = time.monotonic()
    for old, expire in list(_SESSIONS.items()):
        if expire <= now:
            _SESSIONS.pop(old, None)
    _SESSIONS[key] = now + _TTL
    return key

def authenticated(header):
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
        value = cookie["qcc_admin"].value
    except (KeyError, ValueError):
        return False
    expiry = _SESSIONS.get(value, 0)
    if expiry <= time.monotonic():
        _SESSIONS.pop(value, None)
        return False
    return True

def revoke(header):
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
        _SESSIONS.pop(cookie["qcc_admin"].value, None)
    except (KeyError, ValueError):
        pass
