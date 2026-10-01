# Data Model: Ubuntu 18.04 Installer

No new persisted data. The installer reads and writes only existing artifacts.

| Artifact | Path (default) | Owner/mode | Created when | Re-run behaviour |
|----------|----------------|------------|--------------|------------------|
| App config | `$RC_CONFIG_DIR/config.json` (`/etc/reshare-control`) | root, dir 700, file 600 | absent | kept; only fills a missing admin hash |
| App source | `$RC_INSTALL_DIR/src/reshare_control` (`/opt/reshare-control`) | root, go-rwx | not run from a checkout | replaced with fetched source |
| Poll unit | `$RC_SYSTEMD_DIR/reshare-control.service` | root | systemd present | rewritten |
| Poll timer | `$RC_SYSTEMD_DIR/reshare-control.timer` | root | systemd present | rewritten, interval = min `poll_interval_min` |
| Web unit | `$RC_SYSTEMD_DIR/reshare-control-web.service` | root | systemd present | rewritten, restarted |
| Cron line | root crontab, tagged `# reshare-control` | root | no systemd | replaced |

## Input: OS identification

`/etc/os-release` fields `ID`, `VERSION_ID`, `PRETTY_NAME`.

| ID | VERSION_ID | Result |
|----|-----------|--------|
| ubuntu | 18.04 | proceed |
| ubuntu | > 18.04 | refuse, print the standard install command, exit 1 |
| ubuntu | < 18.04 / empty | refuse, "only Ubuntu 18.04", exit 1 |
| anything else / no file | – | refuse, "unsupported system", exit 1 |

## Ignored config fields

`vpn.*` in an existing config is preserved untouched but never acted on (no enrollment,
no VPN firewall ports).
