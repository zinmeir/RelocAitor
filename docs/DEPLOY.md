# Deploying

## Run it locally

```bash
./run.sh          # macOS / Linux  (run.bat on Windows): creates a venv, installs, opens http://127.0.0.1:5000
```

Accounts are stored in `instance/relocaitor.db` and the profile encryption key in `instance/encryption.key`
(both created on first use, both ignored by git).

## Environment variables

| Variable | Needed | Purpose |
|---|---|---|
| `RELOC_ENCRYPTION_KEY` | Production: yes | Encrypts saved profiles. A Fernet key or any random 32+ character secret. **Keep it stable**: changing it makes saved profiles unreadable |
| `RELOC_DB` | Production: yes | SQLite path on persistent storage, e.g. `/var/data/relocaitor.db` |
| `RELOC_SECURE_COOKIES` | Behind HTTPS: `1` | Session cookie sent only over HTTPS |
| `RELOC_RATE_LIMIT` | No (240) | API requests per minute per client; `0` disables |
| `RELOC_LOG_JSON` | No | `1` for one JSON log line per request |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | No | Lets the assistant phrase answers (only with the user's consent) and read prompts |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | No | Live job vacancies in the Career section |
| `PORT`, `HOST` | Platform-set | Where the server listens |

## Render (one click)

New → Blueprint → choose the repository. `render.yaml` sets the build, start command, health check, a
generated encryption key, secure cookies and JSON logs. On the free plan the SQLite file is lost on each
deploy, so accounts reset; for lasting accounts use a plan with a disk (the commented `disk:` block) and set
`RELOC_DB=/var/data/relocaitor.db`.

## Docker

```bash
docker build -t relocaitor .
docker run -p 8000:8000 -v reloc-data:/app/instance \
  -e RELOC_ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" relocaitor
```
The container runs as a non-root user and keeps accounts in the `/app/instance` volume. Put it behind a
TLS-terminating proxy and add `-e RELOC_SECURE_COOKIES=1`.

## GitHub Pages (static demo)

`.github/workflows/pages.yml` publishes `python preview/build_preview.py`. It runs the search, ranking,
map, eligibility and data-status features in the browser. Accounts, pathways, money, career, dimensions and
the assistant need the server and are hidden or labelled there.

## Before going live

- Set `RELOC_ENCRYPTION_KEY` and `RELOC_DB` on persistent storage; back up the database and the key separately.
- Serve over HTTPS and set `RELOC_SECURE_COOKIES=1`.
- One gunicorn process per machine keeps the in-memory rate limiter exact; with more, add a shared limiter.
- Read `docs/SECURITY.md`, "Known gaps".
- Data upkeep: `python -m immigration review` / `approve`, `python -m pipeline fetch && build` (needs internet),
  `python -m pipeline currencies`, then `python -m pipeline.validate` and the tests. CI checks the data on every push.
