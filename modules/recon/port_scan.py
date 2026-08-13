"""recon/port_scan: a TCP connect scan of a single target.

Uses ``socket.connect_ex`` (a full TCP handshake, no raw sockets, no root) across a
bounded thread pool so a wide port range completes quickly without flooding the
target. It is a plain connect scan: no half-open, no spoofing, no evasion, just
"is this port accepting connections right now."

Defensive reconnaissance for hosts you own or are authorized to test. It reports
one host record plus a per-port open/closed record, and run-level counts for
downstream chaining (e.g. feeding open-port hosts into another module).
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor

from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

# Cap concurrent connections so a large range does not hammer the target or
# exhaust local file descriptors. Small ranges use only as many threads as ports.
_MAX_WORKERS = 100
_MIN_PORT = 1
_MAX_PORT = 65535


class PortSpecError(ValueError):
    """Raised when the ``ports`` string cannot be parsed into valid port numbers."""


def parse_ports(spec: str) -> list[int]:
    """Parse a ports string into a sorted, de-duplicated list of port numbers.

    Accepts comma-separated single ports and ``low-high`` inclusive ranges, in any
    mix, tolerating surrounding whitespace and empty tokens::

        "22,80,443"       -> [22, 80, 443]
        "1-1024"          -> [1, 2, ..., 1024]
        "80, 1000-1002"   -> [80, 1000, 1001, 1002]

    Raises :class:`PortSpecError` with a clear message on anything invalid: a
    non-numeric token, a port outside 1-65535, a descending or malformed range, or
    a spec that contains no ports at all.
    """
    ports: set[int] = set()
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            ports.update(_parse_range(token))
        else:
            ports.add(_parse_single(token))
    if not ports:
        raise PortSpecError(f"no ports found in {spec!r}")
    return sorted(ports)


def _parse_single(token: str) -> int:
    try:
        port = int(token)
    except ValueError:
        raise PortSpecError(f"invalid port {token!r}: not a number") from None
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise PortSpecError(f"port {port} out of range ({_MIN_PORT}-{_MAX_PORT})")
    return port


def _parse_range(token: str) -> range:
    parts = token.split("-")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise PortSpecError(f"invalid port range {token!r}: expected 'low-high'")
    low = _parse_single(parts[0])
    high = _parse_single(parts[1])
    if low > high:
        raise PortSpecError(f"invalid port range {token!r}: {low} is greater than {high}")
    return range(low, high + 1)


class PortScanOptions(ModuleOptions):
    target: str = option(description="Target host or IP address to scan.", min_length=1)
    ports: str = option(
        description="Ports to scan: comma list and/or low-high ranges, e.g. '22,80,443' or '1-1024'.",
        min_length=1,
    )
    timeout_s: float = option(1.0, description="Per-port connection timeout in seconds.", gt=0)


def _resolve_target(target: str) -> str:
    """Resolve *target* to a single IPv4 address, or raise ``socket.gaierror``."""
    infos = socket.getaddrinfo(target, None, socket.AF_INET, socket.SOCK_STREAM)
    return infos[0][4][0]


def _service_name(port: int) -> str | None:
    """Best-effort /etc/services lookup for a TCP port; None when unknown."""
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return None


def _probe_port(ip: str, port: int, timeout_s: float) -> bool:
    """True if a TCP connection to ``ip:port`` succeeds within the timeout."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        try:
            return sock.connect_ex((ip, port)) == 0
        except OSError:
            return False


class PortScan(ModuleBase):
    name = "port_scan"
    category = "recon"
    description = "TCP connect scan of a target over a bounded thread pool."
    options_model = PortScanOptions

    def run(self, context: RunContext) -> Result:
        try:
            ports = parse_ports(self.opts.ports)
        except PortSpecError as exc:
            return self.error(str(exc), kind="invalid_ports")

        target = self.opts.target
        try:
            ip = _resolve_target(target)
        except socket.gaierror as exc:
            return self.error(
                f"cannot resolve target {target!r}: {exc}",
                kind="resolution_failed",
            )

        timeout_s = self.opts.timeout_s
        self.log.info("port_scan.start", target=target, ip=ip, ports=len(ports))
        started = time.perf_counter()
        workers = min(len(ports), _MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            open_flags = pool.map(lambda p: _probe_port(ip, p, timeout_s), ports)
            states = dict(zip(ports, open_flags, strict=True))
        duration_ms = round((time.perf_counter() - started) * 1000, 3)

        records = [record("host", address=target, state="up")]
        open_count = 0
        for port in ports:
            is_open = states[port]
            open_count += is_open
            records.append(
                record(
                    "port",
                    address=target,
                    port=port,
                    state="open" if is_open else "closed",
                    service=_service_name(port),
                )
            )
        closed_count = len(ports) - open_count

        self.log.info(
            "port_scan.done",
            target=target,
            open=open_count,
            closed=closed_count,
            duration_ms=duration_ms,
        )
        return self.ok(
            records=records,
            keys={
                "open_count": open_count,
                "closed_count": closed_count,
                "scanned_ports": len(ports),
                "duration_ms": duration_ms,
            },
            summary=f"{target}: {open_count} open, {closed_count} closed of {len(ports)} ports",
        )
