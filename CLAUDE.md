## Agent skills

### Issue tracker

Issues live as GitHub Issues; use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at root. See `docs/agents/domain.md`.

## Worktrees — keep `main` checked out here

launchd runs the daily pipeline (07:00) and heartbeat (12:00) from **this folder's working tree** (`chief-signal-cat/` as WorkingDirectory). Whatever is checked out here is what runs; switching branches here can break scheduled runs (e.g. a branch without `csc/tools/check_heartbeat.py` makes the heartbeat fail).

- **This folder (`csc-project/`) stays on `main` at all times.** Never `git checkout`/`switch` a feature branch here. Only fast-forward it (`git pull`) after merges.
- **Do all branch work in the worktree `../csc-work`** (`git worktree add ../csc-work <branch>` if missing; `git -C ../csc-work switch <branch>` to change branches there). Edit, test, commit and push from `../csc-work`.
- Run tests there with this folder's venv: `cd ../csc-work/chief-signal-cat && ../../csc-project/chief-signal-cat/.venv/bin/python -m pytest -q`. `csc` is not pip-installed, so imports resolve to the worktree's code.
- **Dependencies:** the shared venv only works while the branch uses the same packages as `main`. If a branch changes `chief-signal-cat/requirements.txt`, give the worktree its own venv (`cd ../csc-work/chief-signal-cat && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`) and run its tests with `.venv/bin/python -m pytest -q`. **Never `pip install` into this folder's `.venv` from branch work** — the 07:00 pipeline and 12:00 heartbeat run on it.
- `.env` is not in the worktree (untracked secrets). Tests don't need it. For live dry runs that need credentials, symlink it rather than copying, so there is one copy of the secrets: `ln -s ../../csc-project/chief-signal-cat/.env ../csc-work/chief-signal-cat/.env` (run from this folder). `.env` is gitignored, so the link is never committed.
