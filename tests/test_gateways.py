"""Saved public stratums for PyBLØCK / P2Hash (1.4.5): pyblock.gateways next to the
active pyblock.gateway, chosen from the dashboard.

Run: python3 -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dashboard  # noqa: E402
import mrr_bot  # noqa: E402
import pyblock as pyb  # noqa: E402


class GatewayListTests(unittest.TestCase):
    def test_old_config_gives_list_of_one(self):
        p = pyb.settings({"pyblock": {"gateway": {"host": "pool.example.com", "port": 23334}}})
        self.assertEqual(p["gateways"], [{"name": "", "host": "pool.example.com", "port": 23334}])
        self.assertEqual(pyb.settings({})["gateways"], [])

    def test_list_dedupes_and_keeps_active(self):
        p = pyb.settings({"pyblock": {
            "gateway": {"host": "pool.example.com", "port": 23335},
            "gateways": [{"name": "DATUM", "host": "pool.example.com", "port": 23334},
                         "POOL.example.com:23334", {"name": "x", "hostport": "bad"}]}})
        self.assertEqual([pyb.hostport(g) for g in p["gateways"]],
                         ["pool.example.com:23334", "pool.example.com:23335"])
        self.assertEqual(p["gateways"][0]["name"], "DATUM")

    def test_edit(self):
        raw = {"pyblock": {"gateway": {"host": "pool.example.com", "port": 23334}}}
        pyb.edit_gateways(raw, "add", "pool.example.com:23335", "PATUM")
        self.assertEqual(raw["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23334})
        self.assertEqual(len(raw["pyblock"]["gateways"]), 2)
        pyb.edit_gateways(raw, "add", "pool.example.com:23334", "DATUM")      # rename, no duplicate
        self.assertEqual([g["name"] for g in raw["pyblock"]["gateways"]], ["DATUM", "PATUM"])
        pyb.edit_gateways(raw, "use", "pool.example.com:23335")
        self.assertEqual(pyb.settings(raw)["gateway"], {"host": "pool.example.com", "port": 23335})
        with self.assertRaises(ValueError):
            pyb.edit_gateways(raw, "remove", "pool.example.com:23335")         # the active one
        with self.assertRaises(ValueError):
            pyb.edit_gateways(raw, "remove", "pool.example.com:23334")         # the main gateway (the first)
        pyb.edit_gateways(raw, "primary", "pool.example.com:23335")
        pyb.edit_gateways(raw, "remove", "pool.example.com:23334")
        self.assertEqual([pyb.hostport(g) for g in raw["pyblock"]["gateways"]], ["pool.example.com:23335"])
        for bad in ("192.168.1.10:23338", "localhost:1", "nope", "pool.example.com:0"):
            with self.assertRaises(ValueError):
                pyb.edit_gateways(raw, "add", bad)
        with self.assertRaises(ValueError):
            pyb.edit_gateways(raw, "use", "other.example.com:1")

    def test_first_added_becomes_active(self):
        raw = {}
        pyb.edit_gateways(raw, "add", "pool.example.com:23334")
        self.assertEqual(raw["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23334})


class GatewayTestCacheTests(unittest.TestCase):
    def test_cached_result_is_per_stratum(self):
        conf = {"rent_address": "bc1qexampleexampleexampleexampleexample0", "pyblock": {
            "gateway": {"host": "pool.example.com", "port": 23334}}}
        p = pyb.PyBlock(tempfile.mkdtemp(), lambda: conf)
        calls = []
        def fake(method, url, timeout=0, **kw):
            calls.append(url)
            return 200, {"ok": True}
        with mock.patch.object(pyb, "http_json", fake):
            self.assertEqual(p.gateway_test()["pool"], "pool.example.com:23334")
            p.gateway_test()
            self.assertEqual(len(calls), 1)                                   # cached
            pyb.edit_gateways(conf, "add", "pool.example.com:23335")
            pyb.edit_gateways(conf, "use", "pool.example.com:23335")
            self.assertEqual(p.gateway_test()["pool"], "pool.example.com:23335")   # not the old result
            self.assertEqual(len(calls), 2)
            self.assertIn("23335", calls[1])


class DashboardGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")
        with open(self.path, "w") as f:
            json.dump({"dashboard_password": "x",
                       "pyblock": {"gateway": {"host": "pool.example.com", "port": 23334}}}, f)
        self.p = mock.patch.object(mrr_bot, "CONFIG_PATH", self.path)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_writes_config(self):
        r = dashboard.edit_pyblock_gateways("add", "pool.example.com:23335", "PATUM")
        self.assertEqual([g["hostport"] for g in r["gateways"]], ["pool.example.com:23334", "pool.example.com:23335"])
        r = dashboard.edit_pyblock_gateways("use", "pool.example.com:23335")
        self.assertEqual(r["gateway"], "pool.example.com:23335")
        with open(self.path) as f:
            raw = json.load(f)
        self.assertEqual(raw["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23335})
        self.assertEqual(raw["dashboard_password"], "x")
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")
        with self.assertRaises(RuntimeError):
            dashboard.edit_pyblock_gateways("add", "10.0.0.1:1")


if __name__ == "__main__":
    unittest.main()
