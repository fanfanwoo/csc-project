# Chief Signal Cat

Daily strategic intelligence pipeline for AU car and consumer finance.

Fetches → Filters → Deduplicates → Classifies (LLM) → Scores → Summarises (LLM) → Emails

## Quick start

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and SMTP_* vars

pip install -r requirements.txt
python -m csc.run          # single pipeline run
python -m csc.pipeline.scheduler   # start cron scheduler
```

## Config

| File | Controls |
|---|---|
| `config/sources.yaml` | Source feeds and weights |
| `config/filters.yaml` | Region, age, keyword rules |
| `config/scoring.yaml` | Score weights, dedup threshold |
| `config/email.yaml` | SMTP/SendGrid, recipients, LLM model config |

## Structure

```
csc/
  schemas/    — RawItem → FilteredItem → ClassifiedItem → ScoredItem
  connectors/ — RSS (active), official page / CSV (stubs)
  pipeline/   — one module per stage, each testable independently
  prompts/    — classifier and summariser system prompts
  storage/    — JSONL (active), Supabase (Day 2 stub)
  utils/      — hashing, text cleaning, logging, validation

data/         — append-only JSONL output per run, per stage
docs/         — architecture spec and prompting guide
tests/        — one test file per module + integration test
```

## Tests

```bash
pytest tests/
```

## Day 2 readiness

See [docs/architectures/csc-day1-architecture-spec.md](docs/architectures/csc-day1-architecture-spec.md) — checklist at the bottom.
