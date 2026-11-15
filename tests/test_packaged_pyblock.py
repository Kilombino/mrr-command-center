"""PyBLØCK settings in the packaged app (Umbrel, StartOS): gateway and payout address
set from the dashboard into config.json, with the platform's env as defaults.

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


class PackagedPyblockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")
        with open(self.path, "w") as f:
            json.dump({"dashboard_password": "x"}, f)
        self.p = mock.patch.object(mrr_bot, "CONFIG_PATH", self.path)
        self.p.start()
        self.v = mock.patch.object(dashboard, "setup_view", lambda: {})
        self.v.start()

    def tearDown(self):
        self.v.stop()
        self.p.stop()
        self.tmp.cleanup()

    def test_parse_hostport(self):
        self.assertEqual(dashboard.parse_hostport("pool.example.com:23338"), {"host": "pool.example.com", "port": 23338})
        self.assertEqual(dashboard.parse_hostport(" 203.0.113.5:8333 "), {"host": "203.0.113.5", "port": 8333})
        for bad in ("", "pool.example.com", "pool:0", "pool:70000", "a b:1"):
            self.assertIsNone(dashboard.parse_hostport(bad))

    def test_env_defaults_and_dashboard_wins(self):
        env = {"MRR_PYBLOCK_GATEWAY": "env.example.com:23338", "MRR_PYBLOCK_ADDRESS": ""}
        with mock.patch.dict(os.environ, env):
            p = dashboard.cfg()["pyblock"]
            self.assertEqual(p["gateway"], {"host": "env.example.com", "port": 23338})
            dashboard.set_pyblock("mine.example.com:8333", "")
            p = dashboard.cfg()["pyblock"]
            self.assertEqual(p["gateway"], {"host": "mine.example.com", "port": 8333})
        with open(self.path) as f:
            self.assertEqual(json.load(f)["pyblock"]["gateway"]["port"], 8333)

    def test_rejects_local_and_bad(self):
        for gw in ("192.168.1.10:23338", "127.0.0.1:23338", "localhost:1", "10.0.0.1:2", "nope"):
            with self.assertRaises(RuntimeError):
                dashboard.set_pyblock(gw, "")
        with self.assertRaises(RuntimeError):
            dashboard.set_pyblock("mine.example.com:8333", "not-an-address")

    def test_clear(self):
        dashboard.set_pyblock("mine.example.com:8333", "")
        dashboard.set_pyblock("", "")
        self.assertEqual(dashboard.pyblock_setup(dashboard.cfg())["gateway"], "")


if __name__ == "__main__":
    unittest.main()
