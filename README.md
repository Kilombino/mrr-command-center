<p align="center"><img src="www/img/logo-192.png" width="140" alt=""></p>

# MRR Command Center

**Does the hashrate you rent actually reach your gateway?** A local web dashboard for
renting Blake2B hashrate on [MiningRigRentals](https://www.miningrigrentals.com) (MRR)
into your own [DATUM](https://github.com/OCEAN-xyz/datum_gateway) gateway, and checking
every rental against what the gateway really receives.

> Fork of [MarcanoFilms/mrr-blake2b-bot](https://github.com/MarcanoFilms/mrr-blake2b-bot)
> by [Marcano Trades](https://github.com/MarcanoFilms): the MRR client, the gateway view and
> the look of the MRR Command Center are his work. This fork turns it into a rental
> auditor with manual renting. His automatic rental bot is still in the code, switched
> off; see [Upstream bot](#upstream-bot-optional).

![Overview](docs/img/overview.jpg)

- **Every rental judged**: what you paid for, what MRR says it delivered and what your
  gateway accepted, with a statistical verdict and a face that tells you at a glance.
- **One worker per rental**, so rentals that all arrive through MRR's proxies can be told
  apart, mining to a payout address you fix.
- **Manual renting** from the market, with each rig's last 24 h of hashrate, its region,
  prices per TH and day and per hour, and a confirmation before anything is spent.
- **History and favourites**: finished rentals (MRR and PyBLØCK) are kept for 7 days with
  their final verdict, can be deleted by hand, and rigs that delivered are starred
  automatically.
- **Tickets**: a rental that underdelivers gets an "Abrir ticket" button with the evidence
  (paid vs MRR vs gateway) ready to paste, and an optional automatic notice.
- **Other markets**: PyBLØCK packages and orders, and hashrate from PyBLØCK market,
  p2phash, TideHash or RouteHash detected on the gateway.
- **Gateway**: every ASIC connected to your DATUM gateway (address, worker, hashrate,
  shares, kick button) and the gateway's log.

No dependencies beyond Python 3.10+ and the standard library. Screenshots below have
addresses, IPs, rental numbers and balances masked.

| Rentals | History |
|---|---|
| ![Rentals](docs/img/rentals.jpg) | ![History](docs/img/history.jpg) |

![Market](docs/img/market.jpg)

<p align="center"><img src="docs/img/ticket.jpg" width="540" alt="Ticket text"> <img src="docs/img/login.jpg" width="420" alt="Login"></p>

## How it works

### Rental audit

MRR shows how much hashrate *it* measured for each rental. The audit checks that
against what your own gateway accepted, so you can tell a weak rig, a lossy path or
a wrong number apart. For every active rental the dashboard shows three figures:

| | source |
|---|---|
| **paid** | the rental's advertised TH/s |
| **MRR says** | MRR's own average for the rental |
| **gateway** | accepted shares × share difficulty for the rental's worker, from the gateway's client page |

Cards: **Cotejo** (totals), **Hashrate que llega por alquiler** (stacked chart per
rental, complete 10-minute buckets, with the paid total as a dashed line) and
**N alquileres** (expected vs received, the address it mines to, the three bars, a face
and the verdict, a link to the rental on MRR and its extend control).

The face is happy when the gateway receives more than both what was paid and what MRR
reports, straight within 5 % of what was paid and sad below that. The verdict next to it
is the statistical one.

How it measures (details in the docstring of `audit.py`):

- Every gateway poll is stored in `audit.db` (SQLite, `retention_days`, default 7).
- Each stratum connection has its own cumulative share counter and MRR's proxies
  reconnect often, so the work of a rental is the sum of the per-connection
  increments. A connection born inside the window counts from zero.
- Work is counted as **shares × vardiff**, not from the cumulative difficulty column:
  recent gateways print that column with an SI prefix and three significant digits
  (`2.10E`), and on a long-lived connection it does not move for hours.
- **Verdict**: the expected number of shares for the *paid* hashrate over the window
  is `TH/s × 1e12 × seconds / (vardiff × 2^32)`. A rental is `corto` (short) only when
  the shares received are more than `sigma` (default 3) standard deviations below that,
  `de sobra` (over) when above, `cumple` (ok) otherwise. Testing against the error of
  what was *measured* instead would call a rental that delivered 0.03 % "ok" (one share
  has 100 % error).
- Until 10 shares are expected the verdict is `arrancando` (starting).

**One worker per rental.** The gateway can only tell rentals apart by the stratum
worker (the part of the user after the first dot): all rentals arrive through MRR's
proxies, from a few IPs, and one rental can show several user agents. If your pool
profile gives every rental the same worker, those rentals are shown as
`worker compartido` and not judged. With `audit.assign_workers: true` the dashboard
fixes that itself: every active rental whose worker is shared (or missing) gets its
pool user rewritten through the MRR API to `<address>.<worker_prefix><rental id>`
(`PUT /rental/<id>/pool/<priority>`). That changes the pool of a rental you already
paid for; it never rents or extends. Rigs reconnect within a minute. Work from before
the change cannot be split, so the rental is judged from that moment on.

Known limit: a connection that opens and closes between two polls (10 s) is not
counted, so the gateway figure can read slightly low for rigs that reconnect very often.

### Read-only mode

`"read_only": true` hides the rent and extend controls and makes the server refuse
`/api/rent`, `/api/rent-address` and `/api/extend` (quotes still work). Useful when the
MRR key has rent permission but you only want to watch, or the dashboard is shared.

### Manual renting

Nothing rents on its own: the market table has a **Rent** button per rig and every
rental waits for a confirmation that shows its cost, length, address and worker.

A rental made from the dashboard gets a worker of its own straight away: right after MRR
creates it, its pool user is rewritten to `<rent_address>.<worker_prefix><rental id>`.
`rent_address` is set from the market card (empty = the address of the pool profile), so
the payout address stays fixed while the worker changes with every rental. The audit
then measures it from its first share, and each rental card shows the address it mines
to, the hashrate expected and the hashrate received. Extend controls live in the rental
cards; the separate "active rentals" card is shown only when the audit is off.

Market prices are shown per TH per day in hundred-millionths of MRR's currency. Its names
are configurable (`coin_label`, `unit_label`), and `alt_price` can add the same price in a
second unit: a JSON URL and the path of the value saying how much of that unit one MRR coin
buys (`invert` for the reverse). Each market rig shows a sparkline of its last 24 h of
hashrate from MRR (`/rig/<id>/graph`, cached 10 min) against what it advertises, and its
region with a flag. Extend is greyed out when the rig's owner does not allow extensions or
the rental is already at the rig's maximum length; pressing it shows MRR's price for the
extension and waits for a confirmation.

### PyBLØCK rentals

Next to MRR the market card lists the packages of the
[PyBLØCK Market](https://b.pyblock.xyz:8443/api/market/v1.php/openapi.json) (public API v1,
`/rentals/packages`, cached 2 min) in its own purple box: TH/s, hours, units (each step
has its own price), total, price per TH per day and how it compares with MRR's market
(`last_10` plus MRR's fee, same unit). The promo, if any, is shown as a badge. A
**Probar gateway** button runs PyBLØCK's own gateway check (`/payout/gateway-test`)
without creating anything.

Renting is manual, like MRR: choose units and pay method (`ln`, `xbtln`, `xbt`), confirm
(total, TH/s, hours, gateway, payout address), and the dashboard sends the order with a
random `client_nonce` that it keeps, so a retry after a timeout or a rate limit is the same
order. PyBLØCK checks the gateway first; its refusal is shown as is. The answer is an
invoice (or an on-chain address and exact amount) shown with a QR code and its
countdown: **you pay it from your own wallet**, the dashboard never pays. Its status is
then read every 15 s while unpaid and every minute while it runs.

The gateway user is `<address>.<pyblock.worker_prefix><6 hex>`, so the order has a worker
of its own in the gateway table (labelled `PyBLOCK rental`). The address is
`pyblock.address`, else `rent_address`, else the MRR profile's.

The order id PyBLØCK returns **is the order's secret**. It is kept only in `pyblock.json`
(mode 600, gitignored), never logged, and never returned by the dashboard's API: orders
are referred to by a local random `ref`, and "ver en PyBLØCK" goes through a redirect.
PyBLØCK orders appear in the rentals card with a purple badge (contracted TH/s, what
PyBLØCK reports, what the gateway sees for its worker, time left, state), in the rented
TH/s totals and in `/api/overview` under `pyblock`. Created / paid / ended notices go to
the same Telegram chat, without the order id or the invoice.

### Tickets for rentals that underdeliver

MRR's API v2 has **no endpoint to open a support ticket, a dispute or a refund request**
(checked against [the API docs](https://www.miningrigrentals.com/apidocv2) on 20 Nov 2026).
Tickets are opened on MRR's site, from the rental's page or the ticket centre, and MRR's
[refund policy](https://www.miningrigrentals.com/helpcenter/For-Renters/35) reviews partial
delivery once the rental has ended, within 12 hours of the end; during a rental it asks
renters to contact the rig owner first. What the API does have is the rental's message
thread (`PUT /rental/<id>/message`), which the owner and MRR support read.

So the dashboard does this:

- **"Abrir ticket"** on every active rental with the sad face (below 95 % of what was paid,
  3 sigmas short) and on finished ones while MRR's 12-hour window is open (the button
  counts it down). It shows the evidence in English (advertised TH/s, what MRR reports,
  what the gateway accepted from the rental's own worker, shares against expected,
  window), copies it and opens the rental on MRR, where its ticket button is.
- **"ticket automático al terminar"** (off by default, a switch above the rentals) follows
  MRR's policy: it looks at an MRR rental only once it has **ended**, inside the 12-hour
  window, `audit.tickets.after_end_h` (8.5 h) after the end, because MRR reviews short
  rentals itself and its automatic refunds arrive at the end or 7.5–8.7 hours later. It
  flags the rental when the final delivery is below `max_pct` (100 %) **beyond statistical
  noise**: shares arrive as a Poisson process, so a rig that delivered exactly what was paid
  is measured within about 1/√(expected shares); the notice needs the shortfall to exceed
  `sigma` (3) of those deviations (a rig that delivered in full is wrongly flagged about
  once in 700 rentals) and at least `min_expected_shares`. It skips rentals MRR already
  refunded (the rental's `was_refunded`, or a `Credit/Refund` for it in
  `/account/transactions`). Then, once per rental, the evidence is stored in `audit.db`
  (table `tickets`) and Kilobot sends the ticket text with the time left to claim. A
  second box, **"publicar las pruebas al dueño"** (off), also posts it on the rental's
  message thread.
- **"avisar antes al dueño a medio alquiler"** (off): MRR asks renters to contact the owner
  first, so a running rental that is clearly short (past `min_fraction`, rig online, below
  `early_max_pct` 95 %, 3 sigmas) gets one polite message on its thread with the figures.
- Nothing is sent in `read_only`. The ticket dialog also tells you when MRR has already
  refunded the rental.

### Rentals from other markets

Hashrate that reaches the gateway from a rental market without an order in the panel is
listed in the rentals card as **detected** (orange or purple badge): source, worker, masked
address, user agent, TH/s now and over the last hour by shares, and since when it is seen.
It has no contract, so no face or verdict. Sources:

- **PyBLØCK market**: connections from PyBLØCK's proxy (user agent `pyblock-market/…` or its
  reverse DNS) that are not one of the PyBLØCK orders here.
- **Your own miners are never rentals**: `own_workers` (`"worker"` or `"address.worker"`)
  and `own_user_agents` in `config.json`, or the **"es mío"** button on a detected row. A rig
  you list on PyBLØCK market comes back to your gateway through its proxy when nobody rents
  it; it is shown apart as "tu minero (sin alquilar)" and can be un-marked there.
- `other_sources` in `config.json`: a name and substrings matched against the worker, user
  agent, reverse DNS and stratum user. Defaults: `p2phash`, `tidehash`, `routehash`.

Paid PyBLØCK orders that end now go to the history too, judged on their worker.

### History and favourites

When a rental stops being active, the audit judges it over its whole length (as far as
`retention_days` of samples go), reads its final price from MRR and keeps the result for
`history_days` (7): rig, end, length, paid / MRR / received TH/s, verdict and cost. A
rental that ends with an `ok` or `over` verdict at `favorite_pct` (95 %) or more of what
was paid stars its rig. Stars can also be set by hand in the market, which can be
filtered to show only them. Each entry has a 🗑 button to delete it now (with a
confirmation) instead of waiting for `history_days`. A rental that MRR's list leaves out
once (a glitch or its 100 calls/min limit) is no longer taken for finished while it runs.

### Smaller changes

- `datum_service_scope`: `"system"` shows the journal of a system unit
  (`journalctl -u`) instead of a user unit.
- IPv4-mapped client addresses (`::ffff:1.2.3.4`) are shown and reverse-resolved as IPv4.
- Clients whose worker is `<worker_prefix><digits>` are labelled `MRR proxy` even when
  the proxy has no reverse DNS.

## Install

```bash
git clone https://github.com/Kilombino/mrr-command-center ~/mrr-command-center
cd ~/mrr-command-center
./install.sh                   # config.json from the example, dashboard unit + launcher
nano config.json               # api_key, api_secret, profile_id, gateway password, own_addresses
python3 -I mrr_bot.py status   # checks the API key and balance
python3 -I mrr_bot.py pools    # checks the pool profile points at your gateway
systemctl --user enable --now mrr-dashboard.service
```

The dashboard listens on `dashboard_port` (7160) behind a password (a random one is
written to `config.json` on first start). On MRR you need an API key with *rentals* and
*balance* permissions (and *rent* to rent or extend from the dashboard), and a **pool
profile** (Account → Pools) whose pool is your gateway's public stratum address.
`profile_id` is the number of that profile.

If the gateway runs behind a VPN with port forwarding (the usual setup for a home node),
the stratum port MRR connects to is the forwarded one, not the local one.

`launcher/mrr-command-center.sh` opens the dashboard as a standalone window (Chromium app
mode); `install.sh` adds a desktop entry for it.

## Config reference

Keys marked *market* decide which rigs the market card lists (and the upstream bot rents); keys marked *bot* only matter for the upstream bot.

| key | default | meaning |
|---|---|---|
| `api_key`, `api_secret` | | MRR API credentials |
| `algo` | `blake2b` | MRR algo name |
| `currency` | `BTC` | balance / price currency |
| `profile_id` | | MRR pool profile that points at your gateway |
| `reserve_btc` | 0 | never spend below this confirmed balance (*bot*) |
| `max_spend_per_run_btc` | 0.002 | hard cap per pass (the timer interval is the cap window) (*bot*) |
| `max_concurrent_rentals` | 1 | rigs rented at the same time (*bot*) |
| `max_hours` / `min_hours` | 240 / 3 | rental length bounds (*market*) |
| `min_rpi` | 85 | rig performance index floor (0-100) (*market*) |
| `allow_new_rigs` | false | accept rigs with no rental history (*market*) |
| `min_perf_ratio` | 0.75 | last-30-min / advertised hashrate floor (*market*) |
| `max_price_premium` | 1.25 | ignore rigs above market `last_10` × this (*market*) |
| `price_tolerance` | 0.05 | ties within this fraction go to the longest rental (*bot*) |
| `fee_rate` | 0.03 | MRR renter fee added on top of the rig price |
| `extend_window_hours` | 2 | extend rentals ending within this window (*bot*) |
| `excluded_regions`, `excluded_rigs` | `[]` | blacklist by region code / rig id (*market*) |
| `telegram.token`, `telegram.chat_id` | | Telegram bot token + chat for rent/extend notifications |
| `dashboard_port` | 7160 | dashboard listen port (binds all interfaces) |
| `dashboard_password` | random | dashboard login |
| `own_addresses` | `[]` | your payout addresses, to tell your miners from foreign ones |
| `gateway.url/user/password` | `http://127.0.0.1:7158`, `oracle` | DATUM gateway admin page + digest auth |
| `datum_service` | `datum-convoy.service` | systemd unit whose journal the dashboard shows |
| `datum_service_scope` | `user` | `user` or `system` |
| `read_only` | false | the dashboard never rents nor extends |
| `bot_ui` | false | true: show the upstream bot’s controls, history and log |
| `rent_address` | `""` | payout address for rentals made from the dashboard, `""` = profile's |
| `coin_label` / `unit_label` | `BTC` / `sats` | names shown for MRR's currency and its 1e-8 unit |
| `alt_price` | `{}` | optional second price unit: `label`, `url`, `path`, `invert` |
| `pyblock.enabled` | true | show PyBLØCK packages and allow manual orders |
| `pyblock.api` | `https://b.pyblock.xyz:8443/api/market/v1.php` | PyBLØCK Market API base |
| `pyblock.gateway.host/port` | | public stratum of your DATUM gateway (required to order) |
| `pyblock.backup.host/port` | | optional second gateway |
| `pyblock.address` | `""` | payout address for PyBLØCK orders, `""` = `rent_address`, then the profile's |
| `pyblock.worker_prefix` | `pyb` | worker = prefix + 6 random hex per order |
| `audit.enabled` | true | record gateway samples and show the rental audit |
| `audit.assign_workers` | false | give each active rental its own worker through the MRR API |
| `audit.worker_prefix` | `mrr` | worker name = prefix + rental id |
| `audit.sigma` | 3 | standard deviations before calling a rental short |
| `audit.retention_days` | 7 | how long gateway samples are kept in `audit.db` |
| `audit.series_hours` / `audit.series_bucket_s` | 6 / 600 | per-rental chart span and bucket |
| `audit.history_days` | 7 | how long finished rentals stay in the history |
| `audit.favorite_pct` | 95 | % of the paid hashrate a finished rental needs to star its rig |
| `audit.tickets.max_pct` | 100 | after the end: flag only below this % of what was paid (and beyond `sigma`) |
| `audit.tickets.sigma` | `audit.sigma` (3) | standard deviations of shortfall needed after the end |
| `audit.tickets.min_expected_shares` | 200 | shares the paid hashrate should have brought in, to judge at all |
| `audit.tickets.after_end_h` / `window_h` | 8.5 / 12 | when to look after the end / MRR's claim window |
| `audit.tickets.min_fraction` / `min_observed_h` / `early_max_pct` | 0.25 / 1 / 95 | the early warning to the owner |
| `own_workers` / `own_user_agents` | `[]` | your own miners, never shown as rentals |
| `other_sources` | p2phash, TideHash, RouteHash | `[{"name": …, "match": [substrings]}]` for detected rentals |

## Upstream bot (optional)

Marcano's original rental bot is still here (`mrr_bot.py`): every 15 minutes it extends
rentals about to end and rents the rig that buys the most TH·hours with the budget. It is
off in this fork. To use it, set `"bot_ui": true` (controls, history and log in the
dashboard), run `./install.sh --with-bot` and read
[the upstream README](https://github.com/MarcanoFilms/mrr-blake2b-bot#how-it-decides) for
how it decides.

## Files

```
dashboard.py      MRR Command Center server
pyblock.py        PyBLØCK Market: packages, manual orders, order status
tickets.py        evidence text for MRR tickets and the automatic notice
tests/            unit tests (python3 -m unittest discover -s tests)
audit.py          rental audit: gateway samples, verdicts, per-rental worker, history, favourites
mrr_bot.py        MRR API client (and the upstream bot, off by default)
www/index.html    dashboard UI (single file, no build step)
www/img/          logo, favicon and login cover
docs/img/         screenshots for this README (personal data masked)
systemd/          mrr-dashboard.service (+ the upstream bot's units)
launcher/         Chromium app-mode launcher + .desktop template
config.json       your secrets and knobs (gitignored)
state.json        API nonce + action log (gitignored)
history.json      gateway hashrate history (gitignored)
audit.db          gateway samples, rental history, favourites, ticket log (gitignored)
pyblock.json      PyBLØCK orders with their secret ids (600, gitignored)
```

## Notes and gotchas

- MRR API nonces must be strictly increasing per key. API calls are serialised with a
  file lock (`.mrr.lock`) and the last nonce lives in `state.json`. Do not run two
  programs against the same key with different state files.
- MRR applies a renter fee on top of the rig price (3 % at the time of writing,
  `fee_rate`); the dashboard includes it in costs and hourly prices.
- The dashboard UI text is in Spanish for now. Pull requests translating it are welcome.
- Run the scripts with `python3 -I` (as the units do) so nothing in the working
  directory can shadow standard modules.

## License

MIT. Original bot, MRR client and dashboard by [Marcano Trades](https://github.com/MarcanoFilms).
Rental audit, manual renting, history and the other changes in this fork by
[Kilombino](https://github.com/Kilombino), same license.
