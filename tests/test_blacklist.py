"""Blacklist: rigs whose rental ended with the sad face or got a ticket, taken off by hand."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import audit as audit_mod  # noqa: E402

NOW = int(time.time())
COLS = ("rental_id", "rig_id", "rig_name", "start_unix", "end_unix", "advertised_th", "mrr_average_th",
        "delivered_th", "pct", "verdict", "shares", "expected_shares", "paid", "currency", "address",
        "worker", "finished", "source")


def hist(**kw):
    """A finished rental (fake ids): 10 TH/s paid, 9 TH/s reached the gateway (90 %)."""
    h = {"rental_id": "1000001", "rig_id": "11", "rig_name": "Rig uno", "start_unix": NOW - 30 * 3600,
         "end_unix": NOW - 6 * 3600, "advertised_th": 10.0, "mrr_average_th": 9.9, "delivered_th": 9.0, "pct": 90.0,
         "verdict": "short", "shares": 9000, "expected_shares": 10000.0, "paid": "0.001", "currency": "BTC",
         "address": None, "worker": "mrr1000001", "finished": NOW - 6 * 3600, "source": "mrr"}
    h.update(kw)
    return h


def fresh():
    return audit_mod.Audit(tempfile.mkdtemp(), {"audit": {"db": "audit.db"}})


class BlacklistTest(unittest.TestCase):
    def test_ticket_mark_puts_the_rig_on_the_list(self):
        a = fresh()
        a.add_history(hist(pct=99.0, delivered_th=9.9, verdict="ok"))
        self.assertEqual(a.blacklist(), [])
        a.ticket_mark("1000001", True, "manual")
        bl = a.blacklist()
        self.assertEqual([(b["rig_id"], b["reasons"]) for b in bl], [("11", "ticket")])
        self.assertIn("blacklist", a.history())

    def test_backfill_takes_sad_rentals_and_tickets_but_not_good_or_shared(self):
        d = tempfile.mkdtemp()
        a = audit_mod.Audit(d, {"audit": {"db": "audit.db"}})
        a.add_history(hist())                                                     # sad: 90 %
        a.add_history(hist(rental_id="1000002", rig_id="12", pct=97.0, delivered_th=9.7, verdict="ok"))
        a.add_history(hist(rental_id="1000003", rig_id="13", verdict="shared"))   # mixed workers: no
        a.add_history(hist(rental_id="1000004", rig_id="14", pct=100.0, delivered_th=10.0, verdict="ok"))
        with a.db() as conn:
            conn.execute("INSERT INTO ticket_marks VALUES (?,?,?)", ("1000004", NOW, "manual"))
            conn.execute("DROP TABLE blacklist")
        a2 = audit_mod.Audit(d, {"audit": {"db": "audit.db"}})                  # the table is new again
        got = {b["rig_id"]: b["reasons"] for b in a2.blacklist()}
        self.assertEqual(got, {"11": "sad", "14": "ticket"})

    def test_taken_off_stays_off_until_something_new(self):
        a = fresh()
        a.add_history(hist())
        a.ticket_mark("1000001", True, "panel", now=NOW - 100)
        self.assertEqual(len(a.blacklist()), 1)
        a.blacklist_set("11", on=False, now=NOW)
        self.assertEqual(a.blacklist(), [])
        # the same ticket marked again (older than the removal) does not bring it back
        a.ticket_mark("1000001", False)
        a.ticket_mark("1000001", True, "manual", now=NOW - 50)
        self.assertEqual(a.blacklist(), [])
        # a new ticket after the removal does
        a.add_history(hist(rental_id="1000009", end_unix=NOW + 10))
        self.assertTrue(a.blacklist_ticket("1000009", now=NOW + 20))
        self.assertEqual([b["rig_id"] for b in a.blacklist()], ["11"])

    def test_reasons_merge_and_keep_the_worst_pct(self):
        a = fresh()
        with a.db() as conn:
            a._blacklist_put(conn, "11", "Rig uno", "sad", "1000001", 80.0, NOW)
            a._blacklist_put(conn, "11", None, "ticket", "1000002", 92.0, NOW)
        b = a.blacklist()[0]
        self.assertEqual((b["reasons"], b["pct"], b["rig_name"], b["rental_id"]), ("sad,ticket", 80.0, "Rig uno", "1000002"))

    def test_manual_on_and_off(self):
        a = fresh()
        a.blacklist_set("77", "Otro rig", True)
        self.assertEqual([(b["rig_id"], b["reasons"]) for b in a.blacklist()], [("77", "manual")])
        a.blacklist_set("77", on=False)
        self.assertEqual(a.blacklist(), [])
        a.blacklist_set("77", "Otro rig", True)       # by hand again: back on
        self.assertEqual(len(a.blacklist()), 1)
        with self.assertRaises(ValueError):
            a.blacklist_set("", on=True)


if __name__ == "__main__":
    unittest.main()
