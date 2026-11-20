"""Auto-ticket: speak up for MRR rentals that underdeliver while they still run.

What MRR's API allows (checked against https://www.miningrigrentals.com/apidocv2 on
20 nov 2026): there is NO endpoint to open a support ticket, a dispute or a refund
request. Tickets are opened by hand, from the rental's page or from the ticket centre
(/tickets), and MRR's refund policy reviews partial delivery only once the rental has
ended (within 12 hours of the end). During a rental MRR asks renters to contact the rig
owner first, and the API does have that: PUT /rental/<id>/message, a message on the
rental's own thread, which the owner and MRR support read.

So the automatic part does what the API allows, and only when switched on:

  * at most once per rental, and only after enough of it has elapsed and the audit has
    enough shares to be sure (3 sigmas below what was paid for, and below 95 %),
  * only while the rental is active and MRR shows the rig online,
  * it keeps the evidence (paid vs MRR vs DATUM) in audit.db,
  * optionally posts that evidence on the rental's message thread (a second switch),
  * and sends a Kilobot notice with the link to open the ticket on MRR in one click.

The ticket itself stays one click away for the person: the dashboard pre-fills its text.
"""
import time

DEFAULTS = {
    "min_fraction": 0.25,         # part of the rental that must have elapsed
    "min_observed_h": 1.0,        # hours the audit must have watched the rental's own worker
    "min_expected_shares": 200,   # shares the paid hashrate should have brought in that time
    "max_pct": 95.0,              # only below this % of what was paid (the sad face)
}
MRR = "https://www.miningrigrentals.com"
KV_KEY = "autoticket"


def settings(cfg):
    out = dict(DEFAULTS)
    out.update(((cfg.get("audit") or {}).get("tickets")) or {})
    return out


def switches(audit):
    v = audit.kv_get(KV_KEY, {}) or {}
    return {"enabled": bool(v.get("enabled")), "message_owner": bool(v.get("message_owner"))}


def set_switches(audit, enabled=None, message_owner=None):
    cur = switches(audit)
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if message_owner is not None:
        cur["message_owner"] = bool(message_owner)
    audit.kv_set(KV_KEY, cur)
    return cur


def _fmt_utc(ts):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else "?"


def eligible(r, a, s, now):
    """(True, "") when an active MRR rental deserves its one ticket now, else (False, why)."""
    if r.get("ended") or not (r.get("left_h") or 0) > 0:
        return False, "not active"
    if r.get("rig_online") is not True:
        return False, "rig not online at MRR"
    if not a or a.get("shared"):
        return False, "no worker of its own"
    if a.get("verdict") not in ("short", "nothing"):
        return False, "not short"
    paid = float(r.get("advertised_th") or 0)
    if paid <= 0 or a.get("delivered_th") is None or a["delivered_th"] >= paid * s["max_pct"] / 100:
        return False, "not below the threshold"
    start, end = r.get("start_unix") or 0, r.get("end_unix") or 0
    if end <= start or (now - start) / (end - start) < s["min_fraction"]:
        return False, "too early in the rental"
    if (a.get("elapsed_h") or 0) < s["min_observed_h"] or (a.get("expected_shares") or 0) < s["min_expected_shares"]:
        return False, "not enough audit data yet"
    return True, ""


def evidence(r, a, now=None, finished=False):
    """English text for MRR (support reads English): what was paid, what MRR says, what arrived."""
    now = now or time.time()
    paid = float(r.get("advertised_th") or 0)
    lines = [f"Rental #{r.get('id')} (rig \"{r.get('rig_name') or ''}\" #{r.get('rig_id') or '?'}): "
             + ("it finished below the advertised hashrate." if finished else "it is delivering less than the advertised hashrate.")]
    lines.append(f"- Advertised (paid for): {paid:.2f} TH/s for {float(r.get('length_h') or 0):g} h"
                 + (f", paid {r.get('paid')} {r.get('currency') or ''}".rstrip() if r.get("paid") else "") + ".")
    if r.get("average_th") is not None:
        pct = f" ({float(r['average_pct']):.0f} %)" if r.get("average_pct") not in (None, "") else ""
        lines.append(f"- MRR's own average{'' if finished else ' so far'}: {float(r['average_th']):.2f} TH/s{pct}.")
    if a:
        z = a.get("z")
        lines.append(f"- Received at our DATUM gateway, counted from accepted shares (shares x share difficulty) on this"
                     f" rental's own worker since {_fmt_utc(a.get('observed_from'))}: {a['delivered_th']:.2f} TH/s"
                     f" ({(a.get('pct') or 0):.0f} %), {int(a.get('shares') or 0):,} accepted shares where the advertised"
                     f" hashrate should have produced {round(a.get('expected_shares') or 0):,}"
                     + (f" ({z:.1f} standard deviations below)" if z is not None and z > 0 else "") + ".")
    start, end = r.get("start_unix") or 0, r.get("end_unix") or 0
    if end > start:
        lines.append(f"- Rental window: {_fmt_utc(start)} to {_fmt_utc(end)}"
                     + ("" if finished else f"; {max(0.0, (now - start) / 3600):.1f} h elapsed") + ".")
    if not finished and r.get("rig_online") is not None:
        lines.append(f"- Rig online at MRR: {'yes' if r.get('rig_online') else 'no'}.")
    lines.append("Please check the rig. " + (
        "I ask for a review and a refund of the hashrate that was not delivered." if finished else
        "If it cannot deliver the advertised hashrate, I ask for the missing work to be made up"
        " or refunded when the rental ends."))
    return "\n".join(lines)


def notice(r, a, message_sent, error=None):
    """Spanish Kilobot notice, like the other rent alerts."""
    rid = r.get("id")
    mrr_part = (f" · MRR dice {float(r['average_th']):.2f}" + (f" ({float(r['average_pct']):.0f} %)" if r.get("average_pct") not in (None, "") else "")
                if r.get("average_th") is not None else "")
    msg = ("mensaje con las pruebas enviado al dueño por la API" if message_sent else
           ("no se pudo escribir al dueño: " + str(error)[:120]) if error else "sin mensaje al dueño (solo aviso)")
    return (f"🎫 MRR dashboard: el alquiler #{rid} \"{r.get('rig_name') or ''}\" entrega poco\n"
            f"pagado {float(r.get('advertised_th') or 0):.2f} TH/s{mrr_part} · llega al DATUM {a['delivered_th']:.2f} TH/s"
            f" ({(a.get('pct') or 0):.0f} %) · {int(a.get('shares') or 0):,} de {round(a.get('expected_shares') or 0):,} shares esperadas\n"
            f"{msg}.\nAbrir el ticket en MRR (el texto está en el panel, botón «Abrir ticket»): {MRR}/rental/{rid}\n"
            "MRR revisa los reembolsos al terminar el alquiler: reclama en las 12 h siguientes.")


def check(audit, rentals, api_factory, notify, cfg, log=print, now=None):
    """One pass over the active MRR rentals. Returns the rentals acted on.

    `rentals` are the dashboard's MRR rentals (with rig_online), `api_factory()` returns an MRR
    client (only used to post the optional message), `notify(cfg, text)` sends the Kilobot notice."""
    sw = switches(audit)
    if not sw["enabled"] or cfg.get("read_only"):
        return []
    s = settings(cfg)
    now = now or time.time()
    view = audit.view(rentals)
    by_id = {str(x["id"]): x for x in view["rentals"]}
    done = []
    for r in rentals:
        a = (by_id.get(str(r.get("id"))) or {}).get("analysis")
        ok, _ = eligible(r, a, s, now)
        if not ok:
            continue
        text = evidence(r, a, now)
        if not audit.ticket_claim(r["id"], now, a.get("verdict"), a.get("pct"),
                                  float(r["average_pct"]) if r.get("average_pct") not in (None, "") else None, text):
            continue    # this rental already had its one ticket
        sent, err = False, None
        if sw["message_owner"]:
            try:
                api = api_factory()
                res = api.call("PUT", f"/rental/{int(r['id'])}/message", body={"message": text})
                item = res[0] if isinstance(res, list) and res else res
                sent = not (isinstance(item, dict) and item.get("success") is False)
                if not sent:
                    err = "MRR refused the message"
            except Exception as e:    # the notice still goes out
                err = str(e)[:300]
        audit.ticket_update(r["id"], sent if sw["message_owner"] else None, err)
        log(f"[autoticket] rental {r['id']} {a.get('verdict')} {a.get('pct') or 0:.0f}% of paid"
            f" (MRR {r.get('average_pct')}%), owner message: {'sent' if sent else err or 'off'}")
        try:
            notify(cfg, notice(r, a, sent, err))
        except Exception:
            pass
        done.append(str(r["id"]))
    return done
