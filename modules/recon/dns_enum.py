"""recon/dns_enum: forward DNS enumeration of subdomains under a base domain.

Resolution goes through the standard library (``socket.getaddrinfo``), so the
module runs with Void Kit's current dependency set, no third-party DNS library is
required. ``dns.resolver`` (dnspython) is imported behind a guard purely as an
availability signal for future record-type queries; when it is absent the module
degrades to stdlib resolution with no change in behaviour.

This is ordinary forward-lookup reconnaissance against a small, operator-supplied
wordlist: it asks the resolver whether ``name.domain`` resolves and records the
addresses. No zone transfer, no brute-force flooding, just a modest, authorized-use
enumeration for domains you own or are permitted to assess.
"""

from __future__ import annotations

import socket

from voidkit.contract import ModuleBase, ModuleOptions, Result, RunContext, option, record

try:  # optional; only a capability signal, resolution still uses the stdlib below
    import dns.resolver as _dns_resolver

    _HAS_DNSPYTHON = True
except ImportError:  # pragma: no cover - depends on whether dnspython is installed
    _dns_resolver = None
    _HAS_DNSPYTHON = False

# A short, conventional set of subdomains to try when the operator supplies none.
_DEFAULT_NAMES = (
    "www",
    "mail",
    "ftp",
    "webmail",
    "smtp",
    "ns1",
    "ns2",
    "api",
    "dev",
    "staging",
    "vpn",
    "admin",
)


def parse_names(spec: str) -> list[str]:
    """Split a wordlist string into de-duplicated, lower-cased subdomain labels.

    Tokens may be separated by commas or newlines (or both), with surrounding
    whitespace ignored and empty tokens dropped. Order of first appearance is
    preserved. The literal ``@`` is kept as-is to mean the apex domain.
    """
    seen: set[str] = set()
    names: list[str] = []
    for chunk in spec.replace("\n", ",").split(","):
        token = chunk.strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        names.append(token)
    return names


def _resolve(fqdn: str) -> list[str]:
    """Sorted, de-duplicated A/AAAA addresses for *fqdn*; empty if it does not resolve."""
    try:
        infos = socket.getaddrinfo(fqdn, None)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


class DnsEnumOptions(ModuleOptions):
    domain: str = option(description="Base domain to enumerate, e.g. 'example.com'.", min_length=1)
    names: str = option(
        ",".join(_DEFAULT_NAMES),
        description="Subdomain labels to try (comma/newline separated). '@' means the apex.",
    )


class DnsEnum(ModuleBase):
    name = "dns_enum"
    category = "recon"
    description = "Forward DNS enumeration of subdomains under a base domain (stdlib resolver)."
    options_model = DnsEnumOptions

    def run(self, context: RunContext) -> Result:
        domain = self.opts.domain.strip().rstrip(".")
        if not domain:
            return self.error("domain is empty after normalization", kind="invalid_domain")

        names = parse_names(self.opts.names)
        if not names:
            return self.error("no subdomain names to resolve", kind="empty_wordlist")

        self.log.info(
            "dns_enum.start",
            domain=domain,
            names=len(names),
            resolver="dnspython" if _HAS_DNSPYTHON else "stdlib",
        )

        records = []
        resolved_count = 0
        for name in names:
            fqdn = domain if name == "@" else f"{name}.{domain}"
            addresses = _resolve(fqdn)
            resolved = bool(addresses)
            resolved_count += resolved
            records.append(
                record("domain", name=fqdn, addresses=addresses, resolved=resolved)
            )

        self.log.info("dns_enum.done", domain=domain, resolved=resolved_count, total=len(names))
        return self.ok(
            records=records,
            keys={"resolved_count": resolved_count, "total_names": len(names)},
            summary=f"{resolved_count}/{len(names)} names resolved under {domain}",
        )
