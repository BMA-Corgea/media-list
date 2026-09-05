# T-2 — Verify

Run against a **fresh `git clone`** of the repository, not the working tree — which also
proves nothing the app needs was accidentally gitignored.

## Cold boot

A clone contains `backend/ frontend/ .autodev/ kb/ README.md LICENSE .gitignore
.env.example requirements.txt start.sh` and, correctly, **no `data/`, no `.env`, no
`node_modules`, no `dist`**. After copying in a `.env` (port moved to 7801 so the test could
not collide with anything), `./start.sh` was run once:

```
media-list: creating .venv
media-list: building the frontend (first run)
✓ built in 342ms
media-list: http://127.0.0.1:7801
INFO:     Application startup complete.
```

**Up in ~26 seconds from nothing** — venv created, dependencies installed, frontend built,
database created, server serving. This closes the gap the build evidence flagged honestly.

## Regression on the clone

| Check | Result |
| --- | --- |
| `/api/health` | `ok: true`, version `0.1.0`, `db_exists: true`, db path inside the clone |
| Database self-created | `data/media-list.db` 28672 bytes + `data/art/`, neither of which came from git |
| Schema | 21 columns, `user_version 1` |
| Routing | `/` and `/deep/route` → 200 html · `/api/health` → 200 json · `/api/nope` → 404 json · `/art/x.jpg` → 404 json |
| **Traversal stays closed** | `../../.env`, `../../.git/config`, `../../../../etc/passwd` → SPA shell, **0 secrets in every body** |
| `start.sh` refuses a held port | With 7801 already bound it printed the refusal and exited; **the original server was still answering 200 afterwards** — it did not kill it |

## Not covered

- Chromium only; no second browser.
- No load or concurrency testing — one user, and the surfaces that would need it do not
  exist yet.
- The clone was made from the local repository, not from GitHub, because nothing has been
  pushed. Same tree, but worth stating rather than implying.
