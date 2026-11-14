"""PyBLØCK rentals: parsing of recorded answers and the order flow against a local mock.

Run: python3 -m unittest discover -s tests
The mock implements the documented shapes of the PyBLØCK Market API v1; nothing
here talks to the real service. Fixtures hold no addresses, hosts or order ids
of ours (the order id below is made up).
"""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pyblock  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
FAKE_ID = "11111111-2222-4333-8444-555555555555"
FAKE_ADDR = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"      # BIP-173 test vector, not ours
FAKE_BOLT11 = "lnbc1fakeinvoicefortestsonly"


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class ParseTests(unittest.TestCase):
    def test_packages(self):
        raw = load("pyblock_packages.json")
        cat = pyblock.parse_packages(raw, mrr_ref=2000)
        self.assertEqual(len(cat["packages"]), len(raw["packages"]))
        self.assertEqual(cat["promo"]["discount_pct"], 10)
        self.assertIn("xbtln", cat["pay_methods"])
        p = next(x for x in cat["packages"] if x["id"] == "p1x24")
        self.assertAlmostEqual(p["sat_th_day"], 2250.0)                 # 2250 sats / 1 TH / 1 day
        self.assertAlmostEqual(p["vs_mrr"], 0.125)
        two = next(s for s in p["steps"] if s["qty"] == 2)
        self.assertAlmostEqual(two["sat_th_day"], 4705 / 2)
        q = next(x for x in cat["packages"] if x["id"] == "p4_4x48")
        self.assertAlmostEqual(q["sat_th_day"], q["total_sats"] / 4.4 / 2)
        # available ones first, cheapest per TH/day first
        avail = [x["sat_th_day"] for x in cat["packages"] if x["available"]]
        self.assertEqual(avail, sorted(avail))

    def test_compare_recomputes(self):
        cat = pyblock.parse_packages(load("pyblock_packages.json"))
        self.assertIsNone(cat["packages"][0]["vs_mrr"])
        c2 = pyblock.compare(cat, 1000)
        self.assertIsNotNone(c2["packages"][0]["vs_mrr"])
        self.assertIsNone(cat["packages"][0]["vs_mrr"])                 # original untouched

    def test_order_created(self):
        o = pyblock.parse_order(load("pyblock_order_created.json"), now=1000)
        self.assertEqual(o["order_id"], FAKE_ID)
        self.assertEqual(o["status"], "pending_payment")
        self.assertEqual(o["invoice"], FAKE_BOLT11)
        self.assertEqual(o["expires_at"], 1600)

    def test_order_status_active(self):
        o = pyblock.parse_order(load("pyblock_order_active.json"), now=1000)
        self.assertEqual(o["status"], "active")
        self.assertAlmostEqual(o["live_ths"], 17.4)
        self.assertAlmostEqual(o["hashrate_ths"], 18)
        self.assertEqual(o["ends_at"], 1000 + 36000)

    def test_order_status_phs_and_xbt(self):
        o = pyblock.parse_order({"ok": True, "order": {"status": "pending_payment", "pay_method": "xbt",
                                 "xbt_address": "addr-x", "xbt_amount": "0.0012", "seconds_left": 60,
                                 "hashrate_phs": 0.0045, "live_hashrate_phs": 0}}, now=10)
        self.assertEqual(o["xbt_address"], "addr-x")
        self.assertEqual(o["expires_at"], 70)
        self.assertAlmostEqual(o["hashrate_ths"], 4.5)
        self.assertEqual(o["live_ths"], 0)

    def test_errors(self):
        self.assertEqual(pyblock._err_text({"ok": False, "errors": ["Order not found"]}), "Order not found")
        self.assertEqual(pyblock._err_text({"ok": False, "error": "invalid payout address"}), "invalid payout address")


class Mock(BaseHTTPRequestHandler):
    posts = []
    mode = "ok"            # ok | gateway | ratelimit | down
    status = "pending_payment"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/rentals/packages"):
            return self._send(200, load("pyblock_packages.json"))
        if self.path.endswith("/rentals/orders/" + FAKE_ID):
            o = load("pyblock_order_active.json")
            o["order"]["status"] = Mock.status
            return self._send(200, o)
        if "/payout/gateway-test" in self.path:
            return self._send(200, {"ok": False, "error": "could not connect to host:port"})
        return self._send(404, {"ok": False, "errors": ["Order not found"]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.posts.append(body)
        if Mock.mode == "gateway":
            return self._send(422, {"ok": False, "error": "Tu gateway no pasó el chequeo: could not connect"})
        if Mock.mode == "ratelimit":
            return self._send(429, {"ok": False, "error": "rate limited"})
        if Mock.mode == "down":
            return self._send(502, {"ok": False, "error": "bad gateway"})
        seen = sum(1 for p in Mock.posts if p.get("client_nonce") == body["client_nonce"]) > 1
        return self._send(200 if seen else 201, load("pyblock_order_created.json"))


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}/api/market/v1.php"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Mock.posts, Mock.mode, Mock.status = [], "ok", "pending_payment"
        self.dir = tempfile.mkdtemp()
        self.notices = []
        self.conf = {"rent_address": FAKE_ADDR, "fee_rate": 0.03,
                     "pyblock": {"api": self.base, "gateway": {"host": "gw.example.com", "port": 23334}}}
        self.p = pyblock.PyBlock(self.dir, lambda: self.conf, notify=lambda c, t: self.notices.append(t),
                                 gateway_clients=lambda: [{"worker": "x", "hashrate_th": 1.0}])

    def test_create_and_follow(self):
        o = self.p.create("p18x24", 2, "ln", "nonce-abcdef-0123456")
        self.assertEqual(o["status"], "pending_payment")
        self.assertEqual(o["payment"]["invoice"], FAKE_BOLT11)
        self.assertNotIn("order_id", o)
        sent = Mock.posts[0]
        self.assertEqual(sent["package"], "p18x24")
        self.assertEqual(sent["qty"], 2)
        self.assertEqual(sent["gateway"]["host"], "gw.example.com")
        self.assertTrue(sent["gateway"]["user"].startswith(FAKE_ADDR + ".pyb"))
        self.assertNotIn("backup", sent)
        # the state file holds the secret and is private
        path = os.path.join(self.dir, "pyblock.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path) as f:
            self.assertIn(FAKE_ID, f.read())
        # the overview never carries it
        view = json.dumps(self.p.view())
        self.assertNotIn(FAKE_ID, view)
        self.assertNotIn("nonce-abcdef-0123456", view)
        # same nonce: no second POST
        self.p.create("p18x24", 2, "ln", "nonce-abcdef-0123456")
        self.assertEqual(len(Mock.posts), 1)
        # paid -> notice, then completed -> notice; no secrets in any notice
        Mock.status = "active"
        rec = self.p._find(ref=o["ref"])
        rec["checked"] = 0
        self.p.refresh(rec, force=True)
        self.assertEqual(rec["status"], "active")
        Mock.status = "completed"
        rec["checked"] = 0
        self.p.refresh(rec, force=True)
        self.assertEqual(len(self.notices), 3)
        for t in self.notices:
            self.assertNotIn(FAKE_ID, t)
            self.assertNotIn(FAKE_BOLT11, t)
        self.assertIn("pagado", self.notices[1])
        pub = self.p.public(rec)
        self.assertNotIn("payment", pub)                               # no invoice once it is over

    def test_gateway_refused(self):
        Mock.mode = "gateway"
        with self.assertRaises(pyblock.OrderError) as cm:
            self.p.create("p1x24", 1, "ln", "nonce-gateway-000001")
        self.assertFalse(cm.exception.retryable)
        self.assertIn("gateway", str(cm.exception))
        self.assertEqual(self.p.state["orders"], [])                   # nothing left behind

    def test_retry_same_nonce(self):
        Mock.mode = "ratelimit"
        with self.assertRaises(pyblock.OrderError) as cm:
            self.p.create("p1x24", 1, "xbtln", "nonce-retry-00000001")
        self.assertTrue(cm.exception.retryable)
        self.assertEqual(len(self.p.state["orders"]), 1)
        Mock.mode = "ok"
        o = self.p.create("p1x24", 1, "xbtln", "nonce-retry-00000001")
        self.assertEqual(o["status"], "pending_payment")
        self.assertEqual({p["client_nonce"] for p in Mock.posts}, {"nonce-retry-00000001"})
        self.assertEqual(len(self.p.state["orders"]), 1)

    def test_validation(self):
        with self.assertRaises(pyblock.OrderError):
            self.p.create("p1x24", 9, "ln", "nonce-validation-0001")   # max_qty 2
        with self.assertRaises(pyblock.OrderError):
            self.p.create("p1x24", 1, "card", "nonce-validation-0002")
        with self.assertRaises(pyblock.OrderError):
            self.p.create("nope", 1, "ln", "nonce-validation-0003")
        with self.assertRaises(pyblock.OrderError):
            self.p.create("p1x24", 1, "ln", "short")
        self.conf["pyblock"]["gateway"] = {"host": "", "port": 0}
        with self.assertRaises(pyblock.OrderError):
            self.p.create("p1x24", 1, "ln", "nonce-validation-0004")
        self.assertEqual(Mock.posts, [])

    def test_gateway_test_error_text(self):
        r = self.p.gateway_test(force=True)
        self.assertFalse(r["ok"])
        self.assertIn("could not connect", r["error"])


if __name__ == "__main__":
    unittest.main()
