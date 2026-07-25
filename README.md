# OSCAM Reshare Control

OSCAM Reshare Control monitors OSCAM WebIF user statistics, tracks sustained
ECM/min over-limit behavior, and can optionally disable users that keep exceeding
the configured threshold.

The default posture is detection only. Users are flagged after consecutive
over-limit cycles, but nobody is disabled unless `auto_stop_enabled` is set to
`true`.

## Install

From a cloned checkout on the OSCAM VPS:

```sh
sudo ./install.sh
```

For a piped install after publishing the repo, pass a tarball URL so the script
can persist the Python source used by the scheduled timer:

```sh
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh \
  | sudo RC_SOURCE_URL=https://github.com/<owner>/<repo>/archive/refs/heads/main.tar.gz sh
```

The installer asks for:

- OSCAM WebIF host
- OSCAM WebIF port
- OSCAM WebIF username, blank for open WebIF
- OSCAM WebIF password, hidden while typed

It validates `/oscamapi.json?part=userstats` before saving config, writes
`/etc/reshare-control/config.json` with mode `0600`, and installs a systemd timer
or cron fallback.

## Commands

Run one monitoring cycle:

```sh
reshare-control --config-dir /etc/reshare-control run
```

Show persisted state:

```sh
reshare-control --config-dir /etc/reshare-control status
```

Validate WebIF access:

```sh
reshare-control --config-dir /etc/reshare-control test
```

Manual control:

```sh
reshare-control --config-dir /etc/reshare-control disable-user USER
reshare-control --config-dir /etc/reshare-control enable-user USER
reshare-control --config-dir /etc/reshare-control exempt-user USER
reshare-control --config-dir /etc/reshare-control unexempt-user USER
```

## Configuration

Main settings in `/etc/reshare-control/config.json`:

- `max_ecm_per_min`: global ECM/min threshold, default `20`
- `strike_count`: consecutive over-limit cycles before flagging, default `3`
- `auto_stop_enabled`: enforcement master switch, default `false`
- `base_path`: directory containing `oscam.user`, default `/usr/local/etc`
- `poll_interval_min`: schedule cadence, default `5`
- `exempt_users`: usernames that are evaluated but never auto-stopped

When enforcement is enabled, the tool edits only the matching `[account]` block
in `oscam.user`, applies `GET /userconfig.html?action=reinit`, and appends audit
records to `/etc/reshare-control/audit.log`.

## Spec Kit

The project keeps its Spec Kit artifacts in `.specify/` and the feature spec in
`specs/001-oscam-reshare-control/`. Use feature branches for new work and keep
the spec, plan, tasks, and implementation changes together.
