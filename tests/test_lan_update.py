"""LAN update admission and single-use confirmation tests."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from disk_inspector import lan_update
from disk_inspector.server import State, handler_factory

class LanUpdatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = Path(self.tmp.name) / "qpkg.conf"
        self.set_config("FALSE", "192.168.68.20/32")

    def set_config(self, enabled, clients):
        self.conf.write_text(
            "[QnapControlCenter]\nLAN_Update_Enabled = " + enabled +
            "\nLAN_Update_Clients = " + clients + "\n", encoding="utf-8")

    def allowed(self, peer="192.168.68.20", local="192.168.68.57",
                host="192.168.68.57:8778"):
        return lan_update.allowed_peer(
            peer, local, host, config_path=self.conf)

    def test_disabled_by_default(self):
        self.assertFalse(self.allowed())

    def test_allowlisted_client_only(self):
        self.set_config("TRUE", "192.168.68.20/32")
        self.assertTrue(self.allowed())
        self.assertFalse(self.allowed(peer="192.168.68.21"))
        self.assertFalse(self.allowed(peer="8.8.8.8"))
        self.assertFalse(self.allowed(peer="127.0.0.1"))
        self.assertFalse(self.allowed(local="127.0.0.1"))
        self.assertFalse(self.allowed(host="nas.example:8778"))
        self.assertFalse(self.allowed(host="192.168.68.57:7777"))
        self.assertFalse(self.allowed(host="192.168.68.20:8778"))

    def test_explicit_small_subnet_only(self):
        self.set_config("TRUE", "192.168.68.0/24")
        self.assertTrue(self.allowed(peer="192.168.68.99"))
        self.set_config("TRUE", "192.168.0.0/16")
        self.assertFalse(self.allowed())
        self.set_config("TRUE", "0.0.0.0/0")
        self.assertFalse(self.allowed())
        self.set_config("TRUE", "192.168.68.20/32,not-an-ip")
        self.assertFalse(self.allowed())
        self.set_config("TRUE", "")
        self.assertFalse(self.allowed())

    def test_origin_and_custom_header_required(self):
        self.set_config("TRUE", "192.168.68.20/32")
        args=("192.168.68.20", "192.168.68.57", "192.168.68.57:8778",
              "http://192.168.68.57:8778", "same-origin", "1",
              "application/json")
        self.assertTrue(lan_update.authorized_post(*args, config_path=self.conf))
        for idx, bad in ((3, "http://evil.test"), (4, "cross-site"),
                         (5, ""), (6, "text/plain")):
            with self.subTest(idx=idx):
                modified=list(args); modified[idx]=bad
                self.assertFalse(lan_update.authorized_post(
                    *modified, config_path=self.conf))

    def test_nonce_single_use_expiry_and_limiter(self):
        clock=[10.0]
        gate=lan_update.OneUseConfirmations(clock=lambda:clock[0])
        token=gate.issue("192.168.68.20", "v0.1.9-rc11")
        self.assertFalse(gate.consume("192.168.68.21","v0.1.9-rc11", token))
        self.assertFalse(gate.consume("192.168.68.20","v0.1.9-rc11", token))
        token=gate.issue("192.168.68.20", "v0.1.9-rc11")
        self.assertTrue(gate.consume("192.168.68.20","v0.1.9-rc11", token))
        self.assertFalse(gate.consume("192.168.68.20","v0.1.9-rc11", token))
        token=gate.issue("192.168.68.20", "v0.1.9-rc11")
        clock[0]+=61
        self.assertFalse(gate.consume("192.168.68.20","v0.1.9-rc11", token))
        gate.issue("192.168.68.20","v0.1.9-rc11")
        gate.issue("192.168.68.20","v0.1.9-rc11")
        with self.assertRaises(RuntimeError):
            gate.issue("192.168.68.20","v0.1.9-rc11")

class WebEndpointTests(unittest.TestCase):
    def setUp(self):
        self.state=State()
        self.http=ThreadingHTTPServer(("127.0.0.1",0),
                                     handler_factory(self.state))
        self.thread=threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base="http://127.0.0.1:%d" % self.http.server_port

    def post(self, path, data, intent=True, origin=None):
        headers={"Origin":origin if origin is not None else self.base,
                 "Content-Type":"application/json"}
        if intent:
            headers["X-QCC-Update-Intent"]="1"
        req=Request(self.base+path, data=json.dumps(data).encode(),
                    headers=headers, method="POST")
        try:
            with urlopen(req,timeout=4) as resp:
                return resp.status, json.load(resp)
        except HTTPError as err:
            return err.code, json.load(err) if err.headers.get_content_type()=="application/json" else {}

    def test_no_lan_permission_returns_403(self):
        code,_=self.post("/api/prepare-update",{"tag":"v0.1.9-rc11"})
        self.assertEqual(code,403)

    def test_preparation_and_single_install(self):
        result={"tag":"v0.1.9-rc11","qpkg":[{"name":"QnapControlCenter.qpkg"}]}
        with patch("disk_inspector.server.lan_update.authorized_post",return_value=True), \
             patch("disk_inspector.server.installer.authenticate",return_value=False), \
             patch("disk_inspector.server.installer.ready",return_value=True), \
             patch("disk_inspector.server.check_latest",return_value=result), \
             patch("disk_inspector.server.installer.start",return_value={"state":"starting"}) as run:
            status, prepared=self.post("/api/prepare-update", {"tag":"v0.1.9-rc11"})
            self.assertEqual(status,200)
            data={"tag":"v0.1.9-rc11","nonce":prepared["nonce"]}
            status,_=self.post("/api/install-update", data)
            self.assertEqual(status,202)
            status,_=self.post("/api/install-update", data)
            self.assertEqual(status,403)
            run.assert_called_once_with("v0.1.9-rc11")

    def test_invalid_release_is_not_prepared(self):
        with patch("disk_inspector.server.lan_update.authorized_post",return_value=True), \
             patch("disk_inspector.server.installer.authenticate",return_value=False), \
             patch("disk_inspector.server.check_latest",return_value={"tag":"v8.8.8","qpkg":[]}):
            status,_=self.post("/api/prepare-update", {"tag":"v0.1.9-rc11"})
            self.assertEqual(status,409)
            status,_=self.post("/api/prepare-update", {"tag":"../evil"})
            self.assertEqual(status,400)

if __name__ == "__main__":
    unittest.main()
