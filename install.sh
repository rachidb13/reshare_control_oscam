#!/bin/sh
set -eu

CONFIG_DIR=${RC_CONFIG_DIR:-/etc/reshare-control}
PYTHON=${PYTHON:-python3}
SYSTEMD_DIR=${RC_SYSTEMD_DIR:-/etc/systemd/system}
CRON_MARKER="# reshare-control"
SOURCE_URL=${RC_SOURCE_URL:-}
INSTALL_DIR=${RC_INSTALL_DIR:-/opt/reshare-control}

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

python_module_runner() {
    if [ -n "$source_dir" ]; then
        printf 'PYTHONPATH=%s %s -m reshare_control --config-dir %s run' "$source_dir" "$PYTHON" "$CONFIG_DIR"
    else
        printf '%s -m reshare_control --config-dir %s run' "$PYTHON" "$CONFIG_DIR"
    fi
}

write_config() {
    target_dir=$1
    (
    RC_WRITE_CONFIG_DIR=$target_dir
    RC_WRITE_HOST=$host
    RC_WRITE_PORT=$port
    RC_WRITE_USER=$webif_user
    RC_WRITE_PASS=$webif_pass
    export RC_WRITE_CONFIG_DIR RC_WRITE_HOST RC_WRITE_PORT RC_WRITE_USER RC_WRITE_PASS
    run_python - <<'PY'
import os
from reshare_control.config import InstanceConfig, save_config

config = InstanceConfig(
    host=os.environ["RC_WRITE_HOST"],
    port=os.environ["RC_WRITE_PORT"],
    webif_user=os.environ.get("RC_WRITE_USER", ""),
    webif_pass=os.environ.get("RC_WRITE_PASS", ""),
)
save_config(config, os.environ["RC_WRITE_CONFIG_DIR"])
PY
    )
    chmod 700 "$target_dir"
    chmod 600 "$target_dir/config.json"
}

run_validation() {
    write_config "$tmpdir"
    run_python -m reshare_control --config-dir "$tmpdir" test
}

collect_connection() {
    prompt "OSCAM WebIF host: " host
    prompt "OSCAM WebIF port: " port
    prompt "OSCAM WebIF username (blank for open WebIF): " webif_user
    prompt_password "OSCAM WebIF password (blank for open WebIF): " webif_pass
}

fetch_source_if_needed
collect_connection

while :; do
    status=0
    run_validation || status=$?
    if [ "$status" -eq 0 ]; then
        say "WebIF validation succeeded."
        break
    fi
    case $status in
        2)
            say "authentication failed"
            prompt "OSCAM WebIF username (blank for open WebIF): " webif_user
            prompt_password "OSCAM WebIF password (blank for open WebIF): " webif_pass
            ;;
        3)
            say "unreachable -- check host/port"
            prompt "Re-enter host/port or abort? [r/a]: " choice
            case $choice in
                a|A) say "Aborted."; exit 1 ;;
                *) prompt "OSCAM WebIF host: " host
                   prompt "OSCAM WebIF port: " port ;;
            esac
            ;;
        4)
            say "reachable but no usable ECM/min stats"
            prompt "Continue anyway? [y/N]: " choice
            case $choice in
                y|Y) break ;;
                *) say "Aborted."; exit 1 ;;
            esac
            ;;
        *)
            say "validation failed with exit code $status"
            exit "$status"
            ;;
    esac
done

umask 077
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
write_config "$CONFIG_DIR"

runner="reshare-control --config-dir $CONFIG_DIR run"
if command -v reshare-control >/dev/null 2>&1; then
    runner_cmd=$runner
else
    runner_cmd=$(python_module_runner)
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
ProtectSystem=full
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
    escaped_config_dir=$(printf '%s\n' "$CONFIG_DIR" | sed 's/[|&]/\\&/g')
    sed "s|/etc/reshare-control|$escaped_config_dir|g" "$SYSTEMD_DIR/reshare-control.service" > "$SYSTEMD_DIR/reshare-control.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control.service.tmp" "$SYSTEMD_DIR/reshare-control.service"
    escaped_runner_cmd=$(printf '%s\n' "$runner_cmd" | sed 's/[|&]/\\&/g')
    sed "s|^ExecStart=.*|ExecStart=/usr/bin/env $escaped_runner_cmd|" "$SYSTEMD_DIR/reshare-control.service" > "$SYSTEMD_DIR/reshare-control.service.tmp"
    mv "$SYSTEMD_DIR/reshare-control.service.tmp" "$SYSTEMD_DIR/reshare-control.service"
    systemctl daemon-reload
    systemctl enable --now reshare-control.timer
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

if command -v systemctl >/dev/null 2>&1 && systemctl >/dev/null 2>&1; then
    install_systemd
    say "Installed systemd timer reshare-control.timer."
else
    install_cron
    say "Installed cron schedule for reshare-control."
fi

say "Configuration saved to $CONFIG_DIR/config.json."
