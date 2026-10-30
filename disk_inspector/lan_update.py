"""Zero-setup LAN access for installing *official verified* QnapControlCenter QPKGs.

This is intentionally network trust rather than QTS user authentication.
Only socket source and destination addresses count; X-Forwarded-* is ignored.
The two-step one-use nonce is automatic in the browser, not a user token.
"""
import ipaddress
import secrets
import threading
import time
from urllib.parse import urlsplit

# RFC1918 plus Tailscale/CGNAT and IPv6 ULA for private networks.
# Loopback is handled separately for NAS-local administration.
LAN_NETS = tuple(ipaddress.ip_network(c) for c in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "fc00::/7",
))


def _ip(value):
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return address.ipv4_mapped
        return address
    except (ValueError, TypeError):
        return None


def _lan_ip(value):
    addr = _ip(value)
    return bool(addr and any(addr in net for net in LAN_NETS
                             if net.version == addr.version))


def allowed_peer(peer, local, host, *, expected_port=8778):
    """No allowlist configuration required: private source and destination.

    Host must exactly identify the actual listening socket address and port.
    This deliberately refuses proxy aliases, public peers and host spoofing.
    """
    peer_ip, local_ip = _ip(peer), _ip(local)
    if not peer_ip or not local_ip:
        return False
    if not ((peer_ip.is_loopback and local_ip.is_loopback) or
            (_lan_ip(peer) and _lan_ip(local))):
        return False
    if not isinstance(host, str) or not host or len(host) > 128:
        return False
    try:
        parsed = urlsplit("http://" + host)
        host_ip = _ip(parsed.hostname)
        if (parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or parsed.port != expected_port):
            return False
        return bool(host_ip and host_ip == local_ip)
    except ValueError:
        return False


def authorized_post(peer, local, host, origin, fetch_site, intent, mime,
                    *, expected_port=8778):
    return (
        allowed_peer(peer, local, host, expected_port=expected_port)
        and origin == "http://" + host
        and fetch_site in ("", "same-origin")
        and intent == "1" and mime == "application/json"
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
