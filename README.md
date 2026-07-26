# OSCAM Reshare Control

OSCAM Reshare Control installs a small web interface on a VPS. From the browser
you can add one or more local OSCam instances, monitor WebIF ECM/min statistics,
track sustained over-limit behavior, and optionally disable users that keep
exceeding the configured threshold.

The default posture is detection only. Users are flagged after consecutive
over-limit cycles, but nobody is disabled unless `auto_stop_enabled` is set to
`true`.

## Install

From a cloned checkout on the OSCAM VPS:

```sh
sudo ./install.sh
```

One copy-paste install from GitHub:

```sh
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh \
  | sudo RC_SOURCE_URL=https://github.com/<owner>/<repo>/archive/refs/heads/main.tar.gz sh
```

For this repository after merge to `main`:

```sh
curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/main/install.sh \
  | sudo RC_SOURCE_URL=https://github.com/rachidb13/reshare_control_oscam/archive/refs/heads/main.tar.gz sh
```

The installer writes `/etc/reshare-control/config.json` with mode `0600`, starts
the web interface, installs a scheduled monitor, and prints:

- browser URL, usually `http://SERVER_IP:8787/`
- admin username
- generated admin password

Log in from a browser, then add each OSCam running on that VPS with:

- display name
- WebIF host and port, usually `127.0.0.1` plus that OSCam WebIF port
- WebIF username/password, blank for open WebIF
- OSCam config directory containing `oscam.user`
- ECM/min limit, strike count, poll interval, global notify, global auto-stop, and Telegram settings

After saving an OSCam, press **Sync now**. That button performs one live WebIF poll for that OSCam,
reads local `oscam.user` accounts from the configured path, updates the state table, evaluates strike
rules, sends notifications when configured, and stops users only when the matching global or per-user
policy allows stopping.

Each discovered user appears automatically with policy controls:

- `Use global`: inherit the OSCam global max ECM, notify, and auto-stop settings
- `Notify only`: alert when the user reaches the strike threshold, never auto-stop
- `Stop`: auto-stop this user at threshold even if global auto-stop is off
- `Ignore`: keep the user visible but never auto-stop
- user max ECM/min override: blank inherits the OSCam global max

Telegram notifications require:

- Telegram bot token
- admin chat ID
- Telegram enabled
- Notify enabled globally, or a user policy set to `Notify only` / `Stop`

## Commands

Run one monitoring cycle for every configured OSCam:

```sh
reshare-control --config-dir /etc/reshare-control run-all
```

Run or show one instance:

```sh
reshare-control --config-dir /etc/reshare-control run --instance INSTANCE_ID
reshare-control --config-dir /etc/reshare-control status --instance INSTANCE_ID
```

Start the web UI manually:

```sh
reshare-control --config-dir /etc/reshare-control web
```

Manual control:

```sh
reshare-control --config-dir /etc/reshare-control disable-user --instance INSTANCE_ID USER
reshare-control --config-dir /etc/reshare-control enable-user --instance INSTANCE_ID USER
reshare-control --config-dir /etc/reshare-control exempt-user --instance INSTANCE_ID USER
reshare-control --config-dir /etc/reshare-control unexempt-user --instance INSTANCE_ID USER
```

## Configuration

Main settings per instance in `/etc/reshare-control/config.json`:

- `max_ecm_per_min`: global ECM/min threshold, default `20`
- `strike_count`: consecutive over-limit cycles before flagging, default `3`
- `auto_stop_enabled`: enforcement master switch, default `false`
- `notify_enabled`: global notification switch, default `true`
- `telegram_enabled`, `telegram_bot_token`, `telegram_chat_id`: Telegram delivery settings
- `base_path`: directory containing `oscam.user`, default `/usr/local/etc`
- `poll_interval_min`: schedule cadence, default `5`
- `user_policies`: per-user action and optional max ECM/min override

Per-instance state and audit files are stored under:

```text
/etc/reshare-control/instances/INSTANCE_ID/
```

When enforcement is enabled, the tool edits only the matching `[account]` block
in `oscam.user`, applies `GET /userconfig.html?action=reinit`, and appends audit
records to `/etc/reshare-control/audit.log`.

## Spec Kit

The project keeps its Spec Kit artifacts in `.specify/` and the feature spec in
`specs/001-oscam-reshare-control/`. Use feature branches for new work and keep
the spec, plan, tasks, and implementation changes together.
