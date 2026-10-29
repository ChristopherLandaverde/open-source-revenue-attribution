# Sample dataset (synthetic)

`sample.json` is a tiny, synthetic B2B dataset: 2 accounts, 3 contacts, 5 touchpoints,
3 opportunities. Load it with `uv run python manage.py load_sample_data` (safe to re-run).

## Hand-calculated first-touch results (90-day lookback, inclusive)

Eligible touchpoints occur in `[conversion - 90 days, conversion]`.

| Opp | Contact touches | Pipeline (conversion = created) | Won revenue (conversion = won) |
|---|---|---|---|
| opp-1, 12,000 USD | tp-1 03-02, tp-2 03-20 | created 04-01: tp-1, tp-2 eligible → **tp-1 q1-search** | won 05-15, window from 02-14: tp-1, tp-2 eligible → **tp-1 q1-search** |
| opp-2, 8,000 USD, open | tp-3 04-05 | created 04-12: → **tp-3 april-digest** | not won, excluded |
| opp-3, 5,000 USD | tp-4 2025-11-01, tp-5 05-01 | created 04-10: tp-4 is 160 days earlier (outside), tp-5 is after → **Unattributed** | won 06-01, window from 03-03: tp-4 outside, tp-5 eligible → **tp-5 may-webinar** |

Campaign totals:

- **Pipeline:** google / cpc / q1-search 12,000.00 · newsletter / email / april-digest 8,000.00 · Unattributed 5,000.00 — total 25,000.00 USD (= 12,000 + 8,000 + 5,000).
- **Won revenue:** google / cpc / q1-search 12,000.00 · partner / referral / may-webinar 5,000.00 — total 17,000.00 USD (= 12,000 + 5,000).

These numbers are asserted in `tests/test_sample_mode.py`.
