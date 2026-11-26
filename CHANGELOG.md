# Changelog

## 1.6.2 (26 Nov 2026)

- **With a single gateway, a pool profile pointing at another port is no longer taken for
  it.** Before, the only gateway was every profile's: choosing a profile that mines to
  `:23335` while the saved gateway is `:23334` moved PyBLØCK/P2Hash orders to `:23334`. Now
  such a profile shows "sin gateway guardado" (save that gateway to use it) and orders stay
  where they were. A gateway with no known stratum still takes every profile, as before.

## 1.6.1 (25 Nov 2026)

- **A pool profile pointing at a pool's DATUM port is flagged.** Port 28915 is where a
  gateway talks the DATUM protocol to its pool, not a stratum: a MRR pool profile pointing
  there sends rented hashrate to no gateway of yours. `profile_gateway()` returns
  `warn: "datum_pool"` (and no gateway) for it, and the packaged panel says so beside the
  profile instead of offering to save the pool as one of your gateways.

## 1.6.0 (24 Nov 2026)

- **Several DATUM gateways.** Besides the main one (the gateway API the panel always read:
  config `gateway`, or the one the platform wires in when packaged), the saved public
  stratums (`pyblock.gateways`) can carry a status page of their own (`api`: url, user,
  password): a second DATUM, or each pool's gateway of a PyBLØCK PATUM install (stratum
  23334, 23335…, status page 7152, 7153…, the same API as DATUM). The panel reads them all
  every 10 s, keeps each one's hashrate history (`history_gw.json`) and stores their
  connections in the audit, with the gateway's key in front of each connection id so two
  gateways never mix. A rental is measured by its worker on whichever gateway it reaches.
- **A rental shows where it mines.** The audit's passes already read every rental's pool:
  its host and port are now kept (`rental_worker.pool_host/pool_port`) and each rental shows
  `→ host:port` and its gateway. Without the audit the panel reads them itself, at most 10 a
  refresh and each again after 30 min (MRR's limit is 100 calls a minute). A rental belongs to
  the gateway whose stratum port it points at (and host, when two share a port); with a single
  gateway everything is that one, as before.
- **View selector at the top** ("Todos" and each gateway), shown when there is more than one:
  it filters the rentals, the KPIs, the hashrate chart, the ASICs table and the audit
  ("¿llega lo que pagas?", verdicts, per-rental chart) to one gateway; a gateway with nothing
  rented shows "nada alquilado", and one without a status page says so instead of showing
  another gateway's data. "Todos" adds them up. Kick acts on the client's own gateway.
- New collapsible card **"Tus gateways"**: each gateway with its stratum, status page, state
  (TH/s, ASICs) and whether PyBLØCK/P2Hash orders go to it; save or edit one (saving a saved
  stratum changes only that one: its name and page; an empty password keeps the saved one) or
  remove one. The main gateway can't be removed. `POST /api/gateways` (`api_url`, `api_user`,
  `api_password` besides 1.4.5's `action`, `gateway`, `name`; `primary` marks which saved
  stratum the main gateway's API belongs to). Status-page passwords live only in config.json
  (mode 600) and never appear in a response.
- `profile_gateway()`: where an MRR pool profile mines (its first pool, from MRR's list or
  `/account/profile/<id>`, kept 10 min) and which gateway that is, for the packaged app's
  profile selector.

## 1.5.0 (24 Nov 2026)

- **Price alerts by private Nostr message.** When a rig on MRR's market costs less than a
  threshold (the dashboard's unit per TH per day, MRR's fee included unless unticked), the
  panel sends a NIP-17 private message (a kind 14 rumor, sealed and gift-wrapped as kind 1059,
  NIP-44 encryption) from its own Nostr key to your npub. Any NIP-17 client (Amethyst, 0xchat,
  Primal...) shows it as a direct message: no Telegram, no central server. Optional filters:
  minimum TH/s, minimum rentable hours, online only (on by default), only ⭐ favourites;
  blacklisted rigs are never announced. Anti-spam: one message per check lists the rigs that
  newly crossed (up to 10, the rest counted); a rig is announced once while it stays below
  and again only after it went back above the threshold (or left the market) and crossed
  again. That state, and the panel's secret key, live in `price_alert.json` (mode 600,
  gitignored); the dashboard shows only the panel's npub ("Regenerar" makes a new one). A
  message that no relay accepts is tried again at the next check, and a failed MRR listing
  never re-arms the rigs.
- Settings in `price_alert` in config.json, edited from a new collapsible section "Avisos de
  precio (Nostr)" at the end, before the logs: on/off (off by default), your npub (or hex
  key; stored as npub, checked to be a point on the curve), threshold, fee, filters, check
  interval (5 min) and relays (by default relay.kilombino.com, nos.lol and relay.primal.net,
  each checked with a real send-fetch-decrypt round trip; your own NIP-17 inbox relays, kind
  10050, are added when you publish them). "Enviar prueba" sends a test message now and
  "Comprobar ahora" looks at the market at once. Hidden and refused in `read_only`.
- The market card and the alerts share one cached MRR listing (`market_rigs`), so the alerts
  add at most one listing per interval while nobody has the page open.
- `nostr.py` gains NIP-19 (`npub`, `parse_pubkey`, bech32).

## 1.4.5 (24 Nov 2026)

- **Several public stratums for PyBLØCK and P2Hash.** `pyblock.gateways` keeps a list of
  saved stratums (`{name, host, port}`, name optional), and `pyblock.gateway` stays the active
  one, so older configs and everything that reads it work unchanged (a config with only
  `gateway` is a list of one). A dropdown chooses which one new PyBLØCK orders and P2Hash
  rentals use (P2Hash when `p2hash.gateway` is empty, as before): for instance two ports of
  the same host running different gateways, one at a time, never mixed. Saving one with a
  name, using it and removing it (not the one in use) are in the PyBLØCK box of the market,
  or in the API key card of the packaged app. Only new orders change; running ones keep
  mining where they started. Local addresses are refused, as before. "Probar gateway"
  checks the one in use, and a cached result for another stratum is not shown for it.

## 1.4.4 (23 Nov 2026)

- **Blacklist in the market.** A rig goes on it by itself when a rental of it ends with the
  sad face (less than `blacklist_pct`, 95 %, of what was paid reached the gateway; mixed
  workers don't count) or when a ticket is opened for it: marked by hand, from the ticket
  dialog, or the automatic end-of-rental notice (the mid-rental message to the owner does
  not count). The market keeps showing it, in red with a "lista negra" tag that says why,
  and asks again before renting it; "ocultar 👎" hides them. 👎 next to the ⭐ puts a rig on
  the list or takes it off by hand, and the finished rentals section lists them with ✕.
  Taken off, a rig stays off until a new bad rental or ticket. The first start fills the
  list from the history already in `audit.db`.

## 1.4.3 (23 Nov 2026)

- **Refund amount in the history.** When MRR refunds a rental, the finished-rentals table
  shows how much (from the Credit/Refund entries of `/account/transactions` tied to the
  rental, read once every 10 minutes in a single call) in the coin, and the % of what was
  paid, instead of only a "refunded" badge.
- **Ticket column in the history.** MRR has no ticket API, so the panel records it: the
  "copy and open in MRR" button of the ticket dialog stores when it was used, each MRR
  row has a toggle to mark a ticket opened by hand on MRR's site (and to clear it), and
  rentals the automatic ticket acted on count too. The "Abrir ticket" button stops being
  offered once a ticket is marked or MRR has refunded. Marks live in `audit.db` and go
  with the history (7 days).
- **Shorter page.** Finished rentals, ASICs on the gateway, the market (MRR and PyBLØCK,
  and inside PyBLØCK its packages and P2Hash, each folding separately) and the logs are
  collapsible, title only by default; each browser remembers what is open. The header,
  KPIs, charts, comparison and active rentals stay as they were.
- **Total gateway hashrate in the sticky header**, always in sight; the header is more
  compact on phones.

## 1.4.2 (21 Nov 2026)

- **Rent on P2Hash from the panel.** P2Hash is PyBLØCK's hashrate market on Nostr: sellers
  list rigs with the PyBLØCK Hashrate Agent (signed NIP-99 listings with a BOLT12 offer),
  the buyer asks by NIP-17 and pays each tranche (10 min, say) in advance over its own
  wallet connection (NWC). The panel speaks the agent's protocol (`pyblock-hashrate/0`) with
  a small standard-library implementation of what it needs (BIP-340 signatures, NIP-44 v2,
  gift wraps, WebSocket, NWC), checked against nostr-tools and run end to end against the
  agent's own seller code. A pink box in the market card lists the rigs; a rental shows in
  the rentals card next to MRR's and PyBLØCK's with the same face, verdict and bars, the
  tranches paid with what the gateway measured in each, a countdown for the next payment
  and a Stop button; finished ones go to the history.
- **Nothing pays on its own by default.** Every tranche waits for a click ("Pagar tramo
  N", with the seller's grace period counting down and a Telegram notice). Paying tranches
  automatically needs the switch on, both caps set (sats per rental and per 24 h, 0 by
  default) and the box ticked for that rental. Either way a tranche is paid only if it is
  the next one of the running rental, for the listing's offer and price (+1 %), within the
  hours bought and the caps, and (from the 2nd on) the gateway saw at least half the
  advertised hash since the last payment, measured on the rental's own worker
  (`<address>.p2h<6 hex>`). The paying connection is pasted in the box, kept only in
  `config.json` (600) and never shown back; its budget is read before renting.
- **PyBLØCK market rentals made on their web**: "Añadir orden de PyBLØCK" takes the order's
  secret link (`market_minero.php?o=…`, read through `GET /orders/{secret}`) and follows it
  whole: rigs, the stratum user it mines with (so it is measured on its worker), status,
  refund. With only the miner's public id (`m·25f278f0`) the rig's current rental is
  followed as an estimate (verified TH/s, end and list price from `/rigs`), measured by
  address.
- **Detected connections without a worker are measured**: the gateway samples of a rental
  connection that sends only an address are stored under `@<source>:<address>`, so they get
  a real TH/s (since they arrived, or over the last hour) instead of "–", and PyBLØCK
  orders followed by address use the same key.

## 1.4.1 (20 Nov 2026)

- **The automatic ticket now follows MRR's policy**: it looks at a rental only after it has
  ended, inside MRR's 12-hour window, 8.5 h after the end (MRR reviews short rentals itself
  and refunds at the end or up to ~8.7 h later), and flags it when the final delivery is
  below 100 % beyond statistical noise (3 sigmas of the expected shares). Rentals MRR has
  already refunded are skipped (`was_refunded` or a Credit/Refund in
  `/account/transactions`). The Kilobot notice carries the ticket text and the time left;
  posting the evidence to the owner is a separate box (off).
- The mid-rental part is now only an optional early, polite message to the owner on the
  rental's thread (off by default), as MRR asks.
- **Your own miners are not rentals**: `own_workers` / `own_user_agents`, an "es mío" button
  on detected rows, and a separate "tu minero (sin alquilar)" line (a rig listed on
  PyBLØCK market comes back to your gateway through PyBLØCK's proxy when not rented).
- The history's "Abrir ticket" uses the same noise test, shows "reembolsado" / "avisado",
  and the ticket dialog says when MRR has already refunded the rental.

## 1.4.0 (20 Nov 2026)

- **Tickets for rentals that underdeliver.** MRR's API has no endpoint for tickets,
  disputes or refunds, so every MRR rental with the sad face gets an "Abrir ticket" button:
  the evidence (paid, what MRR says, what reached the gateway, shares against expected)
  ready to paste, copied, and the rental opened on MRR. Finished rentals keep the button
  while MRR's 12-hour claim window is open, with a countdown.
- **Automatic notice** (switch above the rentals, off by default): once per rental, while
  it runs with the rig online, past a quarter of its length and clearly short, the evidence
  is stored, a Telegram notice with the link is sent and, if a second box is ticked, the
  evidence is posted on the rental's message thread for the owner (the only write MRR's API
  allows here).
- **History**: a delete button on every entry (with a confirmation); paid PyBLØCK orders go
  to the history too; a rental MRR's list left out once is no longer taken for finished
  while it still runs (such entries are removed when it shows up again).
- **Other markets**: hashrate from PyBLØCK market and from configurable sources (p2phash,
  TideHash, RouteHash by default; matched on worker, user agent, reverse DNS or stratum
  user) is listed as "detected" with its TH/s now and over the last hour.
- Fixes: rig names MRR sends HTML-escaped are no longer escaped twice; the history no
  longer shows "BTC" instead of the configured coin name on first load; the extend box of
  a rental already past the rig's maximum no longer shows a negative number; renewal
  prices survive MRR's 100 calls/min limit (the last known ones are kept).
- Market: the rigs the filters drop are listed greyed with the reason under the usable
  ones, rentable all the same.

## 1.3.0 (15 Nov 2026)

- PyBLØCK orders made outside the panel can be added by pasting the order id or tracking
  link, measured on their worker or, without one, by payout address as an estimate.
- Unpaid PyBLØCK invoices are shown as such instead of as an expired rental.
- Extend: the cost is estimated from the rig's current price (MRR counted `getcost` as an
  extension request and refused the real one as too soon) and MRR's refusal is shown.

## 1.2.0 (15 Nov 2026)

- PyBLØCK rentals next to MRR: packages, manual orders with an invoice paid from your own
  wallet, status, and what each order delivers to the gateway.
- Price per TH/day paid and renewal price on every rental; faces, stars and verdicts for
  PyBLØCK rentals.

## 1.1.0 (13 Nov 2026)

- MRR balance as a pill in the header; minutes when less than an hour is left; favourite
  star under each rental's face; market columns RPI, Perf 24 h and Perf 30 min coloured.

## 1.0.0 (6 Nov 2026)

- First release: rental audit, manual renting, history and favourites, packaged for
  Umbrel and StartOS.
