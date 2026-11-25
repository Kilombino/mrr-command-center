"""The DATUM gateways the panel knows about (1.6.0).

One of them is the main one: the gateway API the panel has always read (config "gateway",
or the one the platform wires in when packaged). The others are the saved public stratums
(`pyblock.gateways`) that carry a status page of their own: a second DATUM, or each pool's
gateway of a PyBLØCK PATUM install (stratum 23334, 23335…, status page 7152, 7153…).

A rental belongs to the gateway its MRR pool points at, matched by the stratum port (and the
host when two saved gateways share a port). With a single gateway everything is that one, so
a panel set up before 1.6.0 looks and behaves as before.
"""
import pyblock as pyb_mod

MAIN = "main"


def listing(c):
    """[{key, name, host, port, hostport, primary, api}] — `api` is {"url", "user", "password"}
    (the main one's is config "gateway"), None when that gateway has no status page set.
    Keys: "main" for the main gateway, its lowercase host:port for the others."""
    lst = pyb_mod.settings(c)["gateways"]
    main_api = dict(c.get("gateway") or {}) or None
    if not lst:
        return [{"key": MAIN, "name": "DATUM", "host": "", "port": 0, "hostport": "",
                 "primary": True, "api": main_api}]
    pi = pyb_mod.primary_index(lst)
    out = []
    for i, g in enumerate(lst):
        prim = i == pi
        hp = pyb_mod.hostport(g)
        out.append({"key": MAIN if prim else hp.lower(), "name": g.get("name") or ("DATUM" if prim else hp),
                    "host": g["host"], "port": int(g["port"]), "hostport": hp, "primary": prim,
                    "api": main_api if prim else (g.get("api") or None)})
    return out


def public(lst, status=None):
    """The listing for an API response: no passwords; `status` = {key: cache entry} adds
    whether its page answers, its hashrate and its subscribed clients."""
    out = []
    for g in lst:
        e = {k: g[k] for k in ("key", "name", "host", "port", "hostport", "primary")}
        e["has_api"] = bool(g.get("api"))
        e["api_url"] = (g.get("api") or {}).get("url") or ""
        st = (status or {}).get(g["key"]) or {}
        data = st.get("data") or {}
        e.update(ok=bool(data), error=st.get("error"), total_th=data.get("total_th"),
                 subscribed=data.get("subscribed"))
        out.append(e)
    return out


# The port of the DATUM protocol a gateway uses to talk to its pool (datum_pool_port in
# datum_gateway). It is no stratum: a pool profile of MRR pointing there sends the rented
# hashrate to no gateway of yours, and nothing reaches the panel.
DATUM_POOL_PORT = 28915


def pool_warning(host, port):
    """Why a pool profile cannot be one of your gateways, or None."""
    try:
        port = int(port or 0)
    except (TypeError, ValueError):
        return None
    return "datum_pool" if port == DATUM_POOL_PORT else None


def match(lst, host, port):
    """Key of the gateway a pool (host, port) points at, or None. One gateway: always it."""
    if len(lst) == 1:
        return lst[0]["key"]
    try:
        port = int(port or 0)
    except (TypeError, ValueError):
        return None
    same = [g for g in lst if g["port"] and g["port"] == port]
    if not same:
        return None
    if len(same) > 1:
        h = str(host or "").strip().lower()
        hit = next((g for g in same if g["host"].lower() == h), None)
        if hit:
            return hit["key"]
    return same[0]["key"]


def with_api(c, g):
    """A copy of the config whose "gateway" is `g`'s status page, for the gateway helpers."""
    return dict(c, gateway=dict(g["api"]))


def extra(lst):
    """The gateways other than the main one that have a status page to read."""
    return [g for g in lst if not g["primary"] and g.get("api")]
