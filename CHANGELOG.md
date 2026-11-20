# Changelog

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
