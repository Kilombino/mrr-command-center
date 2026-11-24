"""Price alerts (1.5.0): a private Nostr message when a rig on MRR's market is cheap.

When a rig on MRR's market costs less than your threshold (in the dashboard's unit per
TH per day, with MRR's fee by default), the panel sends you a NIP-17 private message
(kind 14 rumor, sealed and gift-wrapped as kind 1059, see nostr.py) from its own Nostr
key to your npub. Any NIP-17 client shows it as a direct message: Amethyst, 0xchat,
Primal... No Telegram, no central server.

  * One message per check, listing the rigs that newly crossed the threshold; a rig
    is announced once while it stays below it, and again only after it went back
    above it (or left the market: rented, offline, no longer listed) and crossed again.
    That state is kept in price_alert.json, so a restart does not repeat alerts.
  * The rigs come from the same MRR listing the market card uses (cached), so the
    alerts add at most one listing per check interval while nobody has the page open.
  * The panel's secret key lives only in price_alert.json (mode 600, gitignored);
    the dashboard shows its npub, never the key.

Settings ("price_alert" in config.json, edited from the dashboard):
  enabled, recipient (npub or hex), relays, threshold, with_fee, min_th, min_hours,
  online_only, favorites_only, interval_min.
"""
import json
import os
import threading
import time

import nostr

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "price_alert.json")
RIG_URL = "https://www.miningrigrentals.com/rigs/{}"
DEFAULT_RELAYS = ["wss://relay.kilombino.com", "wss://nos.lol", "wss://relay.primal.net"]
DEFAULTS = {
    "enabled": False,
    "recipient": "",            # npub or hex public key of whoever gets the alerts
    "relays": list(DEFAULT_RELAYS),
    "threshold": 0.0,           # dashboard unit (sats of MRR's coin) per TH per day
    "with_fee": True,           # compare the price MRR charges, its fee included
    "min_th": 0.0,              # only rigs advertising at least this many TH/s
    "min_hours": 0.0,           # only rigs that can be rented at least this long
    "online_only": True,
    "favorites_only": False,
    "interval_min": 5,
}
MAX_LISTED = 10                 # rigs listed in one message; the rest are counted
DM_RELAYS_TTL = 6 * 3600        # how long the recipient's kind 10050 relay list is kept


# ----------------------------------------------------------------------------- settings
def settings(raw_cfg):
    """The alert settings of a config dict, every key present, the recipient as hex ("" if unset
    or invalid; `recipient` keeps what was typed)."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in ((raw_cfg or {}).get("price_alert") or {}).items() if k in DEFAULTS})
    try:
        s["recipient_hex"] = nostr.parse_pubkey(s["recipient"]) if s["recipient"] else ""
    except ValueError:
        s["recipient_hex"] = ""
    return s


def _num(v, name, lo=0.0, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: no es un número")
    if x != x or x < lo or (hi is not None and x > hi):
        raise ValueError(f"{name}: fuera de rango")
    return x


def _bool(v):
    return v.strip().lower() in ("1", "true", "yes", "on", "sí", "si") if isinstance(v, str) else bool(v)


def clean(updates):
    """Validated settings from the dashboard (only the keys given). ValueError with the reason."""
    out = {}
    for k, v in (updates or {}).items():
        if k not in DEFAULTS:
            continue
        if k in ("enabled", "with_fee", "online_only", "favorites_only"):
            out[k] = _bool(v)
        elif k == "recipient":
            v = str(v or "").strip()
            if v:
                pk = nostr.parse_pubkey(v)
                v = nostr.npub(pk)      # always stored as npub
            out[k] = v
        elif k == "relays":
            items = v if isinstance(v, list) else str(v or "").replace(",", "\n").split("\n")
            relays = []
            for r in (str(x).strip() for x in items):
                if not r:
                    continue
                if not r.startswith(("wss://", "ws://")) or len(r) > 200 or " " in r:
                    raise ValueError(f"relay no válido: {r[:60]}")
                if r.rstrip("/") not in [x.rstrip("/") for x in relays]:
                    relays.append(r)
            if not relays:
                raise ValueError("hace falta al menos un relay")
            if len(relays) > 10:
                raise ValueError("como mucho 10 relays")
            out[k] = relays
        elif k == "threshold":
            out[k] = _num(v, "umbral")
        elif k in ("min_th", "min_hours"):
            out[k] = _num(v, "TH/s mínimos" if k == "min_th" else "horas mínimas")
        elif k == "interval_min":
            out[k] = int(_num(v, "intervalo", 1, 1440))
    return out


def check_ready(s):
    """Why alerts can't run with these settings ("" = they can)."""
    if not s.get("recipient_hex"):
        return "falta tu npub"
    if not s.get("threshold") or s["threshold"] <= 0:
        return "falta el umbral"
    if not s.get("relays"):
        return "faltan relays"
    return ""


# ----------------------------------------------------------------------------- the market
def offer(rig, currency, fee_rate, units):
    """A rig of MRR's listing as {id, name, th, price, price_fee, minh, maxh, online,
    available}, prices in sats of MRR's coin per TH per day; None if it has no price."""
    try:
        p = ((rig.get("price") or {}).get(currency)) or {}
        price = float(p.get("price") or 0)
        unit = ((rig.get("price") or {}).get("type") or "th").lower()
        if price <= 0 or unit not in units or not p.get("enabled"):
            return None
        hr = rig.get("hashrate") or {}
        adv = hr.get("advertised") or {}
        th = float(adv.get("hash") or 0) * units.get((adv.get("type") or "th").lower(), 0)
        sat = price / units[unit] * 1e8
        st = rig.get("status") or {}
        return {"id": str(rig["id"]), "name": str(rig.get("name") or rig["id"]), "th": th,
                "price": sat, "price_fee": sat * (1 + float(fee_rate or 0)),
                "minh": float(rig.get("minhours") or 0) or None,
                "maxh": float(rig.get("maxhours") or 0) or None,
                "online": bool(rig.get("online")),
                "available": (st.get("status") == "available") if isinstance(st, dict) else False}
    except (KeyError, TypeError, ValueError):
        return None


def matching(offers, s, favorites=(), blacklist=()):
    """The offers under the threshold that pass the filters, cheapest first."""
    favs, black = {str(x) for x in favorites}, {str(x) for x in blacklist}
    out = []
    for o in offers:
        if not o or not o["available"] or o["id"] in black:
            continue
        if s["online_only"] and not o["online"]:
            continue
        if s["favorites_only"] and o["id"] not in favs:
            continue
        if s["min_th"] and o["th"] < s["min_th"]:
            continue
        if s["min_hours"] and (o["maxh"] or 0) < s["min_hours"]:
            continue
        price = o["price_fee"] if s["with_fee"] else o["price"]
        if price <= s["threshold"]:
            out.append(dict(o, fav=o["id"] in favs))
    out.sort(key=lambda o: o["price_fee"])
    return out


def step(alerted, below, now):
    """Anti-spam. `alerted` = {rig id: {"at", "price"}} announced and still below; `below` =
    the matching offers of this check. Returns (to announce, new alerted). A rig that is no
    longer below (price up, gone, filtered out) is dropped, so a later crossing is new."""
    new_state, fresh = {}, []
    for o in below:
        if o["id"] in alerted:
            new_state[o["id"]] = alerted[o["id"]]
        else:
            fresh.append(o)
            new_state[o["id"]] = {"at": int(now), "price": round(o["price_fee"], 2)}
    return fresh, new_state


def _n(x):
    """A price as the dashboard writes it: no decimals over 100, thousands with a dot."""
    if x >= 100:
        return f"{x:,.0f}".replace(",", ".")
    return f"{x:.2f}".replace(".", ",")


def _th(x):
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def message(fresh, s, unit="sats", fee_rate=0.03, more=0):
    """The text of one alert (Spanish, from the reader's side)."""
    pct = f"{float(fee_rate or 0) * 100:g}".replace(".", ",")
    basis = f"con el {pct} % de MRR" if s["with_fee"] else f"sin el {pct} % de MRR"
    head = ("Tienes un rig" if len(fresh) == 1 and not more else f"Tienes {len(fresh) + more} rigs") + \
        f" en MRR por debajo de tu umbral ({_n(s['threshold'])} {unit}/TH/día, {basis}):"
    lines = [head, ""]
    for o in fresh:
        hours = ""
        if o.get("maxh"):
            hours = f" · hasta {o['maxh']:g} h" if not o.get("minh") else f" · de {o['minh']:g} a {o['maxh']:g} h"
        lines.append(f"{'⭐ ' if o.get('fav') else ''}{o['name']}")
        lines.append(f"{_n(o['price_fee'])} {unit}/TH/día con el {pct} % ({_n(o['price'])} sin él)"
                     f" · {_th(o['th'])} TH/s{hours}")
        lines.append(RIG_URL.format(o["id"]))
        lines.append("")
    if more:
        lines.append(f"…y {more} más: míralos en el mercado del panel.")
    return "\n".join(lines).rstrip()


# ----------------------------------------------------------------------------- sending
def publish(urls, ev, log=None, wait=8, connect=nostr.WebSocket):
    """Publish one event on every relay (each waits up to `wait` s to connect): [(url, ok, msg)]."""
    pool = nostr.Pool(urls, log=log, connect=connect)
    try:
        t0 = time.time()
        while time.time() - t0 < wait and not all(r.open for r in pool.relays):
            time.sleep(0.1)
        return pool.publish(ev, timeout=wait)
    finally:
        pool.close()


def dm_relays(pk, urls, log=None, wait=6, connect=nostr.WebSocket):
    """The recipient's NIP-17 inbox relays (kind 10050), [] if it has none or none answers."""
    pool = nostr.Pool(urls, log=log, connect=connect)
    got, done = [], threading.Event()

    def on(ev, _url):
        if ev.get("kind") == 10050 and ev.get("pubkey") == pk and nostr.verify_event(ev):
            got.append(ev)
            done.set()
    try:
        pool.sub("dmrelays", {"kinds": [10050], "authors": [pk], "limit": 1}, on)
        done.wait(wait)
        if not got:
            return []
        ev = max(got, key=lambda e: e.get("created_at", 0))
        return [t[1] for t in ev.get("tags", []) if isinstance(t, list) and len(t) > 1
                and t[0] == "relay" and str(t[1]).startswith(("wss://", "ws://"))][:5]
    finally:
        pool.close()


class PriceAlert:
    """State and sending. `get_settings()` gives settings(); `get_market()` gives
    (rigs, error) from the dashboard's cached listing; `get_lists()` gives (favorite ids,
    blacklisted ids); `ctx()` gives {"currency", "fee_rate", "unit", "units"}."""

    def __init__(self, get_settings, get_market, get_lists, ctx, path=STATE_PATH, log=None,
                 send=None, lookup=None):
        self.get_settings, self.get_market, self.get_lists, self.ctx = get_settings, get_market, get_lists, ctx
        self.path = path
        self.log = log or (lambda m: print(f"[alerts] {m}", flush=True))
        self._publish = send or (lambda urls, ev: publish(urls, ev, log=self.log))
        self._lookup = lookup or (lambda pk, urls: dm_relays(pk, urls, log=self.log))
        self.lock = threading.Lock()
        self.state = self._load()

    # --- state file (mode 600): the panel's key, what was announced, the last result
    def _load(self):
        try:
            with open(self.path) as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st.setdefault("sk", "")
        st.setdefault("alerted", {})
        st.setdefault("last", None)
        st.setdefault("dm_relays", {})
        return st

    def _save(self):
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.state, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def key(self, create=False):
        with self.lock:
            if not self.state["sk"] and create:
                self.state["sk"] = nostr.gen_sk()
                self._save()
            return self.state["sk"]

    def regenerate(self):
        with self.lock:
            self.state["sk"] = nostr.gen_sk()
            self._save()
        return self.npub()

    def npub(self):
        sk = self.state.get("sk")
        return nostr.npub(nostr.pubkey(sk)) if sk else ""

    def view(self):
        """For the dashboard: no secret key, ever."""
        s = self.get_settings()
        with self.lock:
            alerted = dict(self.state["alerted"])
            last = self.state["last"]
        return {"settings": {k: s[k] for k in DEFAULTS}, "recipient_ok": bool(s["recipient_hex"]),
                "ready": check_ready(s), "panel_npub": self.npub(), "below": len(alerted),
                "alerted": [{"id": k, **v} for k, v in sorted(alerted.items(), key=lambda kv: kv[1]["at"])][-20:],
                "last": last}

    # --- sending
    def _targets(self, s):
        """Configured relays plus the recipient's own inbox relays (kind 10050, cached)."""
        pk = s["recipient_hex"]
        hit = self.state["dm_relays"].get(pk)
        if not hit or time.time() - hit.get("at", 0) > DM_RELAYS_TTL:
            try:
                found = self._lookup(pk, s["relays"])
            except Exception as e:      # noqa: BLE001 - the inbox list is a nicety
                self.log(f"inbox relays of the recipient: {e}")
                found = (hit or {}).get("relays", [])
            hit = {"at": int(time.time()), "relays": found}
            with self.lock:
                self.state["dm_relays"] = {pk: hit}
        urls = list(s["relays"])
        for u in hit.get("relays", []):
            if u.rstrip("/") not in [x.rstrip("/") for x in urls]:
                urls.append(u)
        return urls

    def send(self, text, s=None):
        """Wrap and publish one message. Returns {"ok": n relays that took it, "relays": [...]}."""
        s = s or self.get_settings()
        if not s["recipient_hex"]:
            raise ValueError("falta tu npub")
        wrap = nostr.wrap_dm(self.key(create=True), s["recipient_hex"], text)
        res = self._publish(self._targets(s), wrap)
        out = {"ok": sum(1 for _, ok, _ in res if ok), "id": wrap["id"],
               "relays": [{"url": u, "ok": bool(ok), "msg": str(m)[:120]} for u, ok, m in res]}
        self.log(f"sent {wrap['id'][:12]}: {out['ok']}/{len(res)} relays "
                 + ", ".join(f"{r['url']}={'ok' if r['ok'] else r['msg']}" for r in out["relays"]))
        return out

    def test(self):
        s = self.get_settings()
        c = self.ctx()
        pct = f"{float(c['fee_rate'] or 0) * 100:g}".replace(".", ",")
        text = "Prueba del MRR Command Center: así te llegarán los avisos de precio."
        if s["threshold"]:
            text += (f"\nTu umbral ahora: {_n(s['threshold'])} {c['unit']}/TH/día"
                     f" ({'con' if s['with_fee'] else 'sin'} el {pct} % de MRR).")
        out = self.send(text, s)
        with self.lock:
            self.state["last"] = {"at": int(time.time()), "kind": "test", "ok": out["ok"],
                                  "relays": out["relays"]}
            self._save()
        return out

    # --- one check
    def check(self, now=None):
        """Look at the market once and send what crossed. Returns a short summary."""
        now = now or time.time()
        s = self.get_settings()
        if not s["enabled"]:
            with self.lock:     # switched off: forget what was announced, start clean next time
                if self.state["alerted"]:
                    self.state["alerted"] = {}
                    self._save()
            return {"skipped": "apagado"}
        why = check_ready(s)
        if why:
            return {"skipped": why}
        rigs, err = self.get_market()
        if rigs is None:            # a failed listing must not re-arm every rig
            return {"skipped": f"sin mercado: {err}"}
        c = self.ctx()
        favs, black = self.get_lists()
        offers = [offer(r, c["currency"], c["fee_rate"], c["units"]) for r in rigs]
        below = matching(offers, s, favs, black)
        with self.lock:
            fresh, new_state = step(self.state["alerted"], below, now)
        summary = {"at": int(now), "kind": "check", "below": len(below), "new": len(fresh)}
        if fresh:
            listed, more = fresh[:MAX_LISTED], max(0, len(fresh) - MAX_LISTED)
            try:
                out = self.send(message(listed, s, c["unit"], c["fee_rate"], more), s)
            except Exception as e:      # noqa: BLE001
                out = {"ok": 0, "relays": [], "error": str(e)[:160]}
            summary.update(ok=out["ok"], relays=out["relays"], rigs=[o["id"] for o in fresh])
            if not out["ok"]:
                # nobody took it: keep the old state so the same rigs are tried next time
                new_state = {k: v for k, v in new_state.items() if k not in {o["id"] for o in fresh}}
                summary["error"] = out.get("error") or "ningún relay lo aceptó"
        with self.lock:
            self.state["alerted"] = new_state
            if fresh or not self.state["last"] or self.state["last"].get("kind") != "check" \
                    or self.state["last"].get("below") != summary["below"]:
                self.state["last"] = summary
            self._save()
        return summary

    def loop(self, stop=None):
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                r = self.check()
                if r.get("new"):
                    self.log(f"{r['new']} rig(s) under the threshold, sent to {r.get('ok', 0)} relay(s)")
            except Exception as e:      # noqa: BLE001 - never kill the loop
                self.log(f"check failed: {e}")
            stop.wait(max(60, int(self.get_settings()["interval_min"]) * 60))
