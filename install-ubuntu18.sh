#!/bin/sh
# Installer for Ubuntu 18.04 only. Installs the same web panel and poller as
# install.sh, but runs them on the archive's python3.8 (18.04's python3 is 3.6,
# which cannot run the app) and never sets up the reshare link / VPN node.
# Every newer system should use install.sh instead.
set -eu

CONFIG_DIR=${RC_CONFIG_DIR:-/etc/reshare-control}
SYSTEMD_DIR=${RC_SYSTEMD_DIR:-/etc/systemd/system}
OS_RELEASE=${RC_OS_RELEASE:-/etc/os-release}
CRON_MARKER="# reshare-control"
SOURCE_URL=${RC_SOURCE_URL:-https://github.com/rachidb13/reshare_control_oscam/archive/refs/heads/master.tar.gz}
INSTALL_DIR=${RC_INSTALL_DIR:-/opt/reshare-control}
STANDARD_INSTALL="curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/master/install.sh | sudo sh"
# The app reads these into its link config; none of them may reach this box.
unset RC_BOOTSTRAP_KEY RC_WG_API_URL RC_OSCAM_CHECKER_URL 2>/dev/null || true

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)
source_dir=
if [ -n "${RC_SOURCE_DIR:-}" ] && [ -d "$RC_SOURCE_DIR/reshare_control" ]; then
    source_dir=$RC_SOURCE_DIR
elif [ -d "$script_dir/src/reshare_control" ]; then
    source_dir=$script_dir/src
fi

# Prefer the terminal, as install.sh does, but fall back to stderr so a run
# without one (CI, nohup) still reports instead of aborting under set -e.
say() {
    if ! { printf '%s\n' "$*" > /dev/tty; } 2>/dev/null; then
        printf '%s\n' "$*" >&2
    fi
}

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

# Runs before anything is written: a refused run must leave no trace.
check_os() {
    os_id=""
    os_version=""
    os_name="unknown"
    if [ -r "$OS_RELEASE" ]; then
        os_id=$(. "$OS_RELEASE" 2>/dev/null && printf '%s' "${ID:-}")
        os_version=$(. "$OS_RELEASE" 2>/dev/null && printf '%s' "${VERSION_ID:-}")
        os_name=$(. "$OS_RELEASE" 2>/dev/null && printf '%s' "${PRETTY_NAME:-unknown}")
    fi
    if [ "$os_id" = "ubuntu" ] && [ "$os_version" = "18.04" ]; then
        return
    fi
    if [ "$os_id" = "ubuntu" ]; then
        say "Unsupported version: $os_name"
    else
        say "Unsupported system: $os_name"
    fi
    say "This installer supports Ubuntu 18.04 only."
    if [ "$os_id" = "ubuntu" ] && [ "$(version_rank "$os_version")" -gt "$(version_rank 18.04)" ]; then
        say "Newer Ubuntu releases use the standard installer:"
        say "  $STANDARD_INSTALL"
    fi
    exit 1
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        say "This installer must run as root (use sudo)."
        exit 1
    fi
}

python_is_supported() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

# The system python3 stays at 3.6 because Ubuntu's own tools depend on it; the
# app gets python3.8 from the archive (bionic-updates, universe) beside it.
ensure_runtime() {
    missing=
    command -v python3.8 >/dev/null 2>&1 || missing="python3.8"
    command -v curl >/dev/null 2>&1 || missing="$missing curl"
    if [ -n "$missing" ]; then
        apt_log=$tmpdir/apt.log
        if ! { apt-get update -q && \
               DEBIAN_FRONTEND=noninteractive apt-get install -y -q $missing; } > "$apt_log" 2>&1; then
            say "Could not install:$missing"
            tail -n 5 "$apt_log" 2>/dev/null | while IFS= read -r line; do say "  $line"; done
            say "python3.8 comes from the Ubuntu 'universe' component. If it is disabled, run:"
            say "  add-apt-repository universe && apt-get update"
            say "then run this installer again."
            exit 1
        fi
    fi
    PYTHON=$(command -v python3.8 2>/dev/null || true)
    if [ -z "$PYTHON" ] || ! python_is_supported "$PYTHON"; then
        say "python3.8 is not usable after installation; nothing else was installed."
        exit 1
    fi
}

run_python() {
    PYTHONPATH=$source_dir${PYTHONPATH+:$PYTHONPATH} "$PYTHON" "$@"
}

poll_interval_min() {
    # The smallest interval any instance asks for: one run polls them all, so
    # the tightest requirement is the one the schedule has to meet.
    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        printf '5'
        return
    fi
    run_python - "$CONFIG_DIR/config.json" <<'PY' || printf '5'
import json
import sys

try:
    with open(sys.argv[1], "r") as fh:
        data = json.load(fh)
    values = [
        instance.get("poll_interval_min")
        for instance in data.get("instances", [])
    ]
    if not values:
        # A v1 config kept the interval at the top level.
        values = [data.get("poll_interval_min")]
    values = [int(value) for value in values if value not in (None, "")]
    interval = min(values) if values else 5
    print(interval if interval >= 1 else 5)
except Exception:
    print(5)
PY
}

# Unlike install.sh, a reshare-control already on PATH is not a reason to skip
# the fetch: on 18.04 it may be a 3.6 entry point, and the services must run the
# fetched source on python3.8.
fetch_source_if_needed() {
    if [ -n "$source_dir" ]; then
        return
    fi
    archive=$tmpdir/source.tar.gz
    extract_dir=$tmpdir/source
    mkdir -p "$extract_dir"
    if ! curl -fsSL "$SOURCE_URL" -o "$archive"; then
        say "Could not download $SOURCE_URL"
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
    printf 'PYTHONPATH=%s %s -m reshare_control --config-dir %s %s' "$source_dir" "$PYTHON" "$CONFIG_DIR" "$1"
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
ExecStart=/usr/bin/env reshare-control --config-dir /etc/reshare-control run-all
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
    timer_interval=$(poll_interval_min)
    # AccuracySec defaults to a minute, which at short intervals lets systemd
    # drift a cycle's worth; the poller measures rates between firings.
    sed -e "s|^OnUnitActiveSec=.*|OnUnitActiveSec=${timer_interval}min|" \
        -e "/^AccuracySec=/d" \
        -e "s|^\[Timer\]|[Timer]\nAccuracySec=1s|" \
        "$SYSTEMD_DIR/reshare-control.timer" > "$SYSTEMD_DIR/reshare-control.timer.tmp"
    mv "$SYSTEMD_DIR/reshare-control.timer.tmp" "$SYSTEMD_DIR/reshare-control.timer"
    escaped_runner_cmd=$(printf '%s\n' "$runner_cmd" | sed 's/[|&]/\\&/g')
    sed "s|^ExecStart=.*|ExecStart=/usr/bin/env $escaped_runner_cmd|" "$SYSTEMD_DIR/reshare-control.service" > "$SYSTEMD_DIR/reshare-control.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control.service.tmp" "$SYSTEMD_DIR/reshare-control.service"
    escaped_web_runner_cmd=$(printf '%s\n' "$web_runner_cmd" | sed 's/[|&]/\\&/g')
    sed "s|^ExecStart=.*|ExecStart=/usr/bin/env $escaped_web_runner_cmd|" "$SYSTEMD_DIR/reshare-control-web.service" > "$SYSTEMD_DIR/reshare-control-web.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control-web.service.tmp" "$SYSTEMD_DIR/reshare-control-web.service"
    systemctl daemon-reload
    systemctl enable --now --quiet reshare-control.timer
    systemctl enable --now --quiet reshare-control-web.service
    # enable --now leaves an already-running panel on the old code after a re-run.
    systemctl restart reshare-control-web.service
}

install_cron() {
    interval=$(poll_interval_min)
    cron_expr="*/$interval * * * * $runner_cmd $CRON_MARKER"
    old_cron=$tmpdir/cron.old
    new_cron=$tmpdir/cron.new
    crontab -l > "$old_cron" 2>/dev/null || true
    grep -v 'reshare-control' "$old_cron" > "$new_cron" || true
    printf '%s\n' "$cron_expr" >> "$new_cron"
    crontab "$new_cron"
}

# Only the panel port. Link ports stay closed even when a copied config has the
# link enabled, because no link runs here. Never turns a firewall on: enabling
# one mid-install could cut the operator's own SSH session.
open_firewall_ports() {
    port=$(run_python - "$CONFIG_DIR" <<'PY'
import json
import os
import sys

try:
    with open(os.path.join(sys.argv[1], "config.json")) as fh:
        port = int((json.load(fh).get("web") or {}).get("port"))
except (IOError, OSError, ValueError, TypeError):
    raise SystemExit(0)
if 0 < port < 65536:
    print("%d/tcp" % port)
PY
    ) || return 0
    [ -n "$port" ] || return 0
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -qi 'status: active'; then
        ufw allow "$port" >/dev/null 2>&1 || true
        return 0
    fi
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="$port" >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
}

check_os
check_root

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/reshare-control.XXXXXX")
chmod 700 "$tmpdir"
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT HUP INT TERM

say "---- start installation (Ubuntu 18.04) ------"
say "installing python3.8 . . ."
ensure_runtime
say "loading . . ."
fetch_source_if_needed

umask 077
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
admin_password=$(ensure_web_config "$CONFIG_DIR")

runner_cmd=$(python_module_command run-all)
web_runner_cmd=$(python_module_command web)

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
