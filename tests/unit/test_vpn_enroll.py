import os
import stat
import subprocess

import pytest

from reshare_control.config import AppConfig, VpnConfig, load_app_config, save_app_config
from reshare_control.vpn_enroll import (
    EnrollmentError,
    enroll,
    render_wg0_conf,
    resolve_panel_fqdn,
    wg_address_from_subnet,
)


class FakeHttp(object):
    def __init__(self):
        self.requests = []

    def __call__(self, method, url, headers=None, json_data=None, timeout=10):
        self.requests.append({
            "method": method,
            "url": url,
            "headers": headers or {},
            "json": json_data,
            "timeout": timeout,
        })
        if url.endswith("/issue-key.php"):
            return {"bootstrap_key": "kns-bootstrap"}
        if url.endswith("/allocate.php"):
            return {
                "status": "ok",
                "server_key": "server-secret",
                "port": 3280,
                "subnet": "10.77.42.0/24",
                "agent_url": "http://203.0.113.10:3280",
            }
        if url.endswith("/register.php"):
            return {"status": "ok"}
        raise AssertionError("unexpected URL: %s" % url)


class FakeRunner(object):
    def __init__(self):
        self.commands = []

    def __call__(self, command, capture=False, input_text=None):
        self.commands.append((command, capture, input_text))
        if command == ["wg", "genkey"]:
            return "private-key\n"
        if command == ["wg", "pubkey"]:
            assert input_text == "private-key\n"
            return "public-key\n"
        if command == ["ip", "route", "show", "default"]:
            return "default via 203.0.113.1 dev ens3 proto dhcp\n"
        return ""


class Log(object):
    def __init__(self):
        self.messages = []

    def info(self, *args):
        self.messages.append(args)


def vpn_app(**overrides):
    values = {
        "enabled": True,
        "license_key": "license-123",
        "panel_fqdn": "panel.example.com",
        "wg_api_url": "https://admin.kanasavpn.com/api/wg",
        "oscam_checker_binary_url": "https://example.com/oscam-checker",
    }
    values.update(overrides)
    return AppConfig(vpn=VpnConfig(**values))


def fake_download(url, destination):
    assert url == "https://example.com/oscam-checker"
    with open(destination, "w") as fh:
        fh.write("#!/bin/sh\n")


def test_api_payloads_and_headers_are_constructed(tmp_path):
    http = FakeHttp()
    runner = FakeRunner()

    result = enroll(
        vpn_app(agent_id="agent-1"),
        str(tmp_path / "config"),
        Log(),
        http_client=http,
        command_runner=runner,
        downloader=fake_download,
        public_ip_resolver=lambda: "203.0.113.10",
        port_probe=lambda port: True,
        system_root=str(tmp_path / "root"),
    )

    assert http.requests[0]["url"] == "https://admin.kanasavpn.com/api/wg/issue-key.php"
    assert http.requests[0]["json"] == {
        "license_key": "license-123",
        "panel_fqdn": "panel.example.com",
    }
    assert http.requests[1]["url"] == "https://admin.kanasavpn.com/api/wg/allocate.php"
    assert http.requests[1]["headers"] == {"X-BOOTSTRAP-KEY": "kns-bootstrap"}
    assert http.requests[1]["json"]["agent_id"] == "agent-1"
    assert http.requests[1]["json"]["endpoint"] == "203.0.113.10"
    assert http.requests[1]["json"]["available_ports"] == list(range(3280, 3300))
    assert http.requests[1]["json"]["agent_port"] == 3280
    assert http.requests[2]["url"] == "https://admin.kanasavpn.com/api/wg/register.php"
    assert http.requests[2]["headers"] == {"X-BOOTSTRAP-KEY": "kns-bootstrap"}
    assert http.requests[2]["json"] == {
        "agent_id": "agent-1",
        "public_key": "public-key",
        "endpoint": "203.0.113.10:51820",
        "listen_port": 51820,
        "agent_url": "http://203.0.113.10:3280",
    }
    assert result.vpn.status == "enrolled"


def test_idempotency_reuses_stored_bootstrap_key_agent_id_and_allocation(tmp_path):
    http = FakeHttp()

    enroll(
        vpn_app(
            agent_id="stored-agent",
            bootstrap_key="stored-bootstrap",
            server_key="stored-server",
            wg_port=3288,
            wg_subnet="10.9.0.0/24",
        ),
        str(tmp_path / "config"),
        Log(),
        http_client=http,
        command_runner=FakeRunner(),
        downloader=fake_download,
        public_ip_resolver=lambda: "203.0.113.10",
        system_root=str(tmp_path / "root"),
    )

    assert [request["url"].rsplit("/", 1)[-1] for request in http.requests] == ["register.php"]
    assert http.requests[0]["headers"] == {"X-BOOTSTRAP-KEY": "stored-bootstrap"}
    assert http.requests[0]["json"]["agent_id"] == "stored-agent"
    loaded = load_app_config(str(tmp_path / "config"))
    assert loaded.vpn.agent_id == "stored-agent"
    assert loaded.vpn.bootstrap_key == "stored-bootstrap"


def test_wg0_conf_rendering_subnet_math_and_default_iface(tmp_path):
    assert wg_address_from_subnet("10.77.42.0/24") == "10.77.42.1/24"

    content = render_wg0_conf("private-key", "10.77.42.1/24", 51820, "ens3")

    assert "Address = 10.77.42.1/24" in content
    assert "ListenPort = 51820" in content
    assert "PrivateKey = private-key" in content
    assert "PostUp = iptables -t nat -A POSTROUTING -o ens3 -j MASQUERADE" in content
    assert "PostDown = iptables -t nat -D POSTROUTING -o ens3 -j MASQUERADE" in content


def test_wireguard_generated_files_are_mode_600(tmp_path):
    enroll(
        vpn_app(agent_id="agent-1"),
        str(tmp_path / "config"),
        Log(),
        http_client=FakeHttp(),
        command_runner=FakeRunner(),
        downloader=fake_download,
        public_ip_resolver=lambda: "203.0.113.10",
        port_probe=lambda port: True,
        system_root=str(tmp_path / "root"),
    )

    for rel in (
        "etc/wireguard/privatekey",
        "etc/wireguard/publickey",
        "etc/wireguard/wg0.conf",
        "opt/reshare-control/oscam-checker/oscam-checker-env.env",
    ):
        mode = stat.S_IMODE(os.stat(str(tmp_path / "root" / rel)).st_mode)
        assert mode == 0o600


def test_fqdn_resolution_validation_branches():
    assert resolve_panel_fqdn(hostname_resolver=lambda: "node.example.com") == "node.example.com"
    assert resolve_panel_fqdn(
        public_ip_resolver=lambda: "203.0.113.10",
        hostname_resolver=lambda: "localhost",
        reverse_dns_resolver=lambda ip: "reverse.example.net",
    ) == "reverse.example.net"
    with pytest.raises(EnrollmentError, match="bare IPs are not accepted"):
        enroll(
            vpn_app(panel_fqdn="203.0.113.10"),
            "/tmp/unused",
            Log(),
            dry_run=True,
            public_ip_resolver=lambda: "203.0.113.10",
        )
    with pytest.raises(EnrollmentError, match="no valid fqdn"):
        resolve_panel_fqdn(
            public_ip_resolver=lambda: "203.0.113.10",
            hostname_resolver=lambda: "localhost",
            reverse_dns_resolver=lambda ip: "203.0.113.10",
        )


def test_vpn_config_persistence_round_trip(tmp_path):
    app = vpn_app(
        agent_id="agent-1",
        bootstrap_key="kns-bootstrap",
        server_key="server-secret",
        wg_port=3280,
        wg_subnet="10.77.42.0/24",
        status="enrolled",
        enrolled_at="2026-07-26T00:00:00Z",
    )

    save_app_config(app, str(tmp_path))
    loaded = load_app_config(str(tmp_path))

    assert loaded.vpn.to_dict() == app.vpn.to_dict()
    assert stat.S_IMODE(os.stat(str(tmp_path / "config.json")).st_mode) == 0o600


def test_dry_run_performs_no_side_effects(tmp_path):
    http = FakeHttp()
    app = vpn_app(agent_id="", panel_fqdn="")

    result = enroll(
        app,
        str(tmp_path / "config"),
        Log(),
        dry_run=True,
        http_client=http,
        command_runner=FakeRunner(),
        downloader=fake_download,
        public_ip_resolver=lambda: pytest.fail("dry-run should not resolve public IP"),
        hostname_resolver=lambda: "localhost",
        system_root=str(tmp_path / "root"),
    )

    assert http.requests == []
    assert not (tmp_path / "config" / "config.json").exists()
    assert not (tmp_path / "root").exists()
    assert app.vpn.agent_id == ""
    assert result.vpn.agent_id
    assert result.vpn.panel_fqdn == "dry-run.example.com"


def test_install_vpn_phase_is_non_fatal():
    script = """
set -eu
said=""
say() { said="$said$*\\n"; }
run_python() { return 42; }
CONFIG_DIR=/etc/reshare-control
RC_LICENSE_KEY=license
RC_SKIP_VPN=0
if [ -n "${RC_LICENSE_KEY:-}" ] && [ "${RC_SKIP_VPN:-0}" != "1" ]; then
    say "Enrolling this VPS as a VPN node..."
    run_python -m reshare_control --config-dir "$CONFIG_DIR" enroll-vpn || \
        say "VPN enrollment did not complete — reshare-control itself is installed. See logs."
    say "Reminder: allow UDP 51820 in the VPS firewall/security group for WireGuard."
fi
printf '%s' "$said"
"""

    result = subprocess.run(["sh", "-c", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    assert result.returncode == 0
    assert "VPN enrollment did not complete" in result.stdout
    assert "UDP 51820" in result.stdout
