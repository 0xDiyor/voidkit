# Void Kit Roadmap

> Phase-based build plan. Each phase ends with a reviewable, runnable increment. Phases are sequential; the module contract (Phase 2) is the load-bearing decision the later phases build on.

**Status:** Pre-alpha · Active development
**Target:** v1.0, a modular terminal framework for security and network operations.

---

## Phase 0: Project foundation

Objective: a runnable, testable skeleton with no functional surface.

- Package layout: `pyproject.toml` (uv), `src/voidkit/`, `pyproject` metadata.
- Entry point: `python -m voidkit` starts a placeholder shell.
- Testing: `pytest`, lint/format via `ruff`, GitHub Actions CI (lint + test on ubuntu + windows).
- `CONTRIBUTING.md` with the module authoring contract placeholder.
- CLI (`argparse`/`typer`): `voidkit --version`, `--help`.

Exit criteria: `uv sync`, `uv run pytest` green, `python -m voidkit` prints a banner.

---

## Phase 1: Module contract v1

Objective: the single blocking decision. Define the base class, option validation, and the result schema that save/load and chaining will consume.

- `ModuleBase`: `name`, `category`, `description`, `options` (pydantic model), `run(context) -> Result`.
- `Result` schema: machine-consumable, JSON-serializable. IDs, category, fields, status (`ok`/`error`), timestamps, structured keys for later piping.
- Option validation via pydantic (declared in README).
- Unit tests pinning the contract.

Exit criteria: a module author can implement the contract against pinned tests, no shell needed.

---

## Phase 2: Core shell + module loader

Objective: the Metasploit-style `use/set/run` REPL.

- Module loader: discover modules under `modules/`, addressed `category/name`.
- REPL (prompt_toolkit): tab completion, history, stateful prompt reflecting selected module.
- Commands: `use`, `set`, `unset`, `show options`, `show modules`, `run`, `exit`.
- Result store: in-memory results; `show results` lists them.

Exit criteria: the README's example workflow runs end to end in the shell.

---

## Phase 3: First modules

Objective: prove the contract and shell with real capability.

- `recon/ping`, `recon/port_scan`, `recon/dns_enum` (scapy/stdlib).
- Results land in the result store in the Phase 1 schema.
- Errors and partial results surfaced cleanly.

Exit criteria: `use recon/port_scan`, `set target 10.0.0.0/24`, `run` returns structured results. Lab-only scope; authorized use only.

---

## Phase 4: Session save/load + module chaining

Objective: persistence and the project's core differentiator (chaining).

- Save/load full session state (selected module, options, results) to JSON, `save <name>` / `load <name>`.
- Chaining: pipe `Result` from one module into another (e.g. `port_scan` hosts fed to `dns_enum`), via the contract's structured keys.
- Enforce run order and option pre-fill from upstream results.

Exit criteria: a two-module chain runs in the shell and persists across a save/load cycle.

---

## Phase 5: Intel, response, and defensive integration

Objective: blue-team depth and the Wazuh tie-in named in the README.

- `intel/` modules: VirusTotal, AbuseIPDB, Shodan enrichment (API keys via env/config).
- `response/` modules: SIEM query, IP block, host isolation stubs.
- Wazuh integration: query results from the Wazuh indexer.

Exit criteria: at least one intel and one response module run against real endpoints.

---

## Phase 6: TUI mode + v1.0

Objective: polish and release.

- Optional TUI mode with `textual` (roadmapped in README).
- Remaining `exploit/` lab modules (HTTP fuzzing, etc.).
- Documentation pass, license finalized (user decision: MIT vs Apache 2.0), README accuracy pass.

Exit criteria: v1.0 tagged and installable (`pip install` / `uv tool install`).

---

## Open decisions (need human input before they block a phase)

1. **License** (Phase 0 pushes a skeleton with `pyproject` metadata that declares it): MIT vs Apache 2.0. User must decide; not picked unilaterally.
2. **Module contract v1 details** (Phase 1): exact `Result` field set and chaining keying scheme. Proposed in the plan, reviewed before code lands.
3. **Module authoring scope**: contract designed for a two-person team; whether `CONTRIBUTING.md` targets external contributors or stays internal.

## Guardrails

- Ground every checkmark in code that actually runs. Do not claim implemented features until they pass tests.
- No offensive capability aimed at evasion, mass targeting, or destructive effect. Offensive modules stay lab-only, authorized-use, per the README disclaimer.
