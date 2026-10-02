# Tasks: Ubuntu 18.04 Installer (No Reshare Link)

**Input**: Design documents from `specs/006-ubuntu1804-installer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/installer-cli.md

**Tests**: Included. Installer behaviour is verified by an integration test that runs the
real script against stubbed system commands (research R9).

## Phase 1: Setup

- [X] T001 Create the test harness `tests/integration/test_install_ubuntu18.py`. It needs a
  fixture that builds a stub bin dir (`apt-get`, `systemctl`, `id`, `crontab`, `ufw`,
  `hostname`, `python3.8` → exec of `sys.executable`), each stub logging its argv to a
  calls file. It also writes a fake os-release, uses temp `RC_CONFIG_DIR`/`RC_SYSTEMD_DIR`/
  `RC_INSTALL_DIR`, sets `RC_SOURCE_DIR=<repo>/src`, and gives a `run_installer(env)`
  helper that runs `sh install-ubuntu18.sh` and returns (code, output, calls).

## Phase 2: Foundational

- [X] T002 Create `install-ubuntu18.sh` skeleton by copying from `install.sh`: `set -eu`, env
  defaults (no bootstrap key/checker URL), tmpdir/trap, `say` writing to /dev/tty else
  stderr (R7), `run_python`, `poll_interval_min`, `fetch_source_if_needed`,
  `ensure_web_config`. Do not edit `install.sh`.

## Phase 3: User Story 2 - Refuse non-18.04 systems (P1)

**Goal**: Exit 1 before any write on anything but Ubuntu 18.04.

**Independent Test**: Run with fake os-release for ubuntu 20.04/22.04, ubuntu 16.04,
debian 11, missing file. Expect exit 1, no config dir, no apt calls.

- [X] T003 [US2] Tests: refusal matrix + 20.04 output contains the standard `install.sh`
  command + no files written + no `apt-get` call, in `tests/integration/test_install_ubuntu18.py`
- [X] T004 [US2] Test: non-root (`id -u` stub prints 1000) refuses before any write, in
  `tests/integration/test_install_ubuntu18.py`
- [X] T005 [US2] Implement `check_os` (reads `${RC_OS_RELEASE:-/etc/os-release}`, uses
  copied `version_rank`) and `check_root`, called first in `install-ubuntu18.sh`

## Phase 4: User Story 1 - Install the panel on 18.04 (P1) 🎯 MVP

**Goal**: Same web panel + poller as `install.sh`, on python3.8, no VPN.

**Independent Test**: Run with ubuntu 18.04 os-release and systemd stub. Expect exit 0,
config.json created (600), three units written with python3.8 in `ExecStart`,
`systemctl enable --now` for the timer and web unit, and URL/admin/password printed.

- [X] T006 [US1] Tests: 18.04 happy path; when `python3.8` is absent from the stub PATH,
  `apt-get install -y python3.8` is called; when apt fails, exit 1 and no unit files exist;
  in `tests/integration/test_install_ubuntu18.py`
- [X] T007 [US1] Tests: units contain the absolute python3.8 path and never
  `reshare-control` from PATH; web unit has `Restart=on-failure`; timer has
  `AccuracySec=1s`; output has `Open: http://`, `User: admin`, `Password:`; in
  `tests/integration/test_install_ubuntu18.py`
- [X] T008 [US1] Tests: no VPN. No `enroll` invocation and no wireguard in any apt call,
  even with `RC_BOOTSTRAP_KEY` set. Firewall (active ufw stub) gets only the web port, even
  when an existing config has `vpn.enabled: true`. In `tests/integration/test_install_ubuntu18.py`
- [X] T009 [US1] Test: no systemd (systemctl stub fails), so a cron line with python3.8 is
  written via the `crontab` stub, in `tests/integration/test_install_ubuntu18.py`
- [X] T010 [US1] Implement `ensure_runtime` (R1/R2/R8) in `install-ubuntu18.sh`
- [X] T011 [US1] Implement runner commands pinned to python3.8 (R3), `install_systemd`,
  `install_cron`, `open_firewall_ports` (web port only), and the final summary, in
  `install-ubuntu18.sh`

## Phase 5: User Story 3 - Safe re-run (P2)

**Independent Test**: Run twice. Second run keeps config.json bytes and prints
"existing password".

- [X] T012 [US3] Test: re-run preserves config.json content and prints the existing-password
  line, in `tests/integration/test_install_ubuntu18.py`
- [X] T013 [US3] Fix anything T012 exposes in `install-ubuntu18.sh` (expected: none, as
  `ensure_web_config` is copied)

## Phase 6: Polish

- [X] T014 [P] Add an "Ubuntu 18.04" install section to `README.md` (command, what differs:
  no reshare link, python3.8)
- [X] T015 Run full suite `PYTHONPATH=src .venv/bin/python -m pytest tests/ -q`,
  `sh -n install-ubuntu18.sh`, and confirm `git diff --exit-code master -- install.sh`
- [ ] T016 Manual check on the 18.04 VPS per `quickstart.md` (needs SSH access restored)

## Phase 7: User Story 4 - NCam support (P1)

**Independent Test**: unit + integration tests below with an `ncam.user` folder and an
NCam-shaped stats body served only at `/ncamapi.json`.

- [X] T017 [US4] Tests: `list_account_users`/`set_account_disabled`/`stop_account` work on
  a folder with only `ncam.user`; `oscam.user` wins when both exist; the error names both
  files when neither exists; in `tests/unit/test_enforce.py`
- [X] T018 [US4] Tests: `normalize_userstats_body`/`validate_userstats_body` read a body
  rooted at `"ncam"` (NCam `n_requ_m` stats shape), in `tests/unit/test_parse.py`
- [X] T019 [US4] Tests: `run_cycle` on an NCam folder requests `/ncamapi.json` first; on an
  OSCam folder a 404 from `/oscamapi.json` falls back to `/ncamapi.json`; in
  `tests/integration/test_poller.py`
- [X] T020 [US4] Implement `user_file_path`/`is_ncam` in `src/reshare_control/enforce.py`
  and use them for read, write and temp-file naming
- [X] T021 [US4] Implement `api_root` in `src/reshare_control/parse.py` and use it in
  `parse.py` and `poller.py`
- [X] T022 [US4] Implement `fetch_userstats(fetcher, prefer_ncam)` with 404 fallback in
  `src/reshare_control/webif.py`; use it in `poller.run_cycle` and `cli.command_test`
- [X] T023 [US4] Update the instance form hint/label in `src/reshare_control/webapp.py`
- [X] T024 [US4] README: NCam support, and "re-run the same command to update"

## Dependencies

- T001 → T003–T013. T002 → T005, T010, T011.
- US2 (T003–T005) runs before US1 because the gate is the first thing the script does.
- US3 depends on US1.
- US4 (T017–T024) only touches app code and is independent of the installer tasks.
- T014 is independent. T015 runs after everything. T016 needs the user.

## Parallel Opportunities

There is one script and one test file, so most tasks touch the same files. Only T014
(README) can run in parallel.

## Implementation Strategy

MVP is US2 + US1, which gives a working, safely gated 18.04 install. US3 is a check of the
copied behaviour. Implementation is done inline by the main session, since it is one
~350-line script.
