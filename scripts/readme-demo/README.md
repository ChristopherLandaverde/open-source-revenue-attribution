# README demo GIF

Builds `docs/media/proof.gif`, the four-frame storyboard at the top of the README, from the
running app on the bundled synthetic sample (`sample_data/demo/`):

1. `touchpoints.csv` with the `q1-search` and `abm-launch` rows highlighted, beside the Data
   validation page the script reaches by clicking **Import the demo data set** on Import CSV.
2. The model comparison's USD table: first-touch and last-touch credit for those two campaigns.
3. The journey of opportunity *Northwind platform*: each touch, its eligibility and its credit
   under every model.
4. The `opportunities.csv` row with no `contact_id`, beside the first check on Data readiness.

Every number and phrase in the captions is read from the pages during the run and recorded in
`run.json`. The script raises `DemoDrift` if the app stops showing what a caption says (for
example if `q1-search` no longer gets all first-touch credit and none under last-touch, or the
readiness check no longer points at the opportunity with no contact). Update the captions in
`capture.py` when that happens.

| File | Role |
|---|---|
| `capture.py` | Drives the app with Playwright for Python, writes screenshots to `out/shots/`, the record to `run.json`, and renders the frames to `out/frames/` |
| `frame.html` | Stage and card styles: `static/css/tokens.css` colours on an ink stage (the logo tile), the app's vendored DM Sans and IBM Plex Mono |
| `build-gif.sh` | Two-pass palette ffmpeg assembly of `out/frames/` into the GIF |
| `run.json` | What the app showed in the last capture |

## Regenerate

Playwright is not a dependency of the app, so it is pulled in for the run only. The capture
re-imports the demo set through the UI, so use a throwaway database:

```sh
export DATABASE_URL=sqlite:///$TMPDIR/osra-demo.sqlite3
uv run python manage.py migrate
uv run python manage.py load_sample_data
DJANGO_SUPERUSER_PASSWORD=demo-pass uv run python manage.py createsuperuser --noinput --username demo --email demo@example.com
uv run python manage.py runserver &

uv run --with playwright==1.62.0 playwright install chromium   # skip if Chromium for 1.62.0 is installed
OSRA_USER=demo OSRA_PASSWORD=demo-pass uv run --with playwright==1.62.0 python scripts/readme-demo/capture.py
scripts/readme-demo/build-gif.sh                                # FFMPEG=/path/to/ffmpeg if it isn't on PATH
```

`BASE_URL` defaults to `http://127.0.0.1:8000`. Look at every frame in `out/frames/` before
committing. The GIF is 880 x 640, 4 to 4.5 s per frame, and should stay under 3 MB.
