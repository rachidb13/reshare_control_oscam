# Tasks: Ubuntu 18.04 Installer (No Reshare Link)

**Input**: Design documents from `specs/006-ubuntu1804-installer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/installer-cli.md

**Tests**: Included. Installer behaviour is verified by an integration test that runs the
real script against stubbed system commands (research R9).

## Phase 1: Setup

- [ ] T001 Create the test harness `tests/integration/test_install_ubuntu18.py`. It needs a
  fixture that builds a stub bin dir (`apt-get`, `systemctl`, `id`, `crontab`, `ufw`,
  `hostname`, `python3.8` → exec of `sys.executable`), each stub logging its argv to a
  calls file. It also writes a fake os-release, uses temp `RC_CONFIG_DIR`/`RC_SYSTEMD_DIR`/
  `RC_INSTALL_DIR`, sets `RC_SOURCE_DIR=<repo>/src`, and gives a `run_installer(env)`
  helper that runs `sh install-ubuntu18.sh` and returns (code, output, calls).

## Phase 2: Foundational

- [ ] T002 Create `install-ubuntu18.sh` skeleton by copying from `install.sh`: `set -eu`, env
  defaults (no bootstrap key/checker URL), tmpdir/trap, `say` writing to /dev/tty else
  stderr (R7), `run_python`, `poll_interval_min`, `fetch_source_if_needed`,
  `ensure_web_config`. Do not edit `install.sh`.

## Phase 3: User Story 2 - Refuse non-18.04 systems (P1)

**Goal**: Exit 1 before any write on anything but Ubuntu 18.04.

**Independent Test**: Run with fake os-release for ubuntu 20.04/22.04, ubuntu 16.04,
debian 11, missing file. Expect exit 1, no config dir, no apt calls.

- [ ] T003 [US2] Tests: refusal matrix + 20.04 output contains the standard `install.sh`
  command + no files written + no `apt-get` call, in `tests/integration/test_install_ubuntu18.py`
- [ ] T004 [US2] Test: non-root (`id -u` stub prints 1000) refuses before any write, in
  `tests/integration/test_install_ubuntu18.py`
- [ ] T005 [US2] Implement `check_os` (reads `${RC_OS_RELEASE:-/etc/os-release}`, uses
  copied `version_rank`) and `check_root`, called first in `install-ubuntu18.sh`

## Phase 4: User Story 1 - Install the panel on 18.04 (P1) 🎯 MVP

**Goal**: Same web panel + poller as `install.sh`, on python3.8, no VPN.

**Independent Test**: Run with ubuntu 18.04 os-release and systemd stub. Expect exit 0,
config.json created (600), three units written with python3.8 in `ExecStart`,
`systemctl enable --now` for the timer and web unit, and URL/admin/password printed.

- [ ] T006 [US1] Tests: 18.04 happy path; when `python3.8` is absent from the stub PATH,
  `apt-get install -y python3.8` is called; when apt fails, exit 1 and no unit files exist;
  in `tests/integration/test_install_ubuntu18.py`
- [ ] T007 [US1] Tests: units contain the absolute python3.8 path and never
  `reshare-control` from PATH; web unit has `Restart=on-failure`; timer has
  `AccuracySec=1s`; output has `Open: http://`, `User: admin`, `Password:`; in
  `tests/integration/test_install_ubuntu18.py`
- [ ] T008 [US1] Tests: no VPN. No `enroll` invocation and no wireguard in any apt call,
  even with `RC_BOOTSTRAP_KEY` set. Firewall (active ufw stub) gets only the web port, even
  when an existing config has `vpn.enabled: true`. In `tests/integration/test_install_ubuntu18.py`
- [ ] T009 [US1] Test: no systemd (systemctl stub fails), so a cron line with python3.8 is
  written via the `crontab` stub, in `tests/integration/test_install_ubuntu18.py`
- [ ] T010 [US1] Implement `ensure_runtime` (R1/R2/R8) in `install-ubuntu18.sh`
- [ ] T011 [US1] Implement runner commands pinned to python3.8 (R3), `install_systemd`,
  `install_cron`, `open_firewall_ports` (web port only), and the final summary, in
  `install-ubuntu18.sh`

## Phase 5: User Story 3 - Safe re-run (P2)

**Independent Test**: Run twice. Second run keeps config.json bytes and prints
"existing password".

- [ ] T012 [US3] Test: re-run preserves config.json content and prints the existing-password
  line, in `tests/integration/test_install_ubuntu18.py`
- [ ] T013 [US3] Fix anything T012 exposes in `install-ubuntu18.sh` (expected: none, as
  `ensure_web_config` is copied)

## Phase 6: Polish

- [ ] T014 [P] Add an "Ubuntu 18.04" install section to `README.md` (command, what differs:
  no reshare link, python3.8)
- [ ] T015 Run full suite `PYTHONPATH=src .venv/bin/python -m pytest tests/ -q`,
  `sh -n install-ubuntu18.sh`, and confirm `git diff --exit-code master -- install.sh`
- [ ] T016 Manual check on the 18.04 VPS per `quickstart.md` (needs SSH access restored)

## Dependencies

- T001 → T003–T013. T002 → T005, T010, T011.
- US2 (T003–T005) runs before US1 because the gate is the first thing the script does.
- US3 depends on US1.
- T014 is independent. T015 runs after everything. T016 needs the user.

## Parallel Opportunities

There is one script and one test file, so most tasks touch the same files. Only T014
(README) can run in parallel.

## Implementation Strategy

MVP is US2 + US1, which gives a working, safely gated 18.04 install. US3 is a check of the
copied behaviour. Implementation is done inline by the main session, since it is one
~350-line script.
