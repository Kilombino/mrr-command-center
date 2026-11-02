# mrr-bot

Rents Blake2B hashrate on MiningRigRentals with the account's confirmed BTC balance,
preferring the most TH-hours and, among near-equal buys, the longest rental.
Rigs are pointed at the pool profile in `config.json` (the DATUM gateway).

```
python3 -I mrr_bot.py market     # cheapest usable rigs and what the budget buys
python3 -I mrr_bot.py plan       # dry run of the next action
python3 -I mrr_bot.py run --live # spend (this is what the systemd timer runs)
python3 -I mrr_bot.py status     # balance + active rentals
python3 -I mrr_bot.py pools      # profile pools, DNS and reachability
```

Config knobs: `reserve_btc`, `max_spend_per_run_btc`, `max_concurrent_rentals`,
`max_hours`, `min_rpi`, `min_perf_ratio`, `max_price_premium`, `price_tolerance`,
`extend_window_hours`, `excluded_regions`, `excluded_rigs`, `allow_new_rigs`.

Timer: `systemctl --user enable --now mrr-bot.timer` (every 15 min, one pass each).
