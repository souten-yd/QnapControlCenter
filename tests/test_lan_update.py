"""Default-on LAN official updater: zero setup, same-origin and nonce gates."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from disk_inspector import lan_update, installer
from disk_inspector.server import State, handler_factory


class LanUpdatePolicyTests(unittest.TestCase):
    def allowed(self, peer="192.168.68.20", local="192.168.68.57",
                host="192.168.68.57:8778"):
        return lan_update.allowed_peer(peer, local, host)

    def test_private_lan_without_any_configuration(self):
        self.assertTrue(self.allowed())
        self.assertTrue(self.allowed(peer="192.168.68.21"))
        self.assertTrue(self.allowed(peer="10.17.2.11"))
        self.assertTrue(self.allowed(peer="100.103.1.7"))
        self.assertTrue(self.allowed(peer="172.22.1.40"))
        self.assertTrue(lan_update.allowed_peer(
            "fd15::17", "fd15::22", "[fd15::22]:8778"))
        self.assertTrue(lan_update.allowed_peer(
            "127.0.0.1", "127.0.0.1", "127.0.0.1:8778"))

    def test_public_networks_and_mismatched_socket_host_denied(self):
        self.assertFalse(self.allowed(peer="8.8.8.8"))
        self.assertFalse(self.allowed(local="8.8.8.8", host="8.8.8.8:8778"))
        self.assertFalse(self.allowed(peer="127.0.0.1"))
        self.assertFalse(self.allowed(local="127.0.0.1",
                                     host="127.0.0.1:8778"))
        self.assertFalse(self.allowed(host="nas.example:8778"))
        self.assertFalse(self.allowed(host="192.168.68.57:7777"))
        self.assertFalse(self.allowed(host="192.168.68.20:8778"))
        self.assertFalse(self.allowed(host="192.168.68.57:8778@evil.test"))
        self.assertFalse(self.allowed(host="192.168.68.57:8778/path"))
        self.assertFalse(self.allowed(host="192.168.68.57:8778?bad=true"))
        self.assertFalse(self.allowed(host=""))

    def test_origin_custom_intent_and_fetch_metadata_required(self):
        args=("192.168.68.20","192.168.68.57","192.168.68.57:8778",
              "http://192.168.68.57:8778","same-origin","1",
              "application/json")
        self.assertTrue(lan_update.authorized_post(*args))
        for idx, bad in ((3,"https://evil.example"),(3,""),
                         (4,"cross-site"),(5,""),(6,"text/plain")):
            with self.subTest(index=idx,bad=bad):
                values=list(args)
                values[idx]=bad
                self.assertFalse(lan_update.authorized_post(*values))

    def test_legacy_allowlist_config_is_not_required(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"qpkg.conf"
            cfg.write_text("[QnapControlCenter]\nLAN_Update_Enabled=FALSE\n"
                           "LAN_Update_Clients=192.168.68.99/32\n")
            # A legacy setting must never silently block ordinary LAN clients.
            self.assertTrue(self.allowed(peer="192.168.68.20"))

    def test_nonce_single_use_expiry_and_rate_limits(self):
        clock=[10.0]
        gate=lan_update.OneUseConfirmations(clock=lambda:clock[0])
        nonce=gate.issue("192.168.68.20","v0.1.14-rc16")
        self.assertFalse(gate.consume("192.168.68.21","v0.1.14-rc16",nonce))
        self.assertFalse(gate.consume("192.168.68.20","v0.1.14-rc16",nonce))
        nonce=gate.issue("192.168.68.20","v0.1.14-rc16")
        self.assertTrue(gate.consume("192.168.68.20","v0.1.14-rc16",nonce))
        self.assertFalse(gate.consume("192.168.68.20","v0.1.14-rc16",nonce))
        nonce=gate.issue("192.168.68.20","v0.1.14-rc16")
        clock[0]+=61
        self.assertFalse(gate.consume("192.168.68.20","v0.1.14-rc16",nonce))
        gate.issue("192.168.68.20","v0.1.14-rc16")
        gate.issue("192.168.68.20","v0.1.14-rc16")
        with self.assertRaises(RuntimeError):
            gate.issue("192.168.68.20","v0.1.14-rc16")


class WebEndpointTests(unittest.TestCase):
    def setUp(self):
        self.state=State()
        self.http=ThreadingHTTPServer(("127.0.0.1",0),
                                      handler_factory(self.state))
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base="http://127.0.0.1:%d" % self.http.server_port

    def post(self,path,data,intent=True,origin=None,fetch_site=None):
        headers={"Origin":origin if origin is not None else self.base,
                 "Content-Type":"application/json"}
        if intent:
            headers["X-QCC-Update-Intent"]="1"
        if fetch_site is not None:
            headers["Sec-Fetch-Site"]=fetch_site
        req=Request(self.base+path,data=json.dumps(data).encode(),
                    headers=headers,method="POST")
        try:
            with urlopen(req,timeout=4) as response:
                return response.status,json.load(response)
        except HTTPError as exc:
            return exc.code,(json.load(exc) if
                exc.headers.get_content_type()=="application/json" else {})

    def test_loopback_update_status_requires_no_ip_setup(self):
        with patch("disk_inspector.server.installer.ready",return_value=True):
            with urlopen(self.base+"/api/update-status") as res:
                info=json.load(res)
        self.assertTrue(info["lan_available"])
        self.assertTrue(info["available"])

    def test_preparation_and_single_install_without_token(self):
        release={"tag":"v0.1.14-rc16",
                 "qpkg":[{"name":"QnapControlCenter_0.1.14_x86_64.qpkg"}]}
        with patch("disk_inspector.server.installer.authenticate",return_value=False), \
             patch("disk_inspector.server.installer.ready",return_value=True), \
             patch("disk_inspector.server.check_latest",return_value=release), \
             patch("disk_inspector.server.installer.start",return_value={"state":"starting"}) as start:
            code,prepared=self.post("/api/prepare-update",{"tag":"v0.1.14-rc16"})
            self.assertEqual(code,200)
            data={"tag":"v0.1.14-rc16","nonce":prepared["nonce"]}
            code,_=self.post("/api/install-update",data)
            self.assertEqual(code,202)
            code,_=self.post("/api/install-update",data)
            self.assertEqual(code,403)
            start.assert_called_once_with("v0.1.14-rc16")

    def test_cross_site_and_missing_intent_cannot_prepare(self):
        with patch("disk_inspector.server.check_latest") as check:
            code,_=self.post("/api/prepare-update",{"tag":"v0.1.14-rc16"},
                             origin="https://evil.example")
            self.assertEqual(code,403)
            code,_=self.post("/api/prepare-update",{"tag":"v0.1.14-rc16"},
                             intent=False)
            self.assertEqual(code,403)
            code,_=self.post("/api/prepare-update",{"tag":"v0.1.14-rc16"},
                             fetch_site="cross-site")
            self.assertEqual(code,403)
            check.assert_not_called()

    def test_invalid_release_and_input_cannot_prepare(self):
        with patch("disk_inspector.server.check_latest",
                   return_value={"tag":"v9.9.9","qpkg":[]}), \
             patch("disk_inspector.server.installer.ready",return_value=True):
            code,_=self.post("/api/prepare-update",{"tag":"v0.1.14-rc16"})
            self.assertEqual(code,409)
            code,_=self.post("/api/prepare-update",{"tag":"../bad"})
            self.assertEqual(code,400)


class InstallerReadyTests(unittest.TestCase):
    def test_cli_is_sufficient_without_token_file(self):
        with patch("disk_inspector.installer.shutil.which",return_value="/usr/bin/qpkg_cli"), \
             patch("disk_inspector.installer.Path.is_file",return_value=True), \
             patch.object(installer,"TOKEN_FILE") as token:
            token.is_file.return_value=False
            self.assertTrue(installer.ready())
            token.is_file.assert_not_called()

    def test_no_cli_still_refuses(self):
        with patch("disk_inspector.installer.shutil.which",return_value=None):
            self.assertFalse(installer.ready())


if __name__=="__main__":
    unittest.main()
