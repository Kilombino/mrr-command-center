"""Price alerts by Nostr DM (1.5.0): settings, the market filter, the anti-spam state,
the message, and the gift wrap a NIP-17 client would open.

Run: python3 -m unittest discover -s tests
Nothing here talks to a relay or to MRR: publishing is a fake that records the events.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import alerts  # noqa: E402
import dashboard  # noqa: E402
import mrr_bot  # noqa: E402
import nostr  # noqa: E402

# NIP-19's own example key
NPUB = "npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6"
PK = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
CTX = {"currency": "BTC", "fee_rate": 0.03, "unit": "Spamsuits", "units": mrr_bot.UNIT}


def rig(rid, sat_th_day, th=100.0, online=True, status="available", maxh=24, minh=3, unit="th", enabled=True):
    """A rig as MRR's /rig listing gives it, priced in BTC per `unit` per day."""
    per_unit = sat_th_day / 1e8 * mrr_bot.UNIT[unit]
    return {"id": rid, "name": f"rig {rid}", "online": online, "status": {"status": status},
            "maxhours": maxh, "minhours": minh,
            "price": {"type": unit, "BTC": {"price": f"{per_unit:.12f}", "enabled": enabled}},
            "hashrate": {"advertised": {"hash": th, "type": "th"}}}


class Settings(unittest.TestCase):
    def test_defaults_and_recipient(self):
        s = alerts.settings({})
        self.assertFalse(s["enabled"])
        self.assertTrue(s["with_fee"] and s["online_only"])
        self.assertIn("wss://relay.kilombino.com", s["relays"])
        self.assertEqual(s["recipient_hex"], "")
        self.assertEqual(alerts.settings({"price_alert": {"recipient": NPUB}})["recipient_hex"], PK)
        self.assertEqual(alerts.settings({"price_alert": {"recipient": "npub1nope"}})["recipient_hex"], "")

    def test_npub_roundtrip(self):
        self.assertEqual(nostr.npub(PK), NPUB)
        self.assertEqual(nostr.parse_pubkey(NPUB), PK)
        self.assertEqual(nostr.parse_pubkey("nostr:" + NPUB), PK)
        self.assertEqual(nostr.parse_pubkey(PK.upper()), PK)
        for bad in (NPUB[:-1] + "7", "nsec1abc", "xyz", "0" * 63 + "5", ""):
            with self.assertRaises(ValueError):
                nostr.parse_pubkey(bad)

    def test_clean(self):
        c = alerts.clean({"recipient": PK, "threshold": "2500", "with_fee": "false", "min_th": 10,
                          "relays": "wss://a.example\nwss://a.example/\n\nwss://b.example", "interval_min": "15",
                          "unknown": 1})
        self.assertEqual(c["recipient"], NPUB)          # stored as npub
        self.assertEqual(c["threshold"], 2500.0)
        self.assertFalse(c["with_fee"])
        self.assertEqual(c["relays"], ["wss://a.example", "wss://b.example"])
        self.assertEqual(c["interval_min"], 15)
        self.assertNotIn("unknown", c)
        for bad in ({"threshold": -1}, {"threshold": "x"}, {"relays": "https://a.example"}, {"relays": ""},
                    {"recipient": "npub1bad"}, {"interval_min": 0}):
            with self.assertRaises(ValueError):
                alerts.clean(bad)

    def test_ready(self):
        self.assertEqual(alerts.check_ready(alerts.settings({})), "falta tu npub")
        self.assertEqual(alerts.check_ready(alerts.settings({"price_alert": {"recipient": NPUB}})), "falta el umbral")
        self.assertEqual(alerts.check_ready(alerts.settings({"price_alert": {"recipient": NPUB, "threshold": 1}})), "")


class Market(unittest.TestCase):
    def offers(self, *rigs):
        return [alerts.offer(r, "BTC", 0.03, mrr_bot.UNIT) for r in rigs]

    def test_offer_units(self):
        o = alerts.offer(rig(7, 2000, unit="gh"), "BTC", 0.03, mrr_bot.UNIT)
        self.assertAlmostEqual(o["price"], 2000, places=3)
        self.assertAlmostEqual(o["price_fee"], 2060, places=3)
        self.assertEqual((o["id"], o["th"], o["maxh"], o["minh"]), ("7", 100.0, 24.0, 3.0))
        self.assertIsNone(alerts.offer(rig(8, 2000, enabled=False), "BTC", 0.03, mrr_bot.UNIT))
        self.assertIsNone(alerts.offer({"id": 9}, "BTC", 0.03, mrr_bot.UNIT))

    def test_threshold_with_and_without_fee(self):
        s = alerts.settings({"price_alert": {"threshold": 2050}})
        self.assertEqual(alerts.matching(self.offers(rig(1, 2000)), s), [])         # 2060 with the fee
        s["with_fee"] = False
        self.assertEqual([o["id"] for o in alerts.matching(self.offers(rig(1, 2000)), s)], ["1"])

    def test_filters(self):
        s = alerts.settings({"price_alert": {"threshold": 5000}})
        offers = self.offers(rig(1, 1000), rig(2, 900, online=False), rig(3, 800, status="rented"),
                             rig(4, 700, th=5), rig(5, 600, maxh=4), rig(6, 500))
        self.assertEqual([o["id"] for o in alerts.matching(offers, s, blacklist=["6"])], ["5", "4", "1"])
        s["online_only"] = False
        self.assertIn("2", [o["id"] for o in alerts.matching(offers, s)])
        s.update(min_th=10, min_hours=6)
        self.assertEqual([o["id"] for o in alerts.matching(offers, s)], ["6", "2", "1"])
        s["favorites_only"] = True
        got = alerts.matching(offers, s, favorites=["1"])
        self.assertEqual([(o["id"], o["fav"]) for o in got], [("1", True)])


class AntiSpam(unittest.TestCase):
    def test_cross_stay_rearm_recross(self):
        a, b = {"id": "1", "price_fee": 100}, {"id": "2", "price_fee": 200}
        fresh, st = alerts.step({}, [a, b], 1000)
        self.assertEqual([o["id"] for o in fresh], ["1", "2"])                 # cross
        fresh, st = alerts.step(st, [a, b], 1300)
        self.assertEqual(fresh, [])                                           # stays below: quiet
        self.assertEqual(st["1"]["at"], 1000)
        fresh, st = alerts.step(st, [b], 1600)                                # 1 went up / left
        self.assertEqual((fresh, sorted(st)), ([], ["2"]))
        fresh, st = alerts.step(st, [a, b], 1900)                             # 1 crossed again
        self.assertEqual([o["id"] for o in fresh], ["1"])


class Message(unittest.TestCase):
    def test_text(self):
        s = alerts.settings({"price_alert": {"threshold": 2500}})
        o = {"id": "123", "name": "Big rig", "th": 1234.5, "price": 2000.0, "price_fee": 2060.0,
             "minh": 3.0, "maxh": 24.0, "fav": True}
        t = alerts.message([o], s, "Spamsuits", 0.03)
        self.assertTrue(t.startswith("Tienes un rig en MRR por debajo de tu umbral (2.500 Spamsuits/TH/día, con el 3 % de MRR):"))
        self.assertIn("⭐ Big rig", t)
        self.assertIn("2.060 Spamsuits/TH/día con el 3 % (2.000 sin él) · 1.234,5 TH/s · de 3 a 24 h", t)
        self.assertIn("https://www.miningrigrentals.com/rigs/123", t)
        t = alerts.message([o, dict(o, id="9", fav=False)], dict(s, with_fee=False), "sats", 0.03, more=4)
        self.assertTrue(t.startswith("Tienes 6 rigs en MRR por debajo de tu umbral (2.500 sats/TH/día, sin el 3 % de MRR):"))
        self.assertTrue(t.endswith("…y 4 más: míralos en el mercado del panel."))


class FakeRelays:
    def __init__(self, ok=True):
        self.events, self.urls, self.ok = [], [], ok

    def __call__(self, urls, ev):
        self.urls.append(list(urls))
        self.events.append(ev)
        return [(u, self.ok, "" if self.ok else "blocked") for u in urls]


class PriceAlertRuns(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "price_alert.json")
        self.recv_sk = nostr.gen_sk()
        self.cfg = {"price_alert": {"enabled": True, "recipient": nostr.npub(nostr.pubkey(self.recv_sk)),
                                    "threshold": 2500, "relays": ["wss://r1.example", "wss://r2.example"]}}
        self.market = [rig(1, 2000), rig(2, 3000), rig(3, 2400)]
        self.relays = FakeRelays()

    def make(self, lookup=lambda pk, urls: ["wss://inbox.example", "wss://r1.example/"]):
        return alerts.PriceAlert(lambda: alerts.settings(self.cfg), lambda: (self.market, None),
                                 lambda: (["3"], []), lambda: CTX, path=self.path, log=lambda m: None,
                                 send=self.relays, lookup=lookup)

    def opened(self, ev):
        got = nostr.unwrap_dm(ev, self.recv_sk)
        self.assertIsNotNone(got)
        return got

    def test_sends_once_then_rearms_and_survives_restart(self):
        pa = self.make()
        r = pa.check(now=1000)
        self.assertEqual((r["below"], r["new"], r["ok"]), (2, 2, 3))
        self.assertEqual(self.relays.urls[0], ["wss://r1.example", "wss://r2.example", "wss://inbox.example"])
        sender, rumor = self.opened(self.relays.events[0])
        self.assertEqual(sender, nostr.pubkey(pa.key()))
        self.assertEqual(rumor["kind"], 14)
        self.assertEqual(rumor["tags"], [["p", nostr.pubkey(self.recv_sk)]])
        self.assertNotIn("sig", rumor)                                        # NIP-17: the rumor is unsigned
        self.assertIn("⭐ rig 3", rumor["content"])
        self.assertIn("rig 1", rumor["content"])
        self.assertEqual(pa.check(now=1300)["new"], 0)                        # stays below: nothing
        self.assertEqual(len(self.relays.events), 1)
        pa2 = self.make()                                                     # restart
        self.assertEqual(pa2.check(now=1600)["new"], 0)
        self.market[0] = rig(1, 2600)                                         # 1 goes up
        self.assertEqual(pa2.check(now=1900)["new"], 0)
        self.market[0] = rig(1, 2100)                                         # ...and crosses again
        r = pa2.check(now=2200)
        self.assertEqual((r["new"], r["rigs"]), (1, ["1"]))
        self.assertIn("rig 1", self.opened(self.relays.events[-1])[1]["content"])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_failed_send_is_retried_and_failed_listing_does_not_rearm(self):
        self.relays.ok = False
        pa = self.make()
        r = pa.check(now=1000)
        self.assertEqual((r["new"], r["ok"]), (2, 0))
        self.assertIn("error", r)
        self.relays.ok = True
        self.assertEqual(pa.check(now=1300)["new"], 2)                        # tried again
        pa.get_market = lambda: (None, "HTTP 500")
        self.assertIn("skipped", pa.check(now=1600))
        pa.get_market = lambda: (self.market, None)
        self.assertEqual(pa.check(now=1900)["new"], 0)                        # not re-armed by the outage

    def test_off_and_not_ready(self):
        pa = self.make()
        pa.check(now=1000)
        self.cfg["price_alert"]["enabled"] = False
        self.assertEqual(pa.check(now=1300), {"skipped": "apagado"})
        self.assertEqual(pa.state["alerted"], {})                             # switched off: forgotten
        self.cfg["price_alert"].update(enabled=True, threshold=0)
        self.assertEqual(pa.check(now=1600), {"skipped": "falta el umbral"})

    def test_many_rigs_one_message(self):
        self.market = [rig(i, 1000 + i) for i in range(1, 15)]
        r = self.make().check(now=1000)
        self.assertEqual((r["new"], len(self.relays.events)), (14, 1))
        self.assertIn("…y 4 más", self.opened(self.relays.events[0])[1]["content"])

    def test_view_never_shows_the_key_and_test_message(self):
        pa = self.make()
        out = pa.test()
        self.assertEqual(out["ok"], 3)
        self.assertIn("Prueba del MRR Command Center", self.opened(self.relays.events[0])[1]["content"])
        v = json.dumps(pa.view())
        self.assertNotIn(pa.key(), v)
        self.assertIn(pa.npub(), v)
        old = pa.npub()
        self.assertNotEqual(pa.regenerate(), old)

    def test_inbox_lookup_failure_still_sends(self):
        def boom(pk, urls):
            raise OSError("no route")
        r = self.make(lookup=boom).check(now=1000)
        self.assertEqual(r["ok"], 2)
        self.assertEqual(self.relays.urls[0], ["wss://r1.example", "wss://r2.example"])


class Dashboard(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cfgp = os.path.join(self.d, "config.json")
        with open(self.cfgp, "w") as f:
            json.dump({"api_key": "k", "api_secret": "s", "price_alert": {"threshold": 10}}, f)
        self.p = mock.patch.object(mrr_bot, "CONFIG_PATH", self.cfgp)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_edit_alerts(self):
        with self.assertRaises(RuntimeError):
            dashboard.edit_alerts({"enabled": True})                          # no npub yet
        m = dashboard.edit_alerts({"recipient": PK, "enabled": True, "relays": "wss://x.example"})
        self.assertTrue(m["enabled"])
        with open(self.cfgp) as f:
            raw = json.load(f)
        self.assertEqual(raw["price_alert"], {"threshold": 10, "recipient": NPUB, "enabled": True,
                                              "relays": ["wss://x.example"]})
        self.assertEqual(stat.S_IMODE(os.stat(self.cfgp).st_mode), 0o600)
        self.assertEqual(raw["api_key"], "k")                                 # the rest untouched

    def test_market_listing_is_shared(self):
        calls = []

        class Api:
            state = {}

            def rigs(self, algo):
                calls.append(algo)
                return [rig(1, 100)]
        dashboard._market_rigs.update(at=0, rigs=None, error=None)
        with mock.patch.object(dashboard, "mrr_api", lambda c: Api()), \
                mock.patch.object(mrr_bot, "save_state", lambda s: None), \
                mock.patch.object(dashboard, "cfg", lambda: {"algo": "blake2b"}):
            self.assertEqual(len(dashboard.market_rigs(300)[0]), 1)
            dashboard.market_rigs(300)
            dashboard.market_rigs(300, Api())
            self.assertEqual(len(calls), 1)                                   # one fetch for all three
        dashboard._market_rigs.update(at=0, rigs=None, error=None)


if __name__ == "__main__":
    unittest.main()
