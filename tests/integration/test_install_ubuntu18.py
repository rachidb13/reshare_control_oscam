"""Drive install-ubuntu18.sh end to end against stubbed system commands.

The script runs for real under ``sh``; only the commands that would touch the
host (apt, systemd, cron, firewall, uid lookup) are replaced by stubs that log
their arguments.
"""

import json
import os
import stat
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "install-ubuntu18.sh")
STANDARD_INSTALL = (
    "curl -fsSL https://raw.githubusercontent.com/rachidb13/"
    "reshare_control_oscam/master/install.sh | sudo sh"
)

OS_RELEASES = {
    "ubuntu18": 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="18.04"\nPRETTY_NAME="Ubuntu 18.04.6 LTS"\n',
    "ubuntu16": 'ID=ubuntu\nVERSION_ID="16.04"\nPRETTY_NAME="Ubuntu 16.04.7 LTS"\n',
    "ubuntu20": 'ID=ubuntu\nVERSION_ID="20.04"\nPRETTY_NAME="Ubuntu 20.04.6 LTS"\n',
    "ubuntu22": 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.4 LTS"\n',
    "debian11": 'ID=debian\nVERSION_ID="11"\nPRETTY_NAME="Debian GNU/Linux 11 (bullseye)"\n',
}

STUBS = {
    "id": """#!/bin/sh
log id "$@"
[ "$1" = "-u" ] && { printf '%s\\n' "${STUB_UID:-0}"; exit 0; }
exec /usr/bin/id "$@"
""",
    "apt-get": """#!/bin/sh
log apt-get "$@"
[ "${STUB_APT_FAIL:-0}" = "1" ] && exit 100
case " $* " in
    *" install "*python3.8*) ln -sf "$STUB_PYTHON" "$STUB_BIN/python3.8" ;;
esac
exit 0
""",
    "systemctl": """#!/bin/sh
log systemctl "$@"
[ "${STUB_NO_SYSTEMD:-0}" = "1" ] && exit 1
exit 0
""",
    "crontab": """#!/bin/sh
log crontab "$@"
if [ "$1" = "-l" ]; then
    [ -f "$STUB_CRONTAB" ] && cat "$STUB_CRONTAB"
    exit 0
fi
cp "$1" "$STUB_CRONTAB"
""",
    "ufw": """#!/bin/sh
log ufw "$@"
[ "$1" = "status" ] && { echo "Status: active"; exit 0; }
exit 0
""",
    "hostname": """#!/bin/sh
[ "$1" = "-I" ] && { echo "10.0.0.5 "; exit 0; }
echo testhost
""",
}


class Harness(object):
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.calls = tmp_path / "calls.log"
        self.calls.write_text("")
        self.crontab = tmp_path / "crontab"
        self.config_dir = tmp_path / "etc"
        self.systemd_dir = tmp_path / "systemd"
        self.install_dir = tmp_path / "opt"
        self.os_release = tmp_path / "os-release"
        self.set_os("ubuntu18")
        log = tmp_path / "log"
        log.write_text(
            '#!/bin/sh\nprintf "%%s\\n" "$*" >> %s\n' % self.calls
        )
        log.chmod(0o755)
        for name, body in STUBS.items():
            self._write_stub(name, body)
        self.add_python38()

    def _write_stub(self, name, body):
        path = self.bin / name
        path.write_text(body.replace("log ", "%s " % (self.root / "log"), 1))
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def add_python38(self):
        target = self.bin / "python3.8"
        if not target.exists():
            target.symlink_to(sys.executable)

    def remove_python38(self):
        (self.bin / "python3.8").unlink()

    def set_os(self, key):
        self.os_release.write_text(OS_RELEASES[key])

    def run(self, **extra):
        env = {
            "PATH": "%s:/usr/bin:/bin" % self.bin,
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
            "RC_OS_RELEASE": str(self.os_release),
            "RC_CONFIG_DIR": str(self.config_dir),
            "RC_SYSTEMD_DIR": str(self.systemd_dir),
            "RC_INSTALL_DIR": str(self.install_dir),
            "RC_SOURCE_DIR": os.path.join(REPO, "src"),
            "STUB_BIN": str(self.bin),
            "STUB_PYTHON": sys.executable,
            "STUB_CRONTAB": str(self.crontab),
        }
        env.update(extra)
        proc = subprocess.run(
            ["sh", SCRIPT],
            cwd=str(self.root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            timeout=60,
        )
        return proc.returncode, proc.stdout.decode(), self.calls.read_text()

    def unit(self, name):
        return (self.systemd_dir / name).read_text()


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path)


# --- User Story 2: refuse everything that is not Ubuntu 18.04 -----------------

@pytest.mark.parametrize("os_key", ["ubuntu16", "ubuntu20", "ubuntu22", "debian11"])
def test_refuses_other_systems_before_any_change(harness, os_key):
    harness.set_os(os_key)
    code, out, calls = harness.run()
    assert code == 1
    assert not harness.config_dir.exists()
    assert not harness.systemd_dir.exists()
    assert "apt-get" not in calls
    assert "18.04" in out


@pytest.mark.parametrize("os_key", ["ubuntu20", "ubuntu22"])
def test_newer_ubuntu_is_pointed_at_standard_installer(harness, os_key):
    harness.set_os(os_key)
    code, out, _ = harness.run()
    assert code == 1
    assert STANDARD_INSTALL in out


@pytest.mark.parametrize("os_key", ["ubuntu16", "debian11"])
def test_other_systems_are_not_pointed_at_standard_installer(harness, os_key):
    harness.set_os(os_key)
    _, out, _ = harness.run()
    assert STANDARD_INSTALL not in out


def test_missing_os_release_is_refused(harness):
    harness.os_release.unlink()
    code, out, calls = harness.run()
    assert code == 1
    assert "Unsupported system" in out
    assert not harness.config_dir.exists()


def test_non_root_is_refused_before_any_change(harness):
    code, out, calls = harness.run(STUB_UID="1000")
    assert code == 1
    assert "root" in out
    assert not harness.config_dir.exists()
    assert "apt-get" not in calls


# --- User Story 1: install the panel on 18.04 ---------------------------------

def test_happy_path_installs_panel_and_poller(harness):
    code, out, calls = harness.run()
    assert code == 0, out
    config = harness.config_dir / "config.json"
    assert config.exists()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(harness.config_dir.stat().st_mode) == 0o700
    for name in ("reshare-control.service", "reshare-control.timer",
                 "reshare-control-web.service"):
        assert (harness.systemd_dir / name).exists()
    assert "systemctl enable --now --quiet reshare-control.timer" in calls
    assert "systemctl enable --now --quiet reshare-control-web.service" in calls
    web_port = json.loads(config.read_text())["web"]["port"]
    assert "Open: http://10.0.0.5:%s/" % web_port in out
    assert "User: admin" in out
    assert "Password: " in out
    assert "existing password" not in out


def test_existing_python38_skips_apt(harness):
    code, out, calls = harness.run()
    assert code == 0, out
    assert "apt-get" not in calls


def test_missing_python38_is_installed_from_apt(harness):
    harness.remove_python38()
    code, out, calls = harness.run()
    assert code == 0, out
    assert "apt-get update" in calls
    install_lines = [l for l in calls.splitlines() if l.startswith("apt-get") and " install " in l]
    assert install_lines and "python3.8" in install_lines[0]


def test_apt_failure_stops_before_services(harness):
    harness.remove_python38()
    code, out, calls = harness.run(STUB_APT_FAIL="1")
    assert code == 1
    assert "python3.8" in out
    assert "universe" in out
    assert not harness.systemd_dir.exists()
    assert not harness.config_dir.exists()


def test_services_are_pinned_to_python38(harness):
    code, out, _ = harness.run()
    assert code == 0, out
    python38 = str(harness.bin / "python3.8")
    for name, sub in (("reshare-control.service", "run-all"),
                      ("reshare-control-web.service", "web")):
        exec_lines = [l for l in harness.unit(name).splitlines() if l.startswith("ExecStart=")]
        assert len(exec_lines) == 1
        line = exec_lines[0]
        assert "%s -m reshare_control" % python38 in line
        assert line.endswith(" %s" % sub)
        assert "--config-dir %s" % harness.config_dir in line
        assert "env reshare-control" not in line


def test_web_unit_restarts_and_timer_is_accurate(harness):
    code, out, _ = harness.run()
    assert code == 0, out
    web = harness.unit("reshare-control-web.service")
    assert "Restart=on-failure" in web
    assert "WantedBy=multi-user.target" in web
    timer = harness.unit("reshare-control.timer")
    assert "AccuracySec=1s" in timer
    assert "OnUnitActiveSec=5min" in timer


def test_never_enrolls_or_installs_vpn(harness):
    harness.remove_python38()
    code, out, calls = harness.run(RC_BOOTSTRAP_KEY="kns-test", RC_SKIP_VPN="0")
    assert code == 0, out
    lowered = calls.lower()
    assert "wireguard" not in lowered
    assert "enroll" not in lowered
    assert "wg-quick" not in lowered


def test_firewall_opens_only_web_port_even_with_vpn_config(harness):
    harness.config_dir.mkdir(mode=0o700)
    code, out, _ = harness.run()
    assert code == 0, out
    config = harness.config_dir / "config.json"
    data = json.loads(config.read_text())
    data["vpn"] = dict(data.get("vpn") or {}, enabled=True, wg_port=7001,
                       wg_listen_port=51820)
    config.write_text(json.dumps(data))
    harness.calls.write_text("")
    code, out, calls = harness.run()
    assert code == 0, out
    ufw_allows = [l for l in calls.splitlines() if l.startswith("ufw allow")]
    assert ufw_allows == ["ufw allow %s/tcp" % data["web"]["port"]]


def test_without_systemd_falls_back_to_cron(harness):
    code, out, calls = harness.run(STUB_NO_SYSTEMD="1")
    assert code == 0, out
    assert not (harness.systemd_dir / "reshare-control.timer").exists()
    cron = harness.crontab.read_text()
    assert "*/5 * * * *" in cron
    assert "%s -m reshare_control" % (harness.bin / "python3.8") in cron
    assert cron.rstrip().endswith("# reshare-control")


def test_generated_web_command_serves_the_panel(harness):
    """The ExecStart the installer wrote really starts the same web interface."""
    import base64
    import socket
    import time
    import urllib.request

    code, out, _ = harness.run()
    assert code == 0, out
    password = [l for l in out.splitlines() if l.startswith("Password: ")][0][len("Password: "):]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    exec_line = [l for l in harness.unit("reshare-control-web.service").splitlines()
                 if l.startswith("ExecStart=")][0][len("ExecStart="):]
    cmd = exec_line + " --host 127.0.0.1 --port %d" % port
    proc = subprocess.Popen(["sh", "-c", "exec " + cmd],
                            env={"PATH": "%s:/usr/bin:/bin" % harness.bin},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    token = base64.b64encode(("admin:%s" % password).encode()).decode()
    request = urllib.request.Request("http://127.0.0.1:%d/" % port,
                                     headers={"Authorization": "Basic " + token})
    try:
        status, body = None, ""
        for _ in range(50):
            try:
                with urllib.request.urlopen(request, timeout=1) as resp:
                    status, body = resp.status, resp.read().decode()
                break
            except OSError:
                time.sleep(0.1)
        assert status == 200
        assert "OSCAM Reshare Control" in body or "Reshare" in body
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# --- User Story 3: safe re-run ------------------------------------------------

def test_rerun_keeps_config_and_password(harness):
    code, out, _ = harness.run()
    assert code == 0, out
    config = harness.config_dir / "config.json"
    before = config.read_bytes()
    code, out, _ = harness.run()
    assert code == 0, out
    assert config.read_bytes() == before
    assert "existing password in %s/config.json" % harness.config_dir in out
