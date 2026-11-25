"""Packaged app, 1.6.0: the MRR pool profile selector knows each profile's gateway, choosing
a profile moves PyBLØCK/P2Hash orders to that gateway, and the platform's DATUM stays the
main gateway (its status page from the platform, never removable).

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
import gateways as gw  # noqa: E402
import mrr_bot  # noqa: E402

PROFILES = [
    {"id": 1, "name": "Start9", "algo": {"name": "blake2b"},
     "pools": [{"priority": 0, "host": "pool.example.com", "port": 23334}]},
    {"id": 2, "name": "PATUM", "algo": {"name": "blake2b"}},           # pools only from /account/profile/2
    {"id": 3, "name": "Otro", "algo": {"name": "blake2b"},
     "pools": [{"priority": 1, "host": "x.example.com", "port": 4000},
               {"priority": 0, "host": "pool.example.com", "port": 23336}]},
    {"id": 4, "name": "sha", "algo": {"name": "sha256"}},
    {"id": 5, "name": "Pool", "algo": {"name": "blake2b"},              # a pool's DATUM port
     "pools": [{"priority": 0, "host": "datum.example.org", "port": 28915}]},
]


class Api:
    def __init__(self):
        self.state = {}
        self.calls = []

    def call(self, method, path, body=None):
        self.calls.append(path)
        if path == "/account/profile":
            return json.loads(json.dumps(PROFILES))
        if path == "/account/profile/2":
            return {"pools": [{"priority": 0, "host": "pool.example.com", "port": 23335}]}
        raise AssertionError(path)


class PackagedProfileGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")
        with open(self.path, "w") as f:
            json.dump({"dashboard_password": "x", "algo": "blake2b", "pyblock": {
                "gateway": {"host": "pool.example.com", "port": 23334},
                "gateways": [{"name": "Start9", "host": "pool.example.com", "port": 23334},
                             {"name": "PATUM", "host": "pool.example.com", "port": 23335,
                              "api": {"url": "http://10.0.0.5:7153", "password": "patumsecret"}}]}}, f)
        self.api = Api()
        self.patches = [mock.patch.object(mrr_bot, "CONFIG_PATH", self.path),
                        mock.patch.object(dashboard, "mrr_api", lambda c: self.api),
                        mock.patch.object(mrr_bot, "save_state", lambda s: None),
                        mock.patch.dict(os.environ, {"MRR_GATEWAY_URL": "http://datum.embassy:7152",
                                                     "MRR_GATEWAY_PASSWORD": "mainsecret"})]
        for p in self.patches:
            p.start()
        dashboard._profile_pools.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_profiles_know_their_gateway(self):
        r = dashboard.pool_profiles()
        got = {p["id"]: (p["pool"], p["gw"]) for p in r["profiles"]}
        self.assertEqual(got[1], ("pool.example.com:23334", "main"))
        self.assertEqual(got[2], ("pool.example.com:23335", "pool.example.com:23335"))
        self.assertEqual(got[3], ("pool.example.com:23336", None))           # first by priority, not saved
        self.assertEqual(got[4], ("", None))                                 # other algorithm: not read
        self.assertEqual(got[5], ("datum.example.org:28915", None))
        self.assertEqual({p["id"]: p.get("warn") for p in r["profiles"]}[5], "datum_pool")
        dashboard.pool_profiles()
        self.assertEqual(self.api.calls.count("/account/profile/2"), 1)      # kept 10 min

    def test_choosing_a_profile_moves_orders_to_its_gateway(self):
        with mock.patch.object(dashboard, "setup_view", lambda: {}):
            r = dashboard.set_profile(2)
        self.assertEqual((r["profile_gw"], r["profile_pool"]), ("pool.example.com:23335", "pool.example.com:23335"))
        with open(self.path) as f:
            raw = json.load(f)
        self.assertEqual(raw["profile_id"], 2)
        self.assertEqual(raw["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23335})
        self.assertEqual(raw["pyblock"]["gateways"][1]["api"]["password"], "patumsecret")   # untouched
        with mock.patch.object(dashboard, "setup_view", lambda: {}):
            r = dashboard.set_profile(3)                                     # not a saved gateway
        self.assertEqual((r["profile_gw"], r["profile_pool"]), (None, "pool.example.com:23336"))
        with open(self.path) as f:
            self.assertEqual(json.load(f)["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23335})

    def test_a_pool_datum_port_is_flagged_not_offered_as_gateway(self):
        with mock.patch.object(dashboard, "setup_view", lambda: {}):
            r = dashboard.set_profile(5)
        self.assertEqual((r["profile_gw"], r["profile_warn"]), (None, "datum_pool"))
        with open(self.path) as f:                                         # orders keep their gateway
            self.assertEqual(json.load(f)["pyblock"]["gateway"], {"host": "pool.example.com", "port": 23334})

    def test_platform_datum_is_the_main_gateway(self):
        lst = gw.listing(dashboard.cfg())
        self.assertEqual(lst[0]["key"], "main")
        self.assertEqual(lst[0]["api"]["url"], "http://datum.embassy:7152")
        self.assertEqual(lst[0]["api"]["password"], "mainsecret")
        with self.assertRaises(RuntimeError):
            dashboard.edit_pyblock_gateways("remove", "pool.example.com:23334")

    def test_setup_view_has_no_page_password(self):
        out = json.dumps(dashboard.setup_view(), default=str)
        self.assertNotIn("secret", out)
        self.assertIn("http://10.0.0.5:7153", out)


if __name__ == "__main__":
    unittest.main()
