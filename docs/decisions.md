# Decisions

Product and data-meaning decisions, newest first. Each links the issue where it was made.

## 2026-10-29 — Pipeline conversion time is the opportunity's created date

[#1](https://github.com/ChristopherLandaverde/open-source-revenue-attribution/issues/1)

- **Pipeline** reports measure the lookback window back from when the opportunity was **created** — they credit what generated the opportunity.
- **Won revenue** reports measure it back from when the opportunity was **won**.

The PRD did not state this; it was the M0 implementation's reading, confirmed by Christopher. Implemented in `reports/services.py`.
