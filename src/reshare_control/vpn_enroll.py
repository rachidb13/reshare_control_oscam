"""WireGuard VPN node enrollment for the kanasavpn fleet."""

from __future__ import print_function

import datetime
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import (
    AppConfig,
    DEFAULT_OSCAM_CHECKER_BINARY_URL,
    save_app_config,
)


PUBLIC_IP_URL = "https://api.ipify.org"
ALLOCATE_PORTS = list(range(3280, 3300))
AGENT_PORT = 8080


class EnrollmentError(RuntimeError):
    """Raised when VPN enrollment cannot complete."""


class HttpResponse(object):
    def __init__(self, status_code, body="", data=None):
        self.status_code = status_code
        self.body = body
        self.data = data


class UrlLibHttpClient(object):
    def __call__(self, method, url, headers=None, json_data=None, timeout=10):
        body = b""
        request_headers = dict(headers or {})
        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8")
                return HttpResponse(response.getcode(), text, _loads_json(text))
        except HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            return HttpResponse(exc.code, text, _loads_json(text))
        except URLError as exc:
            raise EnrollmentError("network error calling %s: %s" % (_redact_url(url), exc))


def enroll(config, config_dir, logger, dry_run=False, http_client=None,
           command_runner=None, downloader=None, public_ip_resolver=None,
           port_probe=None, system_root="/"):
    if not isinstance(config, AppConfig):
        config = AppConfig.from_dict(config)
    working = AppConfig.from_dict(config.to_dict()) if dry_run else config
    vpn = working.vpn
    http = http_client or UrlLibHttpClient()
    runner = command_runner or _run_command
    fetch = downloader or _download_file
    public_ip = None

    logger.info("starting VPN enrollment")
    vpn.enabled = True
    vpn.bootstrap_key = vpn.bootstrap_key.strip()
    if not vpn.bootstrap_key:
        raise EnrollmentError("bootstrap key missing: set RC_BOOTSTRAP_KEY for VPN enrollment")
    if not vpn.oscam_checker_binary_url or vpn.oscam_checker_binary_url == DEFAULT_OSCAM_CHECKER_BINARY_URL:
        raise EnrollmentError("oscam-checker download URL missing: set RC_OSCAM_CHECKER_URL")
    if not vpn.agent_id:
        vpn.agent_id = str(uuid.uuid4())
    _persist(working, config_dir, dry_run)
    if dry_run:
        logger.info("dry run: VPN enrollment would allocate, configure WireGuard, install checker, and register")
        return working

    public_ip = _resolve_public_ip(public_ip_resolver)
    if not (vpn.server_key and vpn.wg_port and vpn.wg_subnet):
        ports = _free_ports(ALLOCATE_PORTS, port_probe)
        if not ports:
            raise EnrollmentError("allocate failed: no free ports in 3280-3299")
        logger.info("allocating kanasavpn node")
        data = _api_post(
            http,
            "allocate",
            "%s/allocate.php" % vpn.wg_api_url.rstrip("/"),
            {
                "agent_id": vpn.agent_id,
                "endpoint": public_ip,
                "available_ports": ports,
                "agent_port": AGENT_PORT,
            },
            headers={"X-BOOTSTRAP-KEY": vpn.bootstrap_key},
        )
        vpn.server_key = _require_field(data, "server_key", "allocate")
        vpn.wg_port = int(_require_field(data, "port", "allocate"))
        vpn.wg_subnet = _require_field(data, "subnet", "allocate")
        _persist(working, config_dir, dry_run)
    else:
        logger.info("reusing stored kanasavpn allocation")

    paths = EnrollmentPaths(system_root)
    _configure_wireguard(vpn, paths, runner, dry_run)
    _configure_checker(vpn, paths, runner, fetch, dry_run)

    public_key = _read_text(paths.wg_public_key).strip()
    if not public_key:
        raise EnrollmentError("register failed: missing WireGuard public key")
    logger.info("registering kanasavpn node")
    _api_post(
        http,
        "register",
        "%s/register.php" % vpn.wg_api_url.rstrip("/"),
        {
            "agent_id": vpn.agent_id,
            "public_key": public_key,
            "endpoint": "%s:%s" % (public_ip, vpn.wg_listen_port),
            "listen_port": vpn.wg_listen_port,
            "agent_url": "http://%s:%s" % (public_ip, vpn.wg_port),
        },
        headers={"X-BOOTSTRAP-KEY": vpn.bootstrap_key},
    )

    vpn.status = "enrolled"
    vpn.enrolled_at = _utcnow()
    _persist(working, config_dir, dry_run)
    logger.info("VPN enrollment complete")
    return working


class EnrollmentPaths(object):
    def __init__(self, system_root="/"):
        root = system_root or "/"
        self.root = root
        self.wireguard_dir = self.path("/etc/wireguard")
        self.sysctl_conf = self.path("/etc/sysctl.d/99-reshare-vpn.conf")
        self.wg_private_key = self.path("/etc/wireguard/privatekey")
        self.wg_public_key = self.path("/etc/wireguard/publickey")
        self.wg_conf = self.path("/etc/wireguard/wg0.conf")
        self.checker_dir = self.path("/opt/reshare-control/oscam-checker")
        self.checker_binary = self.path("/opt/reshare-control/oscam-checker/oscam-checker")
        self.checker_env = self.path("/opt/reshare-control/oscam-checker/oscam-checker-env.env")
        self.checker_service = self.path("/etc/systemd/system/oscam-checker.service")

    def path(self, absolute_path):
        if self.root == "/":
            return absolute_path
        return os.path.join(self.root, absolute_path.lstrip("/"))


def render_wg0_conf(private_key, address, listen_port, default_iface):
    return "\n".join([
        "[Interface]",
        "Address = %s" % address,
        "ListenPort = %s" % listen_port,
        "PrivateKey = %s" % private_key,
        "PostUp = iptables -t nat -A POSTROUTING -o %s -j MASQUERADE" % default_iface,
        "PostDown = iptables -t nat -D POSTROUTING -o %s -j MASQUERADE" % default_iface,
        "",
    ])


def wg_address_from_subnet(subnet):
    network = ipaddress.ip_network(str(subnet), strict=False)
    return "%s/%s" % (network.network_address + 1, network.prefixlen)


def _api_post(http, step, url, payload, headers=None):
    response = http("POST", url, headers=headers or {}, json_data=payload, timeout=10)
    status = _response_status(response)
    data = _response_data(response)
    if 200 <= status < 300:
        return data
    reason = _error_reason(step, status, data, _response_body(response))
    raise EnrollmentError(reason)


def _error_reason(step, status, data, body):
    message = ""
    if isinstance(data, dict):
        message = data.get("error") or data.get("message") or ""
    if not message:
        message = body or "HTTP %s" % status
    if step in ("allocate", "register") and status == 401:
        return "bad bootstrap key: %s" % message
    return "%s failed: %s" % (step, message)


def _configure_wireguard(vpn, paths, runner, dry_run):
    _run(runner, ["apt-get", "install", "-y", "wireguard", "wireguard-tools", "iptables"], dry_run)
    _write_file(paths.sysctl_conf, "net.ipv4.ip_forward=1\n", 0o644, dry_run)
    _run(runner, ["sysctl", "-p", paths.sysctl_conf], dry_run)
    _mkdir(paths.wireguard_dir, 0o700, dry_run)
    if not os.path.exists(paths.wg_private_key):
        private_key = _generate_private_key(runner, dry_run)
        _write_file(paths.wg_private_key, private_key, 0o600, dry_run)
    else:
        private_key = _read_text(paths.wg_private_key).strip()
    if not os.path.exists(paths.wg_public_key):
        public_key = _generate_public_key(private_key, runner, dry_run)
        _write_file(paths.wg_public_key, public_key, 0o600, dry_run)
    if not os.path.exists(paths.wg_conf):
        default_iface = _default_iface(runner, dry_run)
        content = render_wg0_conf(
            private_key,
            wg_address_from_subnet(vpn.wg_subnet),
            vpn.wg_listen_port,
            default_iface,
        )
        _write_file(paths.wg_conf, content, 0o600, dry_run)
    _run(runner, ["systemctl", "enable", "--now", "wg-quick@wg0"], dry_run)


def _configure_checker(vpn, paths, runner, downloader, dry_run):
    _mkdir(paths.checker_dir, 0o700, dry_run)
    if dry_run:
        return
    try:
        downloader(vpn.oscam_checker_binary_url, paths.checker_binary)
    except Exception as exc:
        raise EnrollmentError("download failed: %s" % exc)
    os.chmod(paths.checker_binary, 0o700)
    env = "\n".join([
        "PORT=%s" % vpn.wg_port,
        "SERVER_KEY=%s" % vpn.server_key,
        "WG_SUBNET=%s" % vpn.wg_subnet,
        "KANASA_SERVER_KEY=%s" % vpn.server_key,
        "KANASA_WG_PORT=%s" % vpn.wg_port,
        "KANASA_WG_SUBNET=%s" % vpn.wg_subnet,
        "",
    ])
    _write_file(paths.checker_env, env, 0o600, dry_run)
    service = "\n".join([
        "[Unit]",
        "Description=OSCam checker for kanasavpn",
        "After=network.target wg-quick@wg0.service",
        "",
        "[Service]",
        "Type=simple",
        "EnvironmentFile=%s" % paths.checker_env,
        "ExecStart=%s" % paths.checker_binary,
        "Restart=on-failure",
        "RestartSec=3",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    _write_file(paths.checker_service, service, 0o644, dry_run)
    _run(runner, ["systemctl", "daemon-reload"], dry_run)
    _run(runner, ["systemctl", "enable", "--now", "oscam-checker.service"], dry_run)


def _generate_private_key(runner, dry_run):
    if dry_run:
        return "DRY_RUN_PRIVATE_KEY"
    output = _run(runner, ["wg", "genkey"], dry_run, capture=True)
    return output.strip()


def _generate_public_key(private_key, runner, dry_run):
    if dry_run:
        return "DRY_RUN_PUBLIC_KEY"
    output = _run(runner, ["wg", "pubkey"], dry_run, capture=True, input_text=private_key + "\n")
    return output.strip()


def _default_iface(runner, dry_run):
    if dry_run:
        return "eth0"
    try:
        output = _run(runner, ["ip", "route", "show", "default"], dry_run, capture=True)
    except EnrollmentError:
        return "eth0"
    parts = output.split()
    if "dev" in parts:
        index = parts.index("dev")
        if index + 1 < len(parts):
            return parts[index + 1]
    return "eth0"


def _run(runner, command, dry_run=False, capture=False, input_text=None):
    if dry_run:
        return ""
    return runner(command, capture=capture, input_text=input_text)


def _run_command(command, capture=False, input_text=None):
    kwargs = {}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["text"] = True
    if input_text is not None:
        kwargs["input"] = input_text
        kwargs["text"] = True
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        result = subprocess.run(command, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        stderr = getattr(exc, "stderr", "") or str(exc)
        raise EnrollmentError("command failed (%s): %s" % (" ".join(command), stderr.strip()))
    if capture or input_text is not None:
        return result.stdout
    return ""


def _download_file(url, destination):
    request = Request(url)
    directory = os.path.dirname(destination)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    fd, tmp_path = tempfile.mkstemp(prefix=".download.", suffix=".tmp", dir=directory or ".")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            with urlopen(request, timeout=20) as response:
                shutil.copyfileobj(response, fh)
        os.replace(tmp_path, destination)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _persist(config, config_dir, dry_run):
    if not dry_run:
        save_app_config(config, config_dir)


def _free_ports(candidates, port_probe=None):
    probe = port_probe or _port_free
    return [port for port in candidates if probe(port)]


def _port_free(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _resolve_public_ip(public_ip_resolver=None):
    if public_ip_resolver:
        value = public_ip_resolver()
    else:
        with urlopen(PUBLIC_IP_URL, timeout=10) as response:
            value = response.read().decode("ascii")
    value = str(value).strip()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise EnrollmentError("public IP lookup failed: invalid IP returned")
    return value


def _write_file(path, content, mode, dry_run=False):
    if dry_run:
        return
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    fd, tmp_path = tempfile.mkstemp(prefix=".reshare.", suffix=".tmp", dir=directory or ".")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
        os.chmod(path, mode)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _mkdir(path, mode, dry_run=False):
    if dry_run:
        return
    os.makedirs(path, mode, exist_ok=True)
    os.chmod(path, mode)


def _read_text(path):
    try:
        with open(path, "r") as fh:
            return fh.read()
    except IOError as exc:
        raise EnrollmentError("cannot read %s: %s" % (path, exc))


def _require_field(data, field, step):
    if not isinstance(data, dict) or field not in data:
        raise EnrollmentError("%s failed: response missing %s" % (step, field))
    return data[field]


def _response_status(response):
    if isinstance(response, dict):
        value = response.get("status_code", 200)
    else:
        value = getattr(response, "status_code", getattr(response, "status", 200))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 200


def _response_data(response):
    if isinstance(response, dict):
        if "data" in response:
            return response["data"]
        return response
    data = getattr(response, "data", None)
    if data is not None:
        return data
    return _loads_json(_response_body(response))


def _response_body(response):
    if isinstance(response, dict):
        return str(response.get("body", ""))
    return str(getattr(response, "body", ""))


def _loads_json(text):
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {}


def _redact_url(url):
    return str(url).split("?", 1)[0]


def _utcnow():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
