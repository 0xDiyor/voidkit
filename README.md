# Void Kit

> A modular terminal framework for security and network operations.

Void Kit is an empty shell you fill with capability. Load modules, chain them, and run defensive or offensive workflows from a single clean interface.

**Status:** Pre-alpha · Active development

---

## What it is

Void Kit is a Python-based CLI framework inspired by Metasploit's `use/set/run` workflow, but built to be neutral between red-team and blue-team operations. Drop a module into the `modules/` directory, conform to the contract, and the framework handles discovery, validation, execution, and result storage.

The goal isn't to replace specialized tools — it's to give analysts and operators a single environment for recon, capture, analysis, intel lookup, and defensive response, with modules that can pipe results into each other.

## Why

Most modular security frameworks are red-team focused. Most blue-team tooling is locked inside specific SIEM or EDR ecosystems. Void Kit treats both as first-class citizens and is designed around realistic SOC + homelab workflows where you scan, capture, enrich, and respond from the same shell.

## Planned module categories

| Category   | Purpose                                              |
|------------|------------------------------------------------------|
| `recon/`   | Port scanning, DNS enumeration, service detection    |
| `capture/` | Packet capture, ARP scanning, traffic recording      |
| `analysis/`| PCAP parsing, log analysis, IOC extraction           |
| `intel/`   | VirusTotal, AbuseIPDB, Shodan, threat enrichment     |
| `exploit/` | Lab-only offensive modules (HTTP fuzzing, etc.)      |
| `response/`| SIEM queries, IP blocking, host isolation            |

## Example workflow

```
voidkit > use recon/port_scan
voidkit (recon/port_scan) > set target 10.0.0.0/24
voidkit (recon/port_scan) > run
[+] Scanning 10.0.0.0/24 ...
[+] 3 hosts up, 12 open ports
voidkit (recon/port_scan) > show results
```

## Tech stack

- Python 3.11+
- `prompt_toolkit` — REPL with tab completion and history
- `rich` — styled terminal output
- `pydantic` — module option validation
- `scapy` — packet operations
- `structlog` — structured logging

## Roadmap

- [ ] Core shell + module loader
- [x] Module contract v1 (base class, result schema)
- [ ] First modules: ping, port_scan, dns_enum
- [ ] Session save/load
- [ ] Module chaining (pipe output of one module into another)
- [ ] Wazuh integration
- [ ] TUI mode (Textual)
- [ ] v1.0 release

## Installation

The package skeleton and test harness are in place per Phase 0 of `ROADMAP.md`; the interactive shell and modules are still in development.

```bash
git clone https://github.com/0xDiyor/voidkit
cd voidkit
uv sync                     # install dependencies
uv run python -m voidkit    # print the banner and placeholder prompt
uv run pytest               # run the test suite
```

## Contributing

This is a two-person project in active early development. The module contract is being finalized — see `CONTRIBUTING.md` for how to contribute; the module authoring guide lands there with the Phase 1 contract.

## Authors

- [0xDiyor](https://github.com/0xDiyor) · [0xdiyor.com](https://0xdiyor.com)
- (Teammate)

## License

MIT, see `LICENSE`.

## Disclaimer

Void Kit includes modules intended for authorized security testing and defensive operations only. Offensive modules are designed for use against systems you own or have explicit written permission to test. The authors assume no liability for misuse.
