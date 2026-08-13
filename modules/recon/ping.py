"""recon/ping: ICMP reachability check via the system ``ping`` command.

Shelling out to the platform ``ping`` binary keeps this root-free (unprivileged
users may send ICMP echo through the setuid/cap-net-raw ``ping`` tool even when a
raw socket would be denied) and portable across Linux, macOS, and Windows. The
module never touches a raw socket itself.

Defensive, read-only reconnaissance: it sends a small, fixed number of echo
requests to a single operator-supplied host and reports up/down plus round-trip
latency. For authorized use against hosts you own or have permission to probe.
"""

from __future__ import annotations

import platform
import re
import subprocess

from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

# Per-reply round-trip time: Linux/macOS emit "time=0.045 ms", Windows "time<1ms".
_LATENCY_RE = re.compile(r"time[=<]\s*([\d.]+)")


class PingOptions(ModuleOptions):
    target: str = option(description="Host or IP address to probe.", min_length=1)
    count: int = option(4, description="Number of echo requests to send.", ge=1)


def _build_command(target: str, count: int) -> list[str]:
    """Platform-appropriate ``ping`` argv. Target is passed as a bare arg (no shell)."""
    if platform.system().lower().startswith("win"):
        return ["ping", "-n", str(count), target]
    return ["ping", "-c", str(count), target]


def _timeout_for(count: int) -> float:
    """Overall subprocess deadline: ~1s/probe plus generous slack for slow links."""
    return count * 2 + 5


def _invoke(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run ``ping`` and capture its output. Isolated so tests can monkeypatch it."""
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,  # a non-zero exit means "host down", not an error to raise on
    )


def _parse_latency_ms(output: str) -> float | None:
    """Mean of the per-reply round-trip times in ``ping`` output, or None if absent."""
    samples = [float(match) for match in _LATENCY_RE.findall(output)]
    if not samples:
        return None
    return round(sum(samples) / len(samples), 3)


class Ping(ModuleBase):
    name = "ping"
    category = "recon"
    description = "ICMP reachability check using the system ping command."
    options_model = PingOptions

    def run(self, context: RunContext) -> Result:
        target = self.opts.target
        if target.startswith("-"):
            return self.error(
                f"invalid target {target!r}: must not start with '-'",
                kind="invalid_target",
            )

        command = _build_command(target, self.opts.count)
        timeout = _timeout_for(self.opts.count)
        self.log.info("ping.probe", target=target, count=self.opts.count)

        try:
            completed = _invoke(command, timeout)
        except FileNotFoundError:
            return self.error(
                "the 'ping' command is not installed or not on PATH",
                kind="tool_missing",
            )
        except subprocess.TimeoutExpired:
            # No reply arrived within the deadline: report the host as down rather
            # than surfacing an error, since a silent host is a valid finding.
            self.log.info("ping.timeout", target=target)
            return self.ok(
                records=[record("host", address=target, state="down", latency_ms=None)],
                keys={"reachable": False},
                summary=f"{target} is down (no reply within {timeout:.0f}s)",
            )

        up = completed.returncode == 0
        latency = _parse_latency_ms(completed.stdout) if up else None
        state = "up" if up else "down"
        summary = f"{target} is {state}"
        if latency is not None:
            summary += f" ({latency:.3f} ms avg)"
        self.log.info("ping.result", target=target, state=state, latency_ms=latency)
        return self.ok(
            records=[record("host", address=target, state=state, latency_ms=latency)],
            keys={"reachable": up},
            summary=summary,
        )
