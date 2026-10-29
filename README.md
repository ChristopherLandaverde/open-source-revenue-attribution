# Open Source Revenue Attribution

Self-hostable, auditable B2B revenue attribution. See which marketing touchpoints are
**associated** with pipeline and closed revenue under a clearly named attribution model,
and inspect the math behind every number.

Attribution here is a reporting model. It shows how a stated rule assigns credit; it does
not estimate causal impact or incrementality.

**Status:** M1 (contracts and fixtures). A documented import and event contract
([docs/contract.md](docs/contract.md)) enforced by a validator, a synthetic B2B demo fixture
with hand-calculated expected results, one model (first-touch), and two server-rendered pages:
the report and the data validation report. See [docs/prd.md](docs/prd.md) for product scope
and [docs/project-management-plan.md](docs/project-management-plan.md) for milestones.

## Quick start (fresh clone to running app with sample data)

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker (for Postgres).

```sh
git clone https://github.com/ChristopherLandaverde/open-source-revenue-attribution.git
cd open-source-revenue-attribution
uv sync
cp .env.example .env
docker compose up -d --wait db
uv run python manage.py migrate
uv run python manage.py load_sample_data
uv run python manage.py runserver
```

`load_sample_data` validates the demo fixture first: it loads the accepted rows and lists
the rows it refused, with reason codes (the fixture contains a few invalid rows on purpose).
Add `--strict` to refuse the whole import on any error, or `--path <dir>` to load your own
CSV files in the [import format](docs/contract.md#2-csv-import-files).

Open http://127.0.0.1:8000/ for the first-touch report. Switch between "Pipeline" and "Won
revenue" to swap the results table in place (HTMX). http://127.0.0.1:8000/validation/ shows
the last import's validation report: counts per file, refused rows and warnings.

### Without Docker (SQLite)

Use the same steps, but skip `docker compose` and set the SQLite URL in `.env`:

```sh
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite:///db.sqlite3|' .env
```

## Checks

```sh
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Tests always use in-memory SQLite (`config/settings_test.py`) and need no `.env` or Docker.
CI (`.github/workflows/ci.yml`) runs the same commands.

## Layout

| Path | What |
|---|---|
| `attribution/` | Pure-Python attribution models and types. No Django imports (enforced by a test). |
| `contracts/` | Pure-Python import/event contract validator and reason codes. No Django imports. |
| `reports/` | Django app: records, `load_sample_data` command, report and validation views. |
| `config/` | Django project settings (read from environment / `.env`). |
| `sample_data/demo/` | Synthetic demo fixture (CSV) with hand-calculated expected results in `expected/`. |
| `templates/`, `static/` | Django templates, plain CSS with design tokens, vendored HTMX and RudderStack SDK. |
| `docs/` | Data contract, PRD, decisions, project management plan, market research. |

## License

MIT. See [LICENSE](LICENSE).
