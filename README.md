# OSCAM Reshare Control

Browser control panel for OSCam instances running on the same VPS.

It reads local OSCam WebIF statistics, tracks ECM/min per user, sends Telegram
alerts, and can temporarily disable users in `oscam.user` when they stay above
your configured limit.

## Requirements

- Ubuntu 20.04 or newer, or Debian 11 or newer
- OSCam already installed on the same VPS, with its WebIF enabled
- root access

The installer checks the release first and exits without changing anything if
it is not supported. Two constraints set that floor, and both land on the same
releases:

- the panel needs Python 3.8, and Ubuntu 18.04 ships Python 3.6
- VPN enrollment needs the `wireguard` package from the standard repositories

Other distributions are refused because enrollment installs WireGuard with
`apt-get`.

Pass `RC_SKIP_VPN=1` to install the panel without enrolling the VPN node, or
`RC_SKIP_OS_CHECK=1` to bypass the release check entirely.

## Firewall

The installer opens the ports this node actually uses, so a host firewall does
not silently drop them:

| Port | Protocol | Purpose |
| --- | --- | --- |
| web panel port, `8787` by default | tcp | browser control panel |
| agent port, assigned at enrollment | tcp | agent API the VPN hub calls |
| `wg_listen_port`, `51820` by default | udp | WireGuard handshake |

This runs after enrollment, because the agent port is assigned by the allocator.
`ufw` and `firewalld` are both handled. A firewall that is turned off is left
off: enabling one mid-install could cut the operator's own SSH session.

Cloud provider security groups are separate and still need the same ports
allowed. If the panel times out in the browser, that is the usual cause.

## One Command Install

Run this on the VPS that already has OSCam installed:

```sh
curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/master/install.sh | sudo sh
```

The installer starts the web panel and prints:

- browser URL, usually `http://SERVER_IP:8787/`
- username: `admin`
- generated password

If the browser cannot connect, allow TCP port `8787` in your VPS firewall or
provider security group.

## What It Does

- Add multiple OSCam WebIF instances from one panel
- Read users automatically from the local OSCam `oscam.user`
- Show connected, disconnected, flagged, and stopped users
- Set a global ECM/min policy for each OSCam
- Override max ECM/min, action, and stop duration per user
- Send Telegram alerts with OSCam name, username, observed ECM/min, limit, and action
- Stop users temporarily, then re-enable them automatically after the timer expires
- Keep an audit log under `/etc/reshare-control/instances/INSTANCE_ID/`

The default posture is detection only. Users are not disabled unless global
auto-stop is enabled or a specific user policy is set to `Stop`.

## First Setup

1. Open the URL printed by the installer.
2. Log in with the generated admin password.
3. Add an OSCam instance:
   - WebIF host: usually `127.0.0.1`
   - WebIF port: the OSCam WebIF port
   - WebIF user/password: leave blank only if that WebIF is open
   - OSCam config path: directory containing `oscam.user`, often `/usr/local/etc`
4. Click `Sync now`.
5. Configure global policy or per-user policy.

## User Policies

Each discovered user has its own policy row:

- `Use global`: inherit global max ECM/min, notify, and auto-stop behavior
- `Notify only`: send alert at threshold, never disable this user
- `Stop`: disable this user at threshold, even when global auto-stop is off
- `Ignore`: keep visible, but do not alert or stop

Inputs:

- `Max ECM/min`: blank means inherit global max
- `Stop min`: blank means inherit global stop duration
- `Stop min = 0`: keep disabled until manually enabled

Alerts are sent when a user first reaches the strike threshold. The alert flag is
reset when the user goes below limit, when you click `Reset flag`, or when a
temporary stop expires and the user is enabled again.

## Telegram

In the OSCam edit form, add:

- Telegram bot token
- Telegram admin chat ID
- Telegram enabled
- Notify enabled

Use `Test Telegram` to verify delivery before relying on alerts.

## Services

Check the web panel:

```sh
systemctl status reshare-control-web.service
```

Check the active monitor timer:

```sh
systemctl status reshare-control.timer
systemctl list-timers --all | grep reshare-control
```

Run all OSCam checks immediately:

```sh
reshare-control --config-dir /etc/reshare-control run-all
```

Start the web UI manually:

```sh
reshare-control --config-dir /etc/reshare-control web --host 0.0.0.0 --port 8787
```

## Troubleshooting

If the web page refuses connection:

- confirm the service is running: `systemctl status reshare-control-web.service`
- confirm the port is listening: `ss -ltnp | grep 8787`
- allow TCP `8787` in firewall/security group

If users show `NO_READING`:

- click `Sync now`
- confirm OSCam WebIF is reachable from the same VPS
- confirm the WebIF user has permission to read user statistics
- confirm the configured OSCam path contains the correct `oscam.user`

If stopping does not work:

- confirm the app runs on the same VPS as OSCam
- confirm the configured path points to the active `oscam.user`
- confirm the process has permission to edit that file
- confirm the user policy action is `Stop` or global auto-stop is enabled

## Configuration Files

Main config:

```text
/etc/reshare-control/config.json
```

Per-instance state and audit:

```text
/etc/reshare-control/instances/INSTANCE_ID/
```

When enforcement is enabled, the tool edits only the matching `[account]` block
in `oscam.user`, applies `GET /userconfig.html?action=reinit`, and writes an
audit record.

## Development

Run the dev web panel:

```sh
PYTHONPATH=src python3 -m reshare_control --config-dir /tmp/reshare-control-web-dev web --host 0.0.0.0 --port 8787
```

Run tests:

```sh
PYTHONPATH=src pytest
```

## Spec Kit

Spec Kit artifacts are kept in `.specify/` and feature specs are under `specs/`.
Use a feature branch for each new change and keep spec, plan, tasks, and code
together.
