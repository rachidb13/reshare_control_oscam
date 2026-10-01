# Implementation Plan: Ubuntu 18.04 Installer (No Reshare Link)

**Branch**: `006-ubuntu1804-installer` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-ubuntu1804-installer/spec.md`

## Summary

Add a second POSIX installer, `install-ubuntu18.sh`, beside the untouched `install.sh`.
It accepts only Ubuntu 18.04 and installs `python3.8` (plus `curl` if missing) from the
Ubuntu archive. It then installs the same web panel and poller as the standard installer,
with both pinned to the absolute python3.8 path, and never runs the VPN/reshare-link
enrollment. Code is copied from `install.sh` and trimmed. No application code changes.

## Technical Context

**Language/Version**: POSIX `sh` (dash on 18.04). App runs on Python 3.8 (bionic `python3.8`).

**Primary Dependencies**: apt-get, systemd 237 (or cron), curl; app is stdlib-only

**Storage**: Existing `/etc/reshare-control/config.json` (unchanged format)

**Testing**: pytest integration test that runs the script with stubbed system commands

**Target Platform**: Ubuntu 18.04 LTS only

**Project Type**: CLI installer for an existing single-project Python app

**Performance Goals**: Install completes in under 5 minutes (SC-001)

**Constraints**: `install.sh` byte-identical; no VPN components; no apt source edits

**Scale/Scope**: One new script (~350 lines), one test module, README section

## Constitution Check

The constitution governs polling and enforcement behaviour. This feature changes none of
it, because the same app code runs.

- I Reading Integrity: unaffected (no app change). PASS
- II Sustained Evidence: unaffected. PASS
- III Safe by Default: new config still created by `create_empty_app_config` (auto-stop
  off). The installer refuses before any write on unsupported systems and never enables a
  firewall. PASS
- IV Protocol Fidelity: unaffected; curl is guaranteed present (R8). PASS
- V Least-Intrusive Mutation: the installer changes only its own config dir, units/cron,
  the install dir, and the python3.8/curl packages. PASS
- Security: config dir 700, config.json 600, install dir go-rwx (as in `install.sh`). PASS

Post-design re-check: PASS, no violations to track.

## Project Structure

### Documentation (this feature)

```text
specs/006-ubuntu1804-installer/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/installer-cli.md
└── tasks.md
```

### Source Code (repository root)

```text
install.sh                              # UNCHANGED
install-ubuntu18.sh                     # NEW: 18.04-only, no link enrollment
packaging/*.service, *.timer            # reused as templates (unchanged)
README.md                               # + "Ubuntu 18.04" install section
tests/integration/test_install_ubuntu18.py   # NEW
```

**Structure Decision**: Single-project layout. The new installer sits at the repo root
next to `install.sh`, so the public raw URL pattern matches and it ships in the same
source tarball.

## Script flow (install-ubuntu18.sh)

1. `say` (tty, else stderr), env defaults copied from `install.sh` (no bootstrap key).
2. `check_os` (R5): refuse before anything else.
3. `check_root` (R6).
4. `ensure_runtime` (R1, R2, R8): `apt-get update` + `apt-get install -y python3.8 [curl]`
   only when missing. Verify `python3.8 -c 'import sys; assert sys.version_info >= (3, 8)'`.
   Set `PYTHON` to its absolute path.
5. `fetch_source_if_needed` (copied; source fetched into `/opt/reshare-control/src` unless
   run from a checkout).
6. `ensure_web_config` (copied).
7. Runner commands are always `PYTHONPATH=… /usr/bin/python3.8 -m reshare_control …` (R3).
8. `open_firewall_ports`: web port only (R4).
9. `install_systemd` (copied: timer interval, AccuracySec, web unit with
   `Restart=on-failure`) or `install_cron`.
10. Print URL / admin / password, with the same wording as `install.sh`.

## Complexity Tracking

No constitution violations.

Duplicating the installer instead of parameterising `install.sh` is deliberate: the user
required that `install.sh` stays untouched.
