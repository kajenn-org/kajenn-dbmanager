# kajenn-dbmanager

Kajenn application for PostgreSQL administration over REST and MCP: connection
profiles, introspection, diagrams, migrations, backups, restores and query sessions.

## Repository rules

- **Maintainer:** Giovanni Porcari (`genro`).
- **Branch:** work lands directly on `main`, without pull requests (the repository is a lab).
  A commit is pushed only when ruff, the tests and the docs build pass.
- **Language:** issues, pull requests, code comments, docs and commit messages in English.
- **Forge:** GitHub, `kajenn-org/kajenn-dbmanager`; use the `gh` CLI.

## Names

- Distribution and CLI `kajenn-dbmanager`, import package `kajenn_dbmanager`,
  environment variables prefixed `KAJENN_DBMANAGER_`.
- The project was `asqueel-org/asqueel-dbmanager` up to 0.2.1; that name is no longer published.

## Development

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev,postgresql,ui,queries,asqueel,docs,clusters]'
.venv/bin/ruff check src tests
TMPDIR=/tmp LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest -q
.venv/bin/sphinx-build -W -b html docs /tmp/kajenn-dbmanager-docs
```

The PostgreSQL tests start a server through `testing.postgresql`: it needs the
PostgreSQL client and server binaries on `PATH`, a short `TMPDIR` (the Unix socket
path is limited to 103 bytes on macOS) and a valid `LC_ALL`.

## Documents

Private working documents (plans, handoffs, notes) live under `temp/`, which git ignores.
