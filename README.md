# mrr-blake2b-bot

Rents Blake2B hashrate on [MiningRigRentals](https://www.miningrigrentals.com) (MRR)
and points it at your own [DATUM](https://github.com/OCEAN-xyz/datum_gateway) gateway,
so rented rigs mine blocks that *you* build. Ships with the **MRR Command Center**,
a local web dashboard that shows the gateway's ASICs, your active rentals, the market,
the bot's decisions and lets you rent/extend by hand.

Built for the Bitcoin BLAKE2b fork (BIP-110), where the whole hashrate market lives on MRR
and renting is the cheapest way to get blocks. It works with any algo MRR sells, though:
set `algo` in the config.

```
python3 -I mrr_bot.py market     # cheapest usable rigs and what the budget buys
python3 -I mrr_bot.py plan       # dry run of the next action (never spends)
python3 -I mrr_bot.py run --live # spend (this is what the systemd timer runs)
python3 -I mrr_bot.py status     # balance + active rentals + last actions
python3 -I mrr_bot.py pools      # pool profile, DNS and reachability of your gateway
```

No dependencies beyond Python 3.10+ and the standard library.

## How it decides

Every pass (the timer runs one every 15 minutes) the bot:

1. Reads the confirmed MRR balance and computes the budget for this pass:
   `min(confirmed - reserve_btc, max_spend_per_run_btc)`.
2. **Extends** any active rental that ends within `extend_window_hours`, as long as
   the quote fits the budget. Continuity beats a new rental: the rig is already
   connected and proven.
3. If there are free slots (`max_concurrent_rentals`), fetches the Blake2B rig list
   (cheapest first) and keeps only rigs that are online, available, with
   `rpi >= min_rpi` (rigs with no history are skipped unless `allow_new_rigs`),
   whose last-30-min hashrate is at least `min_perf_ratio` of the advertised one,
   not in `excluded_regions` / `excluded_rigs`, and priced at most
   `max_price_premium` × the market's `last_10` price.
4. For each candidate, works out how many hours the budget buys (capped by the rig's
   max and `max_hours`) and the resulting **TH·hours**. The rig that buys the most
   TH·hours wins; among rigs within `price_tolerance` of the best, the **longest**
   rental wins (fewer gaps, fewer reconnects).
5. Rents with a price filter 1 % above the rig's rate (MRR rejects an exact match)
   and accounts for MRR's 3 % renter fee (`fee_rate`) so it never overspends.

Nothing is bought unless you pass `--live`. Every live action is appended to
`state.json` and, if configured, posted to Telegram.

## Dashboard: MRR Command Center

`dashboard.py` serves `www/index.html` plus a small JSON API on `dashboard_port`
(default 7160), protected by a password (cookie session, HTTP Basic also accepted).
A random password is written to `config.json` on first start if none is set.

It shows, refreshing every few seconds:

- **Gateway**: every stratum client on your DATUM gateway (address, worker, hashrate,
  shares, reject %, session age, user agent, rDNS), with MRR proxies and PyBLOCK
  rentals labelled, your own addresses highlighted (`own_addresses`) and a kick button.
  A 24 h hashrate history is kept in `history.json`.
- **Rentals**: active MRR rentals with advertised vs. delivered hashrate, time left,
  and one-click *quote / extend* for any number of hours.
- **Market**: the filtered rig list with what your budget buys, and a manual *rent*
  button (asks for confirmation and shows the estimated cost, fee included).
- **Bot**: timer state, next/last run, enable/disable/run-now, the last 15 actions,
  and live editing of the strategy knobs (written back to `config.json`).
- **Logs**: journal of `mrr-bot.service` and of your DATUM gateway unit.

The gateway data comes from the DATUM gateway's own admin pages (`gateway.url`,
digest auth with `gateway.user` / `gateway.password`). The bot/timer controls use
`systemctl --user`, so run the dashboard as the same user that owns the units.

`launcher/mrr-command-center.sh` opens the dashboard as a standalone window
(Chromium app mode, own profile so the login cookie persists); `install.sh` adds
a desktop entry for it.

## Install

```bash
git clone https://github.com/MarcanoFilms/mrr-blake2b-bot ~/mrr-bot
cd ~/mrr-bot
./install.sh            # creates config.json from the example, installs the systemd user units + launcher
nano config.json        # api_key, api_secret, profile_id, gateway password, dashboard password
python3 -I mrr_bot.py status
python3 -I mrr_bot.py pools
python3 -I mrr_bot.py plan
systemctl --user enable --now mrr-dashboard.service
systemctl --user enable --now mrr-bot.timer
```

On MRR you need an API key with *rentals* and *balance* permissions, and a
**pool profile** (Account → Pools) whose pool is your gateway's public stratum
address. `profile_id` is the number of that profile. `mrr_bot.py pools` resolves
the profile's host and checks the port is reachable.

If the gateway runs behind a VPN with port forwarding (the usual setup for a home
node), the stratum port MRR connects to is the forwarded one, not the local one.

## Config reference

| key | default | meaning |
|---|---|---|
| `api_key`, `api_secret` | | MRR API credentials |
| `algo` | `blake2b` | MRR algo name |
| `currency` | `BTC` | balance / price currency |
| `profile_id` | | MRR pool profile that points at your gateway |
| `reserve_btc` | 0 | never spend below this confirmed balance |
| `max_spend_per_run_btc` | 0.002 | hard cap per pass (the timer interval is the cap window) |
| `max_concurrent_rentals` | 1 | rigs rented at the same time |
| `max_hours` / `min_hours` | 240 / 3 | rental length bounds |
| `min_rpi` | 85 | rig performance index floor (0-100) |
| `allow_new_rigs` | false | accept rigs with no rental history |
| `min_perf_ratio` | 0.75 | last-30-min / advertised hashrate floor |
| `max_price_premium` | 1.25 | ignore rigs above market `last_10` × this |
| `price_tolerance` | 0.05 | ties within this fraction go to the longest rental |
| `fee_rate` | 0.03 | MRR renter fee added on top of the rig price |
| `extend_window_hours` | 2 | extend rentals ending within this window |
| `excluded_regions`, `excluded_rigs` | `[]` | blacklist by region code / rig id |
| `telegram.token`, `telegram.chat_id` | | bot token + chat for action notifications |
| `dashboard_port` | 7160 | dashboard listen port (binds all interfaces) |
| `dashboard_password` | random | dashboard login |
| `own_addresses` | `[]` | your payout addresses, to tell your miners from foreign ones |
| `gateway.url/user/password` | `http://127.0.0.1:7158`, `oracle` | DATUM gateway admin page + digest auth |
| `datum_service` | `datum-convoy.service` | systemd user unit whose journal the dashboard shows |

## Files

```
mrr_bot.py        the bot (CLI + MRR API client + strategy)
dashboard.py      MRR Command Center server
www/index.html    dashboard UI (single file, no build step)
systemd/          mrr-bot.service, mrr-bot.timer, mrr-dashboard.service
launcher/         Chromium app-mode launcher + .desktop template
assets/           icon
config.json       your secrets and knobs (gitignored)
state.json        nonce + action log (gitignored)
history.json      gateway hashrate history (gitignored)
```

## Notes and gotchas

- MRR API nonces must be strictly increasing per key. The bot and the dashboard
  share one key, so API calls are serialised with a file lock (`.mrr.lock`) and the
  last nonce lives in `state.json`. Do not run two copies against different state files.
- MRR applies a renter fee on top of the rig price (3 % at the time of writing). The
  bot assumes `fee_rate` when sizing rentals; the dashboard shows it in quotes.
- A rig's `rpi` can be the string `"new"`; those are skipped unless `allow_new_rigs`.
- The dashboard UI text is in Spanish for now. Pull requests translating it are welcome.
- Run the scripts with `python3 -I` (as the units do) so nothing in the working
  directory can shadow standard modules.

## License

MIT. Made by [Marcano Trades](https://github.com/MarcanoFilms).
