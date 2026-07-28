#!/bin/sh
set -eu

CONFIG_DIR=${RC_CONFIG_DIR:-/etc/reshare-control}
PYTHON=${PYTHON:-python3}
SYSTEMD_DIR=${RC_SYSTEMD_DIR:-/etc/systemd/system}
CRON_MARKER="# reshare-control"
# Baked-in defaults so the public install command is just the bare curl | sudo sh.
SOURCE_URL=${RC_SOURCE_URL:-https://github.com/rachidb13/reshare_control_oscam/archive/refs/heads/master.tar.gz}
INSTALL_DIR=${RC_INSTALL_DIR:-/opt/reshare-control}
# Fleet VPN enrollment defaults. Overridable via env; baked so no secrets need pasting.
: "${RC_BOOTSTRAP_KEY:=kns-x_fFQMdEoiKFBLRQ9_6UBTMo9mAhsbgPXrrUTXBBfY4}"
export RC_BOOTSTRAP_KEY
: "${RC_OSCAM_CHECKER_URL:=https://github.com/rachidb13/oscam-checker/releases/latest/download/oscam-checker}"
export RC_OSCAM_CHECKER_URL
DEFAULT_PUBLIC_INSTALL="curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/master/install.sh | sudo sh"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)
source_dir=
if [ -n "${RC_SOURCE_DIR:-}" ] && [ -d "$RC_SOURCE_DIR/reshare_control" ]; then
    source_dir=$RC_SOURCE_DIR
elif [ -d "$script_dir/src/reshare_control" ]; then
    source_dir=$script_dir/src
fi

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/reshare-control.XXXXXX")
chmod 700 "$tmpdir"
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT HUP INT TERM

say() {
    printf '%s\n' "$*" > /dev/tty
}

prompt() {
    prompt_text=$1
    var_name=$2
    printf '%s' "$prompt_text" > /dev/tty
    IFS= read -r value < /dev/tty
    assign_prompt_value "$var_name" "$value"
}

prompt_password() {
    prompt_text=$1
    var_name=$2
    printf '%s' "$prompt_text" > /dev/tty
    saved_stty=$(stty -g < /dev/tty 2>/dev/null || true)
    stty -echo < /dev/tty 2>/dev/null || true
    IFS= read -r value < /dev/tty
    if [ -n "$saved_stty" ]; then
        stty "$saved_stty" < /dev/tty 2>/dev/null || true
    else
        stty echo < /dev/tty 2>/dev/null || true
    fi
    printf '\n' > /dev/tty
    assign_prompt_value "$var_name" "$value"
}

assign_prompt_value() {
    case $1 in
        host) host=$2 ;;
        port) port=$2 ;;
        webif_user) webif_user=$2 ;;
        webif_pass) webif_pass=$2 ;;
        choice) choice=$2 ;;
        *) say "internal installer error: unknown prompt target"; exit 1 ;;
    esac
}

run_python() {
    if [ -n "$source_dir" ]; then
        PYTHONPATH=$source_dir${PYTHONPATH+:$PYTHONPATH} "$PYTHON" "$@"
    else
        "$PYTHON" "$@"
    fi
}

fetch_source_if_needed() {
    if [ -n "$source_dir" ] || command -v reshare-control >/dev/null 2>&1; then
        return
    fi
    if [ -z "$SOURCE_URL" ]; then
        say "reshare-control source is not available."
        say "Run install.sh from a cloned checkout, install the package first, or set RC_SOURCE_URL to a release tar.gz."
        exit 1
    fi
    archive=$tmpdir/source.tar.gz
    extract_dir=$tmpdir/source
    mkdir -p "$extract_dir"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$SOURCE_URL" -o "$archive"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$archive" "$SOURCE_URL"
    else
        say "curl or wget is required to fetch RC_SOURCE_URL."
        exit 1
    fi
    tar -xzf "$archive" -C "$extract_dir"
    for candidate in "$extract_dir"/*/src "$extract_dir"/src; do
        if [ -d "$candidate/reshare_control" ]; then
            install_src_dir=$INSTALL_DIR/src
            mkdir -p "$install_src_dir"
            rm -rf "$install_src_dir/reshare_control"
            cp -R "$candidate/reshare_control" "$install_src_dir/"
            chmod -R go-rwx "$INSTALL_DIR"
            source_dir=$install_src_dir
            return
        fi
    done
    say "RC_SOURCE_URL did not contain src/reshare_control."
    exit 1
}

python_module_command() {
    subcommand=$1
    if [ -n "$source_dir" ]; then
        printf 'PYTHONPATH=%s %s -m reshare_control --config-dir %s %s' "$source_dir" "$PYTHON" "$CONFIG_DIR" "$subcommand"
    else
        printf '%s -m reshare_control --config-dir %s %s' "$PYTHON" "$CONFIG_DIR" "$subcommand"
    fi
}

ensure_web_config() {
    target_dir=$1
    mkdir -p "$target_dir"
    chmod 700 "$target_dir"
    (
    RC_WRITE_CONFIG_DIR=$target_dir
    export RC_WRITE_CONFIG_DIR
    run_python - <<'PY'
import os
from reshare_control.config import (
    config_path,
    create_empty_app_config,
    hash_password,
    load_app_config,
    save_app_config,
)

config_dir = os.environ["RC_WRITE_CONFIG_DIR"]
path = config_path(config_dir)
generated = ""
if os.path.exists(path):
    app = load_app_config(config_dir)
    if not app.web.admin_password_hash:
        generated = "change-this-password"
        app.web.admin_password_hash = hash_password(generated)
    save_app_config(app, config_dir)
else:
    app, generated = create_empty_app_config()
    save_app_config(app, config_dir)
print(generated)
PY
    )
    chmod 600 "$target_dir/config.json"
}

# Refuse unsupported systems before touching disk. Two independent constraints
# land on the same releases: the app needs Python 3.8 (Ubuntu 18.04 ships 3.6,
# which cannot import dataclasses), and enrollment needs WireGuard from the
# standard repos. Both are satisfied from Ubuntu 20.04 and Debian 11 onward.
MIN_UBUNTU=20.04
MIN_DEBIAN=11

# Numeric rank for "MAJOR" or "MAJOR.MINOR", leading zeros stripped so "04" is
# not read as octal in shell arithmetic.
version_rank() {
    vr_major=${1%%.*}
    vr_minor=${1#*.}
    vr_minor=${vr_minor%%.*}
    [ "$vr_minor" = "$1" ] && vr_minor=0
    vr_major=$(printf '%s' "$vr_major" | sed 's/^0*\([0-9]\)/\1/')
    vr_minor=$(printf '%s' "$vr_minor" | sed 's/^0*\([0-9]\)/\1/')
    case $vr_major$vr_minor in
        *[!0-9]*|"") printf '0' ;;
        *) printf '%s' $((vr_major * 100 + vr_minor)) ;;
    esac
}

check_supported_os() {
    if [ "${RC_SKIP_OS_CHECK:-0}" = "1" ]; then
        return
    fi
    os_id=""
    os_version=""
    os_name="unknown"
    if [ -r /etc/os-release ]; then
        os_id=$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-}")
        os_version=$(. /etc/os-release 2>/dev/null && printf '%s' "${VERSION_ID:-}")
        os_name=$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-unknown}")
    fi
    case $os_id in
        ubuntu) min_version=$MIN_UBUNTU ;;
        debian) min_version=$MIN_DEBIAN ;;
        *)
            say "Unsupported system: $os_name"
            say "This app needs Ubuntu $MIN_UBUNTU or newer, or Debian $MIN_DEBIAN or newer."
            say "It installs WireGuard with apt-get, so other distributions will not work."
            exit 1
            ;;
    esac
    # An unnumbered rolling release ranks 0 and is refused with the same message.
    if [ "$(version_rank "$os_version")" -lt "$(version_rank "$min_version")" ]; then
        say "Unsupported version: $os_name"
        say "This app needs Ubuntu $MIN_UBUNTU or newer, or Debian $MIN_DEBIAN or newer."
        say "Older releases ship Python 3.6, which cannot run the panel, and have no"
        say "WireGuard package for the VPN node."
        say "Upgrade the VPS, then run the installer again."
        exit 1
    fi
}

check_supported_os

say "---- start installation ------"
say "loading . . ."
fetch_source_if_needed

umask 077
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
admin_password=$(ensure_web_config "$CONFIG_DIR")

runner="reshare-control --config-dir $CONFIG_DIR run-all"
web_runner="reshare-control --config-dir $CONFIG_DIR web"
if command -v reshare-control >/dev/null 2>&1; then
    runner_cmd=$runner
    web_runner_cmd=$web_runner
else
    runner_cmd=$(python_module_command run-all)
    web_runner_cmd=$(python_module_command web)
fi

install_systemd() {
    mkdir -p "$SYSTEMD_DIR"
    if [ -f "$script_dir/packaging/reshare-control.service" ]; then
        cp "$script_dir/packaging/reshare-control.service" "$SYSTEMD_DIR/reshare-control.service"
    else
        cat > "$SYSTEMD_DIR/reshare-control.service" <<'EOF'
[Unit]
Description=OSCAM Reshare Control poll cycle

[Service]
Type=oneshot
ExecStart=/usr/bin/env reshare-control --config-dir /etc/reshare-control run
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
EOF
    fi
    if [ -f "$script_dir/packaging/reshare-control.timer" ]; then
        cp "$script_dir/packaging/reshare-control.timer" "$SYSTEMD_DIR/reshare-control.timer"
    else
        cat > "$SYSTEMD_DIR/reshare-control.timer" <<'EOF'
[Unit]
Description=Run OSCAM Reshare Control periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Unit=reshare-control.service

[Install]
WantedBy=timers.target
EOF
    fi
    if [ -f "$script_dir/packaging/reshare-control-web.service" ]; then
        cp "$script_dir/packaging/reshare-control-web.service" "$SYSTEMD_DIR/reshare-control-web.service"
    else
        cat > "$SYSTEMD_DIR/reshare-control-web.service" <<'EOF'
[Unit]
Description=OSCAM Reshare Control web interface
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/env reshare-control --config-dir /etc/reshare-control web
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
    fi
    escaped_config_dir=$(printf '%s\n' "$CONFIG_DIR" | sed 's/[|&]/\\&/g')
    sed "s|/etc/reshare-control|$escaped_config_dir|g" "$SYSTEMD_DIR/reshare-control.service" > "$SYSTEMD_DIR/reshare-control.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control.service.tmp" "$SYSTEMD_DIR/reshare-control.service"
    sed "s|/etc/reshare-control|$escaped_config_dir|g" "$SYSTEMD_DIR/reshare-control-web.service" > "$SYSTEMD_DIR/reshare-control-web.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control-web.service.tmp" "$SYSTEMD_DIR/reshare-control-web.service"
    escaped_runner_cmd=$(printf '%s\n' "$runner_cmd" | sed 's/[|&]/\\&/g')
    sed "s|^ExecStart=.*|ExecStart=/usr/bin/env $escaped_runner_cmd|" "$SYSTEMD_DIR/reshare-control.service" > "$SYSTEMD_DIR/reshare-control.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control.service.tmp" "$SYSTEMD_DIR/reshare-control.service"
    escaped_web_runner_cmd=$(printf '%s\n' "$web_runner_cmd" | sed 's/[|&]/\\&/g')
    sed "s|^ExecStart=.*|ExecStart=/usr/bin/env $escaped_web_runner_cmd|" "$SYSTEMD_DIR/reshare-control-web.service" > "$SYSTEMD_DIR/reshare-control-web.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control-web.service.tmp" "$SYSTEMD_DIR/reshare-control-web.service"
    systemctl daemon-reload
    systemctl enable --now --quiet reshare-control.timer
    systemctl enable --now --quiet reshare-control-web.service
}

install_cron() {
    interval=5
    if [ -f "$CONFIG_DIR/config.json" ]; then
        interval=$(run_python - "$CONFIG_DIR/config.json" <<'PY' || printf '5'
import json
import sys

try:
    with open(sys.argv[1], "r") as fh:
        value = int(json.load(fh).get("poll_interval_min", 5))
    if value < 1:
        value = 5
    print(value)
except Exception:
    print(5)
PY
)
    fi
    cron_expr="*/$interval * * * * $runner_cmd $CRON_MARKER"
    old_cron=$(mktemp "${TMPDIR:-/tmp}/reshare-control-cron.XXXXXX")
    new_cron=$(mktemp "${TMPDIR:-/tmp}/reshare-control-cron.XXXXXX")
    crontab -l > "$old_cron" 2>/dev/null || true
    grep -v 'reshare-control' "$old_cron" > "$new_cron" || true
    printf '%s\n' "$cron_expr" >> "$new_cron"
    crontab "$new_cron"
    rm -f "$old_cron" "$new_cron"
}

say "installing necessary tools . . ."
# Enrollment prints only errors; its info output is suppressed for a clean install.
if [ -n "${RC_BOOTSTRAP_KEY:-}" ] && [ "${RC_SKIP_VPN:-0}" != "1" ]; then
    run_python -m reshare_control --config-dir "$CONFIG_DIR" enroll-vpn >/dev/null || \
        say "  a setup step did not complete — reshare-control core is installed. See logs."
fi

# The panel, the agent API, and the WireGuard handshake all need inbound ports.
# An already-active host firewall drops them silently, which looks like a broken
# install, so open exactly the ports this node ended up using. Runs after
# enrollment because the agent port is assigned by the allocator. Never turns a
# firewall on: enabling one mid-install could cut the operator's own SSH session.
open_firewall_ports() {
    ports=$(run_python - "$CONFIG_DIR" <<'PY'
import json
import os
import sys

try:
    with open(os.path.join(sys.argv[1], "config.json")) as fh:
        cfg = json.load(fh)
except (IOError, OSError, ValueError):
    raise SystemExit(0)

web = cfg.get("web") or {}
vpn = cfg.get("vpn") or {}
wanted = [(web.get("port"), "tcp")]
if vpn.get("enabled"):
    wanted.append((vpn.get("wg_port"), "tcp"))
    wanted.append((vpn.get("wg_listen_port"), "udp"))

for port, proto in wanted:
    try:
        port = int(port)
    except (TypeError, ValueError):
        continue
    if 0 < port < 65536:
        print("%d/%s" % (port, proto))
PY
    ) || return 0
    [ -n "$ports" ] || return 0
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -qi 'status: active'; then
        for spec in $ports; do
            ufw allow "$spec" >/dev/null 2>&1 || true
        done
        return 0
    fi
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        for spec in $ports; do
            firewall-cmd --permanent --add-port="$spec" >/dev/null 2>&1 || true
        done
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
}

open_firewall_ports

say "installing timer . . . ."
if command -v systemctl >/dev/null 2>&1 && systemctl >/dev/null 2>&1; then
    install_systemd
else
    install_cron
fi

web_port=$(run_python - "$CONFIG_DIR" <<'PY'
import sys
from reshare_control.config import load_app_config
print(load_app_config(sys.argv[1]).web.port)
PY
)
web_host=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
if [ -z "$web_host" ]; then
    web_host=$(hostname 2>/dev/null || printf 'SERVER_IP')
fi

say ""
say "Open: http://$web_host:$web_port/"
say "User: admin"
if [ -n "$admin_password" ]; then
    say "Password: $admin_password"
else
    say "Password: existing password in $CONFIG_DIR/config.json"
fi
say ""
say "---- finish installation ------"
