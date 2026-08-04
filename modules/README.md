# Modules

Drop-in modules the shell discovers at startup. This directory is the default
modules path (`ModuleLoader` also accepts any other directory, and the CLI takes
`--modules-dir` / `$VOIDKIT_MODULES_DIR`).

## Layout

One module per file, grouped into category subdirectories:

```
modules/
    recon/
        port_scan.py      # -> addressed recon/port_scan
        dns_enum.py       # -> addressed recon/dns_enum
    analysis/
        log_parse.py      # -> addressed analysis/log_parse
```

The address the shell uses (`category/name`) comes from the module's declared
`category` and `name` class attributes, not the path. Keep the directory name
equal to the declared `category` — the loader warns when they disagree. Files
whose names start with `_` or `.` are ignored, so helpers and `__init__.py` are
safe to add.

## Adding a module

Create `modules/<category>/<name>.py` and subclass `ModuleBase` (see
`CONTRIBUTING.md` for the full contract):

```python
from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

class PingOptions(ModuleOptions):
    target: str = option(description="Host to ping.")

class Ping(ModuleBase):
    name = "ping"
    category = "recon"
    description = "ICMP reachability check."
    options_model = PingOptions

    def run(self, context: RunContext) -> Result:
        return self.ok(
            records=[record("host", address=self.opts.target, state="up")],
            summary=f"{self.opts.target} is up",
        )
```

There is no registration step: discovery finds any concrete `ModuleBase`
subclass in the file. A file that fails to import is skipped with a warning, so
one broken module never blocks the rest.

The first real modules (`recon/ping`, `recon/port_scan`, `recon/dns_enum`) land
in Phase 3; for authorized, lab-only use per the project disclaimer.
