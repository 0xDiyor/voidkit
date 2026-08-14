"""Tests for the Phase 3 recon modules (ping, port_scan, dns_enum).

The modules live under ``modules/recon/`` rather than the importable ``voidkit``
package, so they are loaded from disk the way the framework loads them. Network
calls are monkeypatched (or aimed at reserved/unroutable addresses) so every test
is fast and hermetic, no reliance on external DNS or a live host.
"""

from __future__ import annotations

import importlib.util
import socket
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from voidkit.contract import ModuleBase, OptionValidationError, Result, ResultStatus
from voidkit.loader import ModuleLoader

MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"


def _load(relpath: str) -> ModuleType:
    """Import a module file from ``modules/`` by relative path, returning the namespace."""
    path = MODULES_DIR / relpath
    spec = importlib.util.spec_from_file_location(f"voidkit_test.{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ping_mod = _load("recon/ping.py")
port_scan_mod = _load("recon/port_scan.py")
dns_enum_mod = _load("recon/dns_enum.py")


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["ping"], returncode=returncode, stdout=stdout, stderr="")


def _assert_well_formed(result: Result) -> None:
    """Every module run must produce a serializable Result with a valid status enum."""
    assert isinstance(result, Result)
    assert result.status in ResultStatus
    assert result.finished_at is not None
    assert result.started_at <= result.finished_at
    # The result must survive the JSON round trip session save/load relies on.
    assert Result.from_dict(result.to_dict()) == result


# --------------------------------------------------------------------------- ping


class TestPingOptions:
    def test_target_is_required(self):
        with pytest.raises(OptionValidationError, match="target"):
            ping_mod.Ping().execute()

    def test_count_defaults_to_four(self):
        module = ping_mod.Ping(target="10.0.0.1")
        assert module.validate_options().count == 4

    def test_count_must_be_at_least_one(self):
        with pytest.raises(Exception):  # noqa: B017 - InvalidOptionValueError from pydantic ge=1
            ping_mod.Ping(target="10.0.0.1", count=0)

    def test_string_count_is_coerced(self):
        assert ping_mod.Ping(target="10.0.0.1", count="3").validate_options().count == 3


class TestPingLatencyParser:
    def test_parses_linux_reply_times(self):
        output = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms\n" \
                 "64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=13.7 ms\n"
        assert ping_mod._parse_latency_ms(output) == pytest.approx(13.0)

    def test_parses_windows_sub_millisecond(self):
        assert ping_mod._parse_latency_ms("Reply from 10.0.0.1: bytes=32 time<1ms TTL=128") == 1.0

    def test_returns_none_without_samples(self):
        assert ping_mod._parse_latency_ms("Request timed out.") is None


class TestPingRun:
    def test_reachable_host_is_up_with_latency(self, monkeypatch):
        stdout = "64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=10.0 ms\n"
        monkeypatch.setattr(ping_mod, "_invoke", lambda cmd, timeout: _completed(0, stdout))
        result = ping_mod.Ping(target="8.8.8.8", count=1).execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        (host,) = result.records_of("host")
        assert host.fields == {"address": "8.8.8.8", "state": "up", "latency_ms": 10.0}
        assert result.keys["reachable"] is True

    def test_unreachable_host_is_down(self, monkeypatch):
        monkeypatch.setattr(ping_mod, "_invoke", lambda cmd, timeout: _completed(1, ""))
        result = ping_mod.Ping(target="10.255.255.1", count=1).execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        (host,) = result.records_of("host")
        assert host.fields["state"] == "down"
        assert host.fields["latency_ms"] is None
        assert result.keys["reachable"] is False

    def test_timeout_reports_down_not_error(self, monkeypatch):
        def _boom(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(ping_mod, "_invoke", _boom)
        result = ping_mod.Ping(target="10.255.255.1").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        assert result.records_of("host")[0].fields["state"] == "down"

    def test_missing_ping_binary_is_a_clean_error(self, monkeypatch):
        def _missing(cmd, timeout):
            raise FileNotFoundError("ping")

        monkeypatch.setattr(ping_mod, "_invoke", _missing)
        result = ping_mod.Ping(target="10.0.0.1").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.ERROR
        assert result.errors[0].kind == "tool_missing"

    def test_target_starting_with_dash_is_rejected(self):
        result = ping_mod.Ping(target="-oremote").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.ERROR
        assert result.errors[0].kind == "invalid_target"


# ----------------------------------------------------------------------- port_scan


class TestParsePorts:
    def test_comma_list(self):
        assert port_scan_mod.parse_ports("22,80,443") == [22, 80, 443]

    def test_range(self):
        assert port_scan_mod.parse_ports("20-25") == [20, 21, 22, 23, 24, 25]

    def test_single_port_range(self):
        assert port_scan_mod.parse_ports("443-443") == [443]

    def test_mixed_and_deduplicated_and_sorted(self):
        assert port_scan_mod.parse_ports("80, 1000-1002, 443, 80") == [80, 443, 1000, 1001, 1002]

    def test_whitespace_and_empty_tokens_tolerated(self):
        assert port_scan_mod.parse_ports(" 22 , , 80 ,") == [22, 80]

    def test_boundary_ports(self):
        assert port_scan_mod.parse_ports("1,65535") == [1, 65535]

    @pytest.mark.parametrize(
        "spec",
        ["", "   ", ",", "abc", "22,abc", "0", "70000", "22,70000", "10-5", "5-", "-5", "1-2-3"],
    )
    def test_invalid_specs_raise(self, spec):
        with pytest.raises(port_scan_mod.PortSpecError):
            port_scan_mod.parse_ports(spec)


class TestPortScanOptions:
    def test_target_and_ports_required(self):
        with pytest.raises(OptionValidationError):
            port_scan_mod.PortScan().execute()

    def test_timeout_must_be_positive(self):
        with pytest.raises(Exception):  # noqa: B017 - InvalidOptionValueError from pydantic gt=0
            port_scan_mod.PortScan(target="127.0.0.1", ports="80", timeout_s=0)


class TestPortScanRun:
    def test_invalid_ports_yield_error_result(self):
        result = port_scan_mod.PortScan(target="127.0.0.1", ports="not-ports").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.ERROR
        assert result.errors[0].kind == "invalid_ports"

    def test_unroutable_target_reports_all_closed_fast(self):
        # 192.0.2.0/24 is TEST-NET-1 (RFC 5737): reserved, never routed. A tiny
        # timeout keeps this quick and deterministic without touching a real host.
        result = port_scan_mod.PortScan(
            target="192.0.2.1", ports="80,443", timeout_s=0.05
        ).execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        assert [r.fields["address"] for r in result.records_of("host")] == ["192.0.2.1"]
        port_records = result.records_of("port")
        assert len(port_records) == 2
        assert all(r.fields["state"] == "closed" for r in port_records)
        assert result.keys == {
            "open_count": 0,
            "closed_count": 2,
            "scanned_ports": 2,
            "duration_ms": pytest.approx(result.keys["duration_ms"]),
        }

    def test_detects_a_locally_open_port(self):
        # Open a real listening socket on loopback: a deterministic "open" result
        # with no external dependency.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            result = port_scan_mod.PortScan(
                target="127.0.0.1", ports=str(port), timeout_s=1.0
            ).execute()
        finally:
            listener.close()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        (port_record,) = result.records_of("port")
        assert port_record.fields["port"] == port
        assert port_record.fields["state"] == "open"
        assert result.keys["open_count"] == 1


# ------------------------------------------------------------------------ dns_enum


class TestParseNames:
    def test_comma_separated(self):
        assert dns_enum_mod.parse_names("www,mail,api") == ["www", "mail", "api"]

    def test_newline_and_comma_mixed(self):
        assert dns_enum_mod.parse_names("www\nmail,api\n") == ["www", "mail", "api"]

    def test_lowercased_and_deduplicated_preserving_order(self):
        assert dns_enum_mod.parse_names("WWW, mail, www, MAIL, api") == ["www", "mail", "api"]

    def test_whitespace_and_blanks_dropped(self):
        assert dns_enum_mod.parse_names("  www  ,\n\n, mail ,") == ["www", "mail"]

    def test_apex_token_preserved(self):
        assert dns_enum_mod.parse_names("@,www") == ["@", "www"]

    def test_default_names_are_a_valid_wordlist(self):
        parsed = dns_enum_mod.parse_names(",".join(dns_enum_mod._DEFAULT_NAMES))
        assert parsed == list(dns_enum_mod._DEFAULT_NAMES)


class TestDnsEnumRun:
    def test_resolution_shape_with_mocked_resolver(self, monkeypatch):
        table = {"www.example.com": ["93.184.216.34"], "example.com": ["93.184.216.34"]}
        monkeypatch.setattr(dns_enum_mod, "_resolve", lambda fqdn: table.get(fqdn, []))
        result = dns_enum_mod.DnsEnum(domain="example.com", names="www,mail,@").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        by_name = {r.fields["name"]: r.fields for r in result.records_of("domain")}
        assert by_name["www.example.com"]["resolved"] is True
        assert by_name["www.example.com"]["addresses"] == ["93.184.216.34"]
        assert by_name["mail.example.com"]["resolved"] is False
        assert by_name["mail.example.com"]["addresses"] == []
        assert by_name["example.com"]["resolved"] is True  # '@' -> apex
        assert result.keys == {"resolved_count": 2, "total_names": 3}

    def test_hermetic_real_run_against_reserved_tld(self):
        # '.invalid' is reserved (RFC 6761) and guaranteed never to resolve, so a
        # real stdlib run is deterministic: shape and status hold, 0 resolved.
        result = dns_enum_mod.DnsEnum(domain="invalid", names="www,mail").execute()
        _assert_well_formed(result)
        assert result.status is ResultStatus.OK
        assert result.keys == {"resolved_count": 0, "total_names": 2}
        assert all(not r.fields["resolved"] for r in result.records_of("domain"))

    def test_default_wordlist_is_used_when_names_omitted(self, monkeypatch):
        monkeypatch.setattr(dns_enum_mod, "_resolve", lambda fqdn: [])
        result = dns_enum_mod.DnsEnum(domain="example.com").execute()
        _assert_well_formed(result)
        assert result.keys["total_names"] == len(dns_enum_mod._DEFAULT_NAMES)

    def test_domain_is_required(self):
        with pytest.raises(OptionValidationError, match="domain"):
            dns_enum_mod.DnsEnum().execute()


# --------------------------------------------------------------- loader integration


class TestModulesAreDiscoverable:
    def test_all_three_modules_load_at_their_addresses(self):
        loader = ModuleLoader(MODULES_DIR)
        addresses = loader.addresses()
        for address in ("recon/ping", "recon/port_scan", "recon/dns_enum"):
            assert address in addresses
            assert issubclass(loader.get_module(address), ModuleBase)
