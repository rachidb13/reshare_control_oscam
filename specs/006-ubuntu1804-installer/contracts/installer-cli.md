# Contract: install-ubuntu18.sh

## Invocation

```sh
curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/master/install-ubuntu18.sh | sudo sh
# or, from a checkout:
sudo sh install-ubuntu18.sh
```

No arguments.

## Environment overrides

These match `install.sh`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `RC_CONFIG_DIR` | `/etc/reshare-control` | config directory |
| `RC_INSTALL_DIR` | `/opt/reshare-control` | where fetched source is put |
| `RC_SYSTEMD_DIR` | `/etc/systemd/system` | unit directory |
| `RC_SOURCE_URL` | master tarball | source archive |
| `RC_SOURCE_DIR` | – | use this `src` dir instead of fetching |

Specific to this installer (for tests):

| Variable | Default | Meaning |
|----------|---------|---------|
| `RC_OS_RELEASE` | `/etc/os-release` | OS identification file |

Deliberately **not** honoured: `RC_BOOTSTRAP_KEY`, `RC_SKIP_VPN`, `RC_SKIP_OS_CHECK`,
`PYTHON` (the runtime is always the absolute path of `python3.8`).

## Exit status

- `0`: installed; services started (or cron written).
- `1`: refused (OS, not root) or failed (package install, source fetch). On refusal,
  nothing has been written.

## Output (stdout/tty)

Success ends with:

```
Open: http://<first host IP>:<web port>/
User: admin
Password: <generated> | existing password in <config dir>/config.json

---- finish installation ------
```

When the OS is Ubuntu newer than 18.04, the refusal includes:

```
curl -fsSL https://raw.githubusercontent.com/rachidb13/reshare_control_oscam/master/install.sh | sudo sh
```

## Side effects (success)

- Packages: `python3.8` and `curl` if missing. Nothing else, and no VPN packages.
- Files: see data-model.md.
- systemd: `reshare-control.timer` and `reshare-control-web.service` enabled and started.
- Firewall: only if ufw/firewalld is already active, open `<web port>/tcp`.
