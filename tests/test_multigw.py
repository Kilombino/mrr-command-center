"""Several DATUM gateways (1.6.0): listing, matching a rental's pool, per-gateway reads,
history and audit, and no status-page password in any response."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import audit as audit_mod  # noqa: E402
import dashboard  # noqa: E402
import gateways as gw  # noqa: E402
import mrr_bot  # noqa: E402
import pyblock as pyb  # noqa: E402

MAIN_API = {"url": "http://127.0.0.1:7152", "user": "admin", "password": "mainsecret"}
TWO = {"gateway": MAIN_API, "pyblock": {
    "gateway": {"host": "pool.example.com", "port": 23334},
    "gateways": [{"name": "Start9", "host": "pool.example.com", "port": 23334},
                 {"name": "PATUM", "host": "pool.example.com", "port": 23335,
                  "api": {"url": "http://10.0.0.5:7153/", "user": "admin", "password": "patumsecret"}}]}}


class ListingTests(unittest.TestCase):
    def test_old_config_is_one_main_gateway(self):
        lst = gw.listing({"gateway": MAIN_API})
        self.assertEqual([g["key"] for g in lst], ["main"])
        self.assertTrue(lst[0]["primary"])
        self.assertEqual(lst[0]["api"], MAIN_API)
        lst = gw.listing({"gateway": MAIN_API, "pyblock": {"gateway": {"host": "pool.example.com", "port": 23334}}})
        self.assertEqual([(g["key"], g["hostport"]) for g in lst], [("main", "pool.example.com:23334")])

    def test_two_gateways(self):
        lst = gw.listing(TWO)
        self.assertEqual([g["key"] for g in lst], ["main", "pool.example.com:23335"])
        self.assertEqual(lst[0]["api"], MAIN_API)                     # the main one keeps the panel's API
        self.assertEqual(lst[1]["api"]["url"], "http://10.0.0.5:7153")  # trailing slash dropped
        self.assertEqual([g["key"] for g in gw.extra(lst)], ["pool.example.com:23335"])

    def test_primary_mark_moves_the_main_api(self):
        conf = json.loads(json.dumps(TWO))
        pyb.edit_gateways(conf, "primary", "pool.example.com:23335")
        lst = gw.listing(conf)
        self.assertEqual([g["key"] for g in lst], ["pool.example.com:23334", "main"])
        self.assertEqual(lst[1]["api"], MAIN_API)

    def test_public_has_no_password(self):
        status = {"main": {"data": {"total_th": 5.0, "subscribed": 2}},
                  "pool.example.com:23335": {"data": None, "error": "timed out"}}
        out = gw.public(gw.listing(TWO), status)
        self.assertNotIn("secret", json.dumps(out))
        self.assertEqual(out[0]["total_th"], 5.0)
        self.assertEqual((out[1]["ok"], out[1]["error"], out[1]["has_api"]), (False, "timed out", True))
        self.assertNotIn("secret", json.dumps(pyb.public_gateways(pyb.settings(TWO)["gateways"])))


class MatchTests(unittest.TestCase):
    def test_single_gateway_gets_everything(self):
        lst = gw.listing({"gateway": MAIN_API})
        self.assertEqual(gw.match(lst, "anything.example", 9999), "main")
        self.assertEqual(gw.match(lst, None, None), "main")

    def test_by_port(self):
        lst = gw.listing(TWO)
        self.assertEqual(gw.match(lst, "pool.example.com", 23334), "main")
        self.assertEqual(gw.match(lst, "1.2.3.4", "23335"), "pool.example.com:23335")   # host may differ (domain vs IP)
        self.assertIsNone(gw.match(lst, "pool.example.com", 3333))
        self.assertIsNone(gw.match(lst, "pool.example.com", "x"))

    def test_same_port_two_hosts(self):
        conf = {"gateway": MAIN_API, "pyblock": {"gateways": [
            {"name": "a", "host": "a.example.com", "port": 23334},
            {"name": "b", "host": "b.example.com", "port": 23334, "api": {"url": "http://10.0.0.9:7152"}}]}}
        lst = gw.listing(conf)
        self.assertEqual(gw.match(lst, "B.example.com", 23334), "b.example.com:23334")
        self.assertEqual(gw.match(lst, "a.example.com", 23334), "main")
        self.assertEqual(gw.match(lst, "c.example.com", 23334), "main")     # first of that port


class EditTests(unittest.TestCase):
    def test_page_saved_kept_and_dropped(self):
        raw = {"pyblock": {"gateway": {"host": "pool.example.com", "port": 23334}}}
        pyb.edit_gateways(raw, "add", "pool.example.com:23335", "PATUM",
                          {"url": "http://10.0.0.5:7153", "user": "", "password": "s3"})
        g = pyb.settings(raw)["gateways"][1]
        self.assertEqual(g["api"], {"url": "http://10.0.0.5:7153", "user": "admin", "password": "s3"})
        # rename without touching the page (api None), then change the url with an empty password
        pyb.edit_gateways(raw, "add", "pool.example.com:23335", "PATUM 2")
        pyb.edit_gateways(raw, "add", "pool.example.com:23335", "", {"url": "http://10.0.0.6:7153", "password": ""})
        g = pyb.settings(raw)["gateways"][1]
        self.assertEqual((g["name"], g["api"]["url"], g["api"]["password"]), ("PATUM 2", "http://10.0.0.6:7153", "s3"))
        # editing one leaves the other alone
        self.assertNotIn("api", pyb.settings(raw)["gateways"][0])
        pyb.edit_gateways(raw, "add", "pool.example.com:23335", "", {"url": ""})
        self.assertNotIn("api", pyb.settings(raw)["gateways"][1])
        with self.assertRaises(ValueError):
            pyb.edit_gateways(raw, "add", "pool.example.com:23335", "", {"url": "ftp://x"})

    def test_main_gateway_cannot_be_removed(self):
        raw = json.loads(json.dumps(TWO))
        pyb.edit_gateways(raw, "use", "pool.example.com:23335")
        with self.assertRaises(ValueError):
            pyb.edit_gateways(raw, "remove", "pool.example.com:23334")


class AuditAcrossGatewaysTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = audit_mod.Audit(self.tmp.name, {"audit": {"db": "audit.db"}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_pool_is_remembered(self):
        self.a.remember("11", "mrr11", None, "bc1qaddr", pool={"host": "pool.example.com", "port": "23335"})
        self.a.remember("11", "mrr11", None, "bc1qaddr")            # a later pass without the pool keeps it
        self.assertEqual(self.a.pools(), {"11": ("pool.example.com", 23335)})

    def test_old_database_gets_the_columns(self):
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE rental_worker (rental_id TEXT PRIMARY KEY, worker TEXT, observe_from INTEGER,"
                     " updated INTEGER)")
        conn.execute("INSERT INTO rental_worker VALUES ('5', 'mrr5', NULL, 1)")
        conn.commit()
        conn.close()
        a = audit_mod.Audit(self.tmp.name, {"audit": {"db": "old.db"}})
        self.assertEqual(a.pools(), {})
        self.assertEqual(a.workers()["5"]["worker"], "mrr5")

    def test_a_worker_is_measured_on_any_gateway(self):
        now = time.time()

        def cl(skey, shares):
            return {"subscribed": True, "skey": skey, "subbed_s": 3600, "worker": "mrr7",
                    "shares_accepted": shares, "vdiff": "1000"}
        with mock.patch("time.time", return_value=now - 600):
            self.a.record([cl("1_1_1_1", 0)], 10)
            self.a.record(dashboard.audit_rows([cl("1_1_1_1", 0)], "pool.example.com:23335"), 10)
        with mock.patch("time.time", return_value=now):
            self.a.record([cl("1_1_1_1", 10)], 10)
            self.a.record(dashboard.audit_rows([cl("1_1_1_1", 30)], "pool.example.com:23335"), 10)
        work, shares, conns, _, _ = self.a._work("mrr7", now - 700, now)
        self.assertEqual((shares, conns), (40, 2))      # same connection id on two gateways: kept apart


class DashboardMultiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")
        with open(self.path, "w") as f:
            json.dump(dict(TWO, dashboard_password="x"), f)
        self.patches = [mock.patch.object(mrr_bot, "CONFIG_PATH", self.path),
                        mock.patch.object(dashboard, "HISTORY_PATH", os.path.join(self.tmp.name, "history.json")),
                        mock.patch.object(dashboard, "AUDIT", [None])]
        for p in self.patches:
            p.start()
        dashboard.cache["gw"].clear()
        dashboard.xhistory.clear()
        dashboard._pool_cache.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        dashboard.cache["gw"].clear()
        dashboard.xhistory.clear()
        dashboard._pool_cache.clear()
        self.tmp.cleanup()

    def test_tag_rentals(self):
        lst = gw.listing(TWO)
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        pools = {"1": ("pool.example.com", 23334), "2": ("pool.example.com", 23335)}
        out = dashboard.tag_rentals(rows, lst, pools)
        self.assertEqual([(r["pool"], r["gw"]) for r in out],
                         [("pool.example.com:23334", "main"), ("pool.example.com:23335", "pool.example.com:23335"),
                          ("", None)])
        self.assertNotIn("gw", rows[0])                    # copies, the cached rentals are not touched

    def test_poll_others_reads_each_page_with_its_own_password(self):
        seen = []

        def fake_get(c, path):
            seen.append((c["gateway"]["url"], c["gateway"]["password"], path))
            return "<html></html>"
        with mock.patch.object(dashboard, "gateway_get", fake_get):
            dashboard.poll_others(dashboard.cfg(), 1000)
        self.assertEqual({(u, p) for u, p, _ in seen}, {("http://10.0.0.5:7153", "patumsecret")})
        ent = dashboard.cache["gw"]["pool.example.com:23335"]
        self.assertTrue(ent["data"]["ok"])
        self.assertEqual(dashboard.xhistory["pool.example.com:23335"], [{"t": 1000, "th": 0, "clients": 0}])
        lst, v = dashboard.gateways_view(dashboard.cfg())
        self.assertNotIn("secret", json.dumps(v, default=str))
        self.assertEqual(v["gw_views"]["pool.example.com:23335"]["history"][0]["t"], 1000)
        # its status page taken off: no longer read, its cache dropped
        dashboard.edit_pyblock_gateways("add", "pool.example.com:23335", "", {"url": ""})
        with mock.patch.object(dashboard, "gateway_get", fake_get):
            dashboard.poll_others(dashboard.cfg(), 1010)
        self.assertNotIn("pool.example.com:23335", dashboard.cache["gw"])
        lst, v = dashboard.gateways_view(dashboard.cfg())
        self.assertEqual(v["gw_views"]["pool.example.com:23335"]["error"], "sin página de estado")

    def test_a_page_that_fails_keeps_the_error(self):
        def boom(c, path):
            raise OSError("connection refused")
        with mock.patch.object(dashboard, "gateway_get", boom):
            dashboard.poll_others(dashboard.cfg(), 1000)
        ent = dashboard.cache["gw"]["pool.example.com:23335"]
        self.assertIsNone(ent["data"])
        self.assertIn("refused", ent["error"])
        self.assertEqual(dashboard.xhistory, {})

    def test_history_saved_and_loaded(self):
        dashboard.xhistory["k"] = [{"t": 1, "th": 2.0, "clients": 1}]
        dashboard.save_history()
        dashboard.xhistory.clear()
        n = len(dashboard.history)
        dashboard.load_history()
        del dashboard.history[n:]
        self.assertEqual(dashboard.xhistory["k"], [{"t": 1, "th": 2.0, "clients": 1}])

    def test_rental_pools_without_audit_respects_the_limit(self):
        calls = []

        class Api:
            state = {}

            def call(self, method, path, body=None):
                calls.append(path)
                return {"pools": [{"priority": 0, "host": "pool.example.com", "port": 23335}]}
        rentals = [{"id": i} for i in range(25)]
        with mock.patch.object(dashboard, "mrr_api", lambda c: Api()), \
                mock.patch.object(mrr_bot, "save_state", lambda s: None):
            first = dashboard.rental_pools(rentals)
            self.assertEqual(len(calls), 10)                 # at most 10 a call
            self.assertEqual(len(first), 10)
            dashboard.rental_pools(rentals)
            dashboard.rental_pools(rentals)
            self.assertEqual(len(calls), 25)                 # each read once
            dashboard.rental_pools(rentals)
            self.assertEqual(len(calls), 25)                 # cached for 30 min
        self.assertEqual(first["0"], ("pool.example.com", 23335))

    def test_gateway_cfg(self):
        c = dashboard.cfg()
        self.assertIs(dashboard.gateway_cfg(c, "main"), c)
        self.assertEqual(dashboard.gateway_cfg(c, "pool.example.com:23335")["gateway"]["url"], "http://10.0.0.5:7153")
        with self.assertRaises(RuntimeError):
            dashboard.gateway_cfg(c, "nope:1")

    def test_api_of(self):
        self.assertIsNone(dashboard.api_of({"action": "add"}))
        self.assertEqual(dashboard.api_of({"api_url": "http://x:1", "api_password": "p"}),
                         {"url": "http://x:1", "user": "", "password": "p"})


if __name__ == "__main__":
    unittest.main()
