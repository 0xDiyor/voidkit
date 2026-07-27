# Contributing to Void Kit

Void Kit is a two-person project in early development. This document covers how to get a
working environment and the conventions we hold ourselves to. It will grow as the framework
does.

## Getting started

```bash
git clone https://github.com/0xDiyor/voidkit
cd voidkit
uv sync          # install runtime + dev dependencies
uv run pytest    # run the test suite
uv run ruff check .   # lint
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## Writing modules

**The module contract is not defined yet.** It lands in Phase 1 of `ROADMAP.md`, a
`ModuleBase` class, pydantic option models, and a machine-consumable `Result` schema that
session save/load and module chaining will consume. Until that contract is pinned by tests,
please do not write modules; they would be built on sand and rewritten.

Once the contract exists, this section will document it. The conventions already settled:

- Modules live under `modules/` and are addressed as `category/module_name` (snake_case),
  e.g. `recon/port_scan`.
- Module options are declared as pydantic models, not ad-hoc dicts.
- Use `structlog` for the operator audit trail and `rich` for user-facing shell output;
  keep the two separate.

## Code conventions

- Lint and format with `ruff` (line length 100, target Python 3.11). CI enforces
  `ruff check` and `pytest` on Ubuntu and Windows.
- New behavior comes with tests. Do not mark roadmap items done until the code runs and
  passes tests.

## Authorized use only

Void Kit is a dual-use security framework. Contributions must respect its security posture:

- All capability is for **authorized security testing and defensive operations only**,
  systems you own or have explicit written permission to test.
- Offensive modules (`exploit/`) are scoped lab-only.
- Do not contribute capability aimed at evasion, mass targeting, or destructive effect.
  Such contributions will be rejected.
