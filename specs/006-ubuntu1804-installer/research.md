# Research: Ubuntu 18.04 Installer (No Reshare Link)

## R1. Getting a Python the panel can run on 18.04

- **Decision**: Install the `python3.8` package from Ubuntu 18.04's own archive
  (bionic-updates, `universe` component; 3.8.0 build). Run the panel and poller with its
  absolute path (`/usr/bin/python3.8`), never with `python3`.
- **Rationale**: The app needs 3.7+ (`dataclasses`, `http.server.ThreadingHTTPServer`)
  and declares `requires-python >= 3.8`. Everything else it imports is stdlib, so no pip
  and no venv are needed. Staying on the distro archive keeps updates coming through apt.
  The system `python3` (3.6) is left alone: Ubuntu tools depend on it.
- **Alternatives considered**: Port the code to 3.6 (rejected by the user, and it touches
  shared code). Use the deadsnakes PPA (third-party, not needed since bionic carries 3.8).
  Build from source (slow and fragile on small VPSes).

## R2. Where the `universe` component is disabled

- **Decision**: If `apt-get install python3.8` fails, stop with a message saying that
  python3.8 comes from the Ubuntu `universe` component and that
  `add-apt-repository universe && apt-get update` enables it. Do not edit apt sources
  ourselves.
- **Rationale**: Changing package sources is a system-wide change the operator should
  choose. Stock 18.04 cloud images have universe enabled, so this is a rare path.

## R3. Making sure services never pick up Python 3.6

- **Decision**: Every command the installer writes (systemd `ExecStart` for both units,
  the cron line) uses `<abs python3.8> -m reshare_control` with `PYTHONPATH` pointing at
  the installed source. Never use a `reshare-control` command found on `PATH`. The standard
  installer prefers one if present, but on 18.04 it could be a 3.6 entry point.
- **Rationale**: Satisfies FR-006 deterministically.

## R4. No reshare link, under any input

- **Decision**: The script contains no enrollment call and no bootstrap key, and it does
  not read `RC_BOOTSTRAP_KEY` / `RC_SKIP_VPN`. The firewall step opens only `web.port/tcp`,
  even when an existing `config.json` has `vpn.enabled: true`.
- **Rationale**: FR-007 and FR-010. Leaving the call out entirely is simpler and safer than
  guarding it.

## R5. Strict OS gate

- **Decision**: Parse `/etc/os-release` (path overridable via `RC_OS_RELEASE` for tests
  only). Proceed only when `ID=ubuntu` and `VERSION_ID=18.04`. On Ubuntu with a version
  ranked above 18.04, print the standard install command. Run before the root check and
  before any write.
- **Rationale**: FR-002/003, SC-002. The standard installer's `RC_SKIP_OS_CHECK` escape
  is not carried over: the user asked for 18.04 only.

## R6. Root check

- **Decision**: `[ "$(id -u)" -eq 0 ]`, else refuse. Done after the OS gate and before
  any write.

## R7. Output without a TTY

- **Decision**: `say` writes to `/dev/tty` when it can be opened, else to stderr.
- **Rationale**: The standard installer writes only to `/dev/tty`, which aborts under
  `set -e` in CI or tests without a terminal. For `curl | sudo sh` behaviour is unchanged.

## R8. curl

- **Decision**: Install `curl` in the same apt step if it is missing. The poller uses curl
  for WebIF calls, and wget-only boxes would otherwise install a panel that cannot poll.

## R9. Testing without an 18.04 box

- **Decision**: Pytest drives the real script with stub `apt-get`, `systemctl`, `id`,
  `crontab`, `ufw`, `hostname` on `PATH`, a fake os-release file, and temporary
  config/systemd/install dirs. The `python3.8` stub execs the test interpreter. A final
  manual check runs on the 18.04 test VPS (quickstart.md).
