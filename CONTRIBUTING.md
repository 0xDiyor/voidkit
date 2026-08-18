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

## Chaining and sessions (Phase 4)

Chaining pipes one module's `Result` into the next as `context.upstream`. A downstream
module reads the upstream records with the same selectors it would use on any result:

```python
class HostCount(ModuleBase):
    name = "host_count"
    category = "analysis"

    def run(self, context: RunContext) -> Result:
        if context.upstream is None:
            return self.error("no upstream result to consume; 'chain from <module>' first")
        addresses = context.upstream.values("host", "address")
        return self.ok(records=[record("host", address=a) for a in addresses])
```

The shell drives this without changing the contract. The UX is one command:

- `chain from <result-id|category/name>`: point the next run's `upstream` at a stored
  result. The reference is an exact result id, an id prefix (the 8-char form `show results`
  prints), or a module address (resolves to that module's most recent result).
- `chain` / `chain show`: report the current source.
- `chain clear`: stop chaining; runs go back to standalone.

The chain source is sticky: it stays set across `use` and multiple `run`s until you clear
it or point it somewhere else. Then `run` passes the chosen result through to `execute()`
as `RunContext.upstream`. If the source is no longer in the store the run is refused with a
clear message rather than silently dropping the upstream.

Sessions persist the working state, selected module, its options, the whole result store,
and the chain source, to JSON under `./sessions` (or `$VOIDKIT_SESSIONS_DIR`, or
`--sessions-dir`):

- `save <name>` writes `<sessions-dir>/<name>.json`.
- `load <name>` restores it: results repopulate the store, the module and its options are
  reselected, and the chain source is restored (if it still resolves). A missing or corrupt
  file is reported, not fatal.

Because results serialize verbatim (`Result.to_dict()`/`from_dict()`) and carry stable ids,
a chain survives a save/load boundary: save a session, load it into a fresh shell, and
`chain from` a restored result to run the downstream module. `voidkit.session.Session` owns
the state container and disk I/O; the shell maps itself to and from it.

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
