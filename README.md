# Data Factory — Stage 2 (PostgreSQL)

Stage 1 built a resumable, deterministic factory for NYC 311 data. Stage 2 adds PostgreSQL
as a new destination and the Olist e-commerce data as a new source, through the same package.

## Run it

Requirements: **Python 3.11+** and a **PostgreSQL server** (measured on 18.6; no Docker needed).

```bash
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .

# Connection: no password or port is stored in the repository.
set PGPASSWORD=<postgres password>          # macOS/Linux: export PGPASSWORD=...
set PGPORT=5432                             # only if the server is not on 5432
# or replace the whole URL: set DATABASE_URL=postgresql+psycopg://user@host:port/dbname

data-factory check-db                       # connection test
data-factory run                            # one command: empty server -> full database
python -m unittest discover -s tests -t .   # tests (database tests are skipped without a server)
```

`data-factory run` creates the database `dba_stage2` if it does not exist, then builds both
datasets: **nyc311** (fetch → validate → clean → enrich → publish → load) and **olist**
(fetch → validate → load). Each load runs in one transaction: all or nothing, safe to repeat.

```bash
data-factory run --dataset olist                 # one dataset
data-factory run --dataset nyc311 --stages load  # one stage
data-factory benchmark --label now --set snapshot # time the dashboard queries
data-factory index-evidence                      # index plans, sizes, write cost
```

## Project layout

| Path | Content |
|---|---|
| `factory.toml` | every setting (sources, pinned checksums, schemas, SQL files) |
| `src/data_factory/` | the package: sources, contracts, validation, sinks, pipelines, CLI |
| `sql/nyc311/`, `sql/olist/` | all DDL, run by the load stage |
| `data/` | raw downloads, intermediate and published files (not in Git) |
| `solution.ipynb`, `report.md` | stage-2 notebook (run after `data-factory run`) and report |
| `docs/stage1/` | stage-1 notebook and report |
| `docs/decisions.md` | every decision with its evidence |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 10 | configuration error |
| 20–21 | network error / invalid response |
| 30–34 | data error (validation, quarantine limit, source schema change, reference data, checksum mismatch) |
| 40 | input of an earlier stage is missing |
| 50 | database error (connection, constraint, load rolled back) |
| 1 | unexpected error (bug) |
