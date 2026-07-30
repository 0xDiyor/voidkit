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

The module contract (v1) lives in `src/voidkit/contract/` and is pinned by
`tests/test_contract_*.py`. A module is three pieces:

```python
from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

class PingOptions(ModuleOptions):
    target: str = option(description="Host to ping.")          # no default = required
    count: int = option(4, description="Probes to send.", ge=1)

class Ping(ModuleBase):
    name = "ping"
    category = "recon"
    description = "ICMP reachability check."
    options_model = PingOptions

    def run(self, context: RunContext) -> Result:
        # self.opts is the validated PingOptions instance
        return self.ok(
            records=[record("host", address=self.opts.target, state="up")],
            summary=f"{self.opts.target} is up",
        )
```

Rules of the contract:

- **Never return a raw dict**; build the `Result` with `self.ok()`, `self.partial()`
  (some records plus errors), or `self.error()`. The builders fill in the module address,
  timestamps, and the options snapshot.
- **Emit findings as typed records** (`record("host", address=...)`) with stable,
  snake_case field names. Records are the chaining unit: a downstream module reads them
  via `result.records_of("host")` or `result.values("host", "address")`. Run-level
  scalars (counts, derived values) go in `keys`.
- **Everything in a `Result` must be JSON-serializable**; the schema enforces it.
  Session save/load (Phase 4) persists results verbatim via `to_dict()`/`from_dict()`.
- The framework calls `execute()`, which validates options first (raising
  `OptionValidationError` before any work happens) and converts an uncaught exception
  from `run()` into an error `Result`.
- `EchoModule` in `tests/test_contract_module.py` is the reference implementation.

The conventions already settled:

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
