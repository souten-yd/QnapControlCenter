"""Explicitly opted-in, source-IP allowlisted LAN update authorization.

This is an administrator-controlled trusted-network exception, not QTS user
authentication. It must never be enabled by default or infer trust from RFC1918
addresses alone. The QTS configuration is checked on each update request.
"""
import ipaddress
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

CONFIG = Path("/etc/config/qpkg.conf")
TRUSTED = tuple(ipaddress.ip_network(s) for s in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "fc00::/7",
))


def _ip(value):
    try:
        addr = ipaddress.ip_address(value)
        return addr.ipv4_mapped or addr if isinstance(addr, ipaddress.IPv6Address) else addr
    except (ValueError, TypeError):
        return None


def _settings(path=CONFIG):
    """Parse only QnapControlCenter's QTS INI section; malformed means disabled."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    active = False
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            active = line == "[QnapControlCenter]"
        elif active and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"')
    if values.get("LAN_Update_Enabled") != "TRUE":
        return []
    raw = values.get("LAN_Update_Clients", "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if not items or len(items) > 16:
        return []
    nets = []
    try:
        for item in items:
            network = ipaddress.ip_network(item, strict=False)
            # No blanket RFC1918 /8 grants; IPv4 /24 or narrower, IPv6 /64+.
            if network.prefixlen < (24 if network.version == 4 else 64):
                return []
            if not any(network.subnet_of(parent) for parent in TRUSTED if parent.version == network.version):
                return []
            nets.append(network)
    except ValueError:
        return []
    return nets


def allowed_peer(peer, local, host, *, config_path=CONFIG, expected_port=8778):
    """Require a real LAN peer and a numeric same-socket Host (no proxy trust)."""
    peer_ip, local_ip = _ip(peer), _ip(local)
    if not peer_ip or not local_ip:
        return False
    if peer_ip.is_loopback or local_ip.is_loopback:
        return False
    if not any(peer_ip in net for net in _settings(config_path)):
        return False
    if not isinstance(host, str) or len(host) > 128:
        return False
    try:
        host_url = urlsplit("http://" + host)
        host_ip = _ip(host_url.hostname)
        if (host_url.username or host_url.password or host_url.path or
                host_url.query or host_url.fragment or host_url.port != expected_port):
            return False
        return bool(host_ip and host_ip == local_ip)
    except ValueError:
        return False


def authorized_post(peer, local, host, origin, fetch_site, intent, mime,
                    *, config_path=CONFIG, expected_port=8778):
    return (
        allowed_peer(peer, local, host, config_path=config_path, expected_port=expected_port) and
        origin == "http://" + host and
        fetch_site in ("", "same-origin") and
        intent == "1" and mime == "application/json"
    )


class OneUseConfirmations:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.issued = {}
        self.attempts = {}

    def issue(self, peer, tag):
        now = self.clock()
        with self.lock:
            self.issued = {key: item for key, item in self.issued.items()
                           if item[2] > now}
            self.attempts = {
                key: [t for t in old if t > now - 600]
                for key, old in self.attempts.items()
            }
            self.attempts = {k: v for k, v in self.attempts.items() if v}
            if len(self.attempts.get(peer, [])) >= 5 or sum(
                len(v) for v in self.attempts.values()
            ) >= 20:
                raise RuntimeError("Too many update requests; retry later")
            self.attempts.setdefault(peer, []).append(now)
            nonce = secrets.token_urlsafe(32)
            self.issued[nonce] = (peer, tag, now + 60)
            return nonce

    def consume(self, peer, tag, nonce):
        if not isinstance(nonce, str) or len(nonce) != 43:
            return False
        with self.lock:
            item = self.issued.pop(nonce, None)
            return bool(item and item[0] == peer and item[1] == tag and
                        item[2] > self.clock())
