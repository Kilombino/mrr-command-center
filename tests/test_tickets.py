"""Auto-ticket, manual history deletion and rentals from other sources.

Run: python3 -m unittest discover -s tests
Nothing here talks to MRR or Telegram: the API and the notifier are stubs.
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import audit as audit_mod  # noqa: E402
import dashboard  # noqa: E402
import tickets  # noqa: E402

NOW = 1_800_000_000


def rental(**kw):
    r = {"id": 5900001, "rig_id": 42, "rig_name": "Big rig", "advertised_th": 10.0, "average_th": 9.8,
         "average_pct": "98", "start_unix": NOW - 10 * 3600, "end_unix": NOW + 14 * 3600, "length_h": 24,
         "left_h": 14, "paid": "0.00100000", "currency": "BTC", "ended": False, "rig_online": True}
    r.update(kw)
    return r


def analysis(**kw):
    a = {"worker": "mrr5900001", "shared": False, "verdict": "short", "delivered_th": 6.0, "pct": 60.0,
         "shares": 600, "expected_shares": 1000.0, "z": 12.6, "elapsed_h": 10.0, "observed_from": NOW - 10 * 3600,
         "connected": True}
    a.update(kw)
    return a


class FakeAudit:
    """The parts of audit.Audit that tickets.check uses, backed by a real (temporary) audit.db."""
    def __init__(self, a):
        self.tmp = tempfile.mkdtemp()
        self.real = audit_mod.Audit(self.tmp, {"audit": {"db": "audit.db"}})
        self.a = a

    def __getattr__(self, k):
        return getattr(self.real, k)

    def view(self, rentals):
        return {"rentals": [{"id": r["id"], "analysis": self.a} for r in rentals]}


class FakeAPI:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, method, endpoint, params=None, body=None):
        self.calls.append((method, endpoint, body))
        if self.fail:
            raise RuntimeError("HTTP 500")
        return [{"id": "5900001", "success": True}]


class EligibleTests(unittest.TestCase):
    s = dict(tickets.DEFAULTS)

    def ok(self, r=None, a=None):
        return tickets.eligible(r or rental(), a if a is not None else analysis(), self.s, NOW)[0]

    def test_sad_mid_rental(self):
        self.assertTrue(self.ok())

    def test_guards(self):
        self.assertFalse(self.ok(rental(ended=True)))
        self.assertFalse(self.ok(rental(left_h=0)))
        self.assertFalse(self.ok(rental(rig_online=False)))
        self.assertFalse(self.ok(rental(rig_online=None)))           # unknown is not online
        self.assertFalse(self.ok(a=analysis(verdict="ok")))
        self.assertFalse(self.ok(a=analysis(shared=True)))
        self.assertFalse(self.ok(a=analysis(delivered_th=9.6)))       # 96 %: not the sad face
        self.assertFalse(self.ok(rental(start_unix=NOW - 3600, end_unix=NOW + 23 * 3600)))   # 4 % elapsed
        self.assertFalse(self.ok(a=analysis(elapsed_h=0.5)))
        self.assertFalse(self.ok(a=analysis(expected_shares=50)))
        self.assertFalse(tickets.eligible(rental(), None, self.s, NOW)[0])

    def test_nothing_counts(self):
        self.assertTrue(self.ok(a=analysis(verdict="nothing", delivered_th=0.0, shares=0, connected=False)))


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.au = FakeAudit(analysis())
        self.sent = []
        self.notify = lambda c, text: self.sent.append(text)

    def run_check(self, api, cfg=None):
        return tickets.check(self.au, [rental()], lambda: api, self.notify, cfg or {}, log=lambda m: None, now=NOW)

    def test_off_by_default(self):
        api = FakeAPI()
        self.assertEqual(self.run_check(api), [])
        self.assertEqual((self.sent, api.calls), ([], []))
        self.assertEqual(tickets.switches(self.au), {"enabled": False, "message_owner": False})

    def test_once_per_rental_without_message(self):
        tickets.set_switches(self.au, enabled=True)
        api = FakeAPI()
        self.assertEqual(self.run_check(api), ["5900001"])
        self.assertEqual(self.run_check(api), [])                    # never twice
        self.assertEqual(api.calls, [])                              # message switch off: no write to MRR
        self.assertEqual(len(self.sent), 1)
        self.assertIn("#5900001", self.sent[0])
        self.assertIn("sin mensaje al dueño", self.sent[0])
        log = self.au.tickets()
        self.assertEqual(len(log), 1)
        self.assertIn("Advertised (paid for): 10.00 TH/s", log[0]["evidence"])
        self.assertIn("MRR's own average so far: 9.80 TH/s (98 %)", log[0]["evidence"])
        self.assertIn("6.00 TH/s (60 %)", log[0]["evidence"])

    def test_message_owner(self):
        tickets.set_switches(self.au, enabled=True, message_owner=True)
        api = FakeAPI()
        self.run_check(api)
        self.assertEqual(len(api.calls), 1)
        m, ep, body = api.calls[0]
        self.assertEqual((m, ep), ("PUT", "/rental/5900001/message"))
        self.assertIn("standard deviations below", body["message"])
        self.assertEqual(self.au.tickets()[0]["message_sent"], 1)
        self.assertIn("enviado al dueño", self.sent[0])

    def test_message_failure_still_notifies(self):
        tickets.set_switches(self.au, enabled=True, message_owner=True)
        self.run_check(FakeAPI(fail=True))
        t = self.au.tickets()[0]
        self.assertEqual(t["message_sent"], 0)
        self.assertIn("HTTP 500", t["error"])
        self.assertIn("no se pudo escribir", self.sent[0])

    def test_read_only_does_nothing(self):
        tickets.set_switches(self.au, enabled=True, message_owner=True)
        api = FakeAPI()
        self.assertEqual(self.run_check(api, {"read_only": True}), [])
        self.assertEqual((self.sent, api.calls), ([], []))


class HistoryTests(unittest.TestCase):
    def test_add_and_delete(self):
        au = audit_mod.Audit(tempfile.mkdtemp(), {"audit": {"db": "audit.db"}})
        au.add_history({"rental_id": "pyb-abc", "rig_name": "PyBLØCK 1× 10T", "start_unix": NOW - 3600,
                        "end_unix": NOW, "advertised_th": 10.0, "verdict": "ok", "paid": "5000",
                        "currency": "sats", "finished": int(time.time()), "source": "pyblock"})
        h = au.history()["history"]
        self.assertEqual((h[0]["rental_id"], h[0]["source"]), ("pyb-abc", "pyblock"))
        self.assertEqual(au.delete_history("nope"), 0)
        self.assertEqual(au.delete_history("pyb-abc"), 1)
        self.assertEqual(au.history()["history"], [])

    def test_old_db_gets_the_source_column(self):
        tmp = tempfile.mkdtemp()
        import sqlite3
        c = sqlite3.connect(os.path.join(tmp, "audit.db"))
        c.execute("""CREATE TABLE history (rental_id TEXT PRIMARY KEY, rig_id TEXT, rig_name TEXT, start_unix INTEGER,
            end_unix INTEGER, advertised_th REAL, mrr_average_th REAL, delivered_th REAL, pct REAL, verdict TEXT,
            shares INTEGER, expected_shares REAL, paid TEXT, currency TEXT, address TEXT, worker TEXT,
            finished INTEGER NOT NULL)""")
        c.execute("INSERT INTO history (rental_id, finished) VALUES ('1', ?)", (int(time.time()),))
        c.commit()
        c.close()
        au = audit_mod.Audit(tmp, {"audit": {"db": "audit.db"}})
        self.assertIsNone(au.history()["history"][0]["source"])     # old rows read as MRR


class TrackTests(unittest.TestCase):
    """A rental MRR's list leaves out once must not land in the history while it still runs."""
    def mrr_rental(self, rid, end):
        return {"id": rid, "rig": {"id": 7, "name": "r"}, "hashrate": {"advertised": {"hash": "10", "type": "th"}},
                "start": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(end - 86400)),
                "end": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(end)), "ended": False}

    def test_missing_once_is_not_finished(self):
        au = audit_mod.Audit(tempfile.mkdtemp(), {"audit": {"db": "audit.db"}})
        now = int(time.time())
        r = self.mrr_rental("77", now + 3600 * 5)

        class API:
            def call(self, m, ep, params=None, body=None):
                return dict(r, price={"paid": "0.1", "currency": "BTC"})
        au.track(API(), [r], now)
        au.track(API(), [], now + 120)                 # left out of the list once
        self.assertEqual(au.history()["history"], [])
        au.add_history({"rental_id": "77", "finished": now, "verdict": "ok"})   # an old wrong entry
        au.track(API(), [r], now + 240)                # running again: the wrong entry goes
        self.assertEqual(au.history()["history"], [])


class SourceTests(unittest.TestCase):
    SRC = dashboard.DASH_DEFAULTS["other_sources"]

    def test_classify(self):
        self.assertEqual(dashboard.classify_source({"useragent": "P2PHash-Agent/0.3"}, self.SRC), "p2phash rental")
        self.assertEqual(dashboard.classify_source({"host": "x.tidehash.com"}, self.SRC), "TideHash rental")
        self.assertEqual(dashboard.classify_source({"worker": "rig1", "useragent": "cgminer"}, self.SRC), "")

    def test_parse_clients_labels(self):
        row = ("<TR><TD>1/2</TD><TD>203.0.113.9</TD><TD>bc1qexample.{w}</TD><TD>abcdef01 12.0s</TD><TD>1s</TD>"
               "<TD>4096</TD><TD>1.0T (10)</TD><TD>0 (0) 0.00%</TD><TD>5.00 Th/s (3.0s)</TD><TD></TD><TD>{ua}</TD></TR>")
        html = row.format(w="p2p", ua="p2phash-agent/1.0") + row.format(w="kilo", ua="pyblock-market/1.0")
        dashboard.rdns_cache["203.0.113.9"] = ""
        cl = dashboard.parse_clients(html, [], self.SRC)
        self.assertEqual([c["label"] for c in cl], ["p2phash rental", "PyBLOCK rental"])


if __name__ == "__main__":
    unittest.main()
