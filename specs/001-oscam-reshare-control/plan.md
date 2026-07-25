# Implementation Plan: OSCAM Reshare Control

**Branch**: `001-oscam-reshare-control` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-oscam-reshare-control/spec.md`

## Summary

A self-contained VPS tool, installed by a single SSH one-liner, that logs in to one OSCAM WebIF
using operator-provided credentials, reads each active user's ECM/min every ~5 minutes, and flags
(and optionally stops) sustained resharers via a consecutive-strike engine. Technical approach: a
**Python 3 (stdlib-only) script that shells out to `curl`** for all WebIF HTTP (probe → Digest →
Basic via `curl --anyauth`), with a POSIX `install.sh` that collects/validates credentials on
`/dev/tty`, writes an owner-only JSON config, and installs a systemd timer (cron fallback).

## Technical Context

**Language/Version**: Python 3.6+ (stdlib only: `json`, `hashlib`, `html.parser`, `subprocess`,
`argparse`, `configparser`, `fcntl`, `logging`); POSIX `sh` for `install.sh`

**Primary Dependencies**: `curl` (HTTP incl. `--anyauth`/`--digest`); coreutils. No `pip` packages.

**Storage**: Two owner-only files under a config dir (default `/etc/reshare-control/`):
`config.json` (connection + tuning) and `state.json` (per-user strike state). OSCAM's own
`oscam.user` file is read/edited in place for enforcement.

**Testing**: `pytest` for pure-Python units (strike engine, JSON/HTML shape parsing, digest/join
helpers) run against captured WebIF fixtures; `shellcheck` for `install.sh`. Network calls are
stubbed by injecting a fake fetcher, so tests need no live WebIF.

**Target Platform**: Linux VPS hosting an OSCAM instance (systemd or cron available); plain HTTP LAN
WebIF. Runs on (or with file access to) the box so it can edit `oscam.user`.

**Project Type**: Single-project CLI/daemon (installer + poller). No web/mobile frontend.

**Performance Goals**: A poll cycle for a typical instance (≤ a few hundred users) completes well
within the ~5-minute cadence; per-request timeout ~5s so a dead WebIF fails fast as "no reading".

**Constraints**: No third-party runtime deps beyond `curl`; config/state files owner-only (0600);
passwords never echoed or logged; usernames masked in logs; enforcement OFF by default; only the
target user's block in `oscam.user` is ever modified; changes applied via `?action=reinit` (no
full restart).

**Scale/Scope**: Exactly one OSCAM instance per install (re-run per box); a single operator.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the design upholds it | Status |
|---|---|---|
| **I. Reading Integrity — No Reading, No Action** | Fetch layer returns a tri-state per user: `numeric value` / `NO_READING` / (skip if disabled). Strike engine only acts on numeric; transport/auth failure, non-2xx, absent user, and non-numeric ECM/min all map to `NO_READING` (unchanged streak). | ✅ PASS |
| **II. Sustained Evidence Before Enforcement** | Streak increments only on numeric over-limit; resets only on numeric at/under-limit; unchanged on NO_READING. Flag/stop require `strikes >= strike_count` (default 3). | ✅ PASS |
| **III. Safe by Default** | `auto_stop_enabled` defaults **false**; `exempt` users never auto-stopped; already-disabled/stopped users skipped. Defaults `max_ecm_per_min=20`, `strike_count=3`. | ✅ PASS |
| **IV. Protocol Fidelity & Build Tolerance** | Auth flow probe → Digest → Basic via `curl --anyauth`; per-endpoint URI. Join via `md5(username)==usermd5`; plaintext `name` used when present. Parser tolerates the documented ~6 shapes + HTML/XML fallback; skips `disabled==1`. | ✅ PASS |
| **V. Least-Intrusive Mutation & Auditability** | Stop edits ONLY the target `[account]` block's `disabled` line in `oscam.user`; applies via `GET /userconfig.html?action=reinit`; never touches `oscam.conf`/`oscam.server`; every stop/reinstate audit-logged (user, time, ECM/min, threshold, strikes). | ✅ PASS |

**Security & Operational Constraints**: HTTP-not-HTTPS assumed; ~5s timeouts; credentials stored
0600 (encryption at rest explicitly deferred to a later version per spec Assumptions); usernames
masked in logs; state persisted per user across runs. All satisfied. **No violations — Complexity
Tracking not required.**

## Project Structure

### Documentation (this feature)

```text
specs/001-oscam-reshare-control/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── config.schema.md       # config.json shape + defaults
│   ├── state.schema.md        # state.json shape
│   ├── cli.md                 # command surface (install/run/status/enable/disable)
│   └── webif-endpoints.md     # WebIF requests the tool depends on
└── checklists/
    └── requirements.md  # spec quality checklist (done)
```

### Source Code (repository root)

```text
src/
└── reshare_control/
    ├── __init__.py
    ├── cli.py            # arg parsing: run / status / disable-user / enable-user / test
    ├── config.py         # load/save config.json (0600), defaults, validation
    ├── state.py          # load/save state.json (0600), per-user strike records, file lock
    ├── webif.py          # curl-based fetcher: probe→Digest→Basic; GET endpoints; reinit
    ├── parse.py          # tolerant JSON/HTML/XML → normalized user list; md5 join
    ├── strike.py         # pure strike engine (numeric/over/under/NO_READING transitions)
    ├── enforce.py        # edit oscam.user target block; call reinit; audit log
    └── poller.py         # one poll cycle: fetch → parse → evaluate → (enforce) → persist

install.sh               # one-liner entry: prompt on /dev/tty, validate, write config, schedule
packaging/
├── reshare-control.service   # systemd unit (oneshot)
└── reshare-control.timer     # systemd timer (~5 min); cron line used as fallback

tests/
├── fixtures/             # captured WebIF JSON/HTML/XML per build shape
├── unit/
│   ├── test_strike.py    # engine transitions incl. NO_READING-is-inert
│   ├── test_parse.py     # all documented shapes + md5 join + disabled skip
│   ├── test_config.py    # defaults, 0600, validation
│   └── test_enforce.py   # only-target-block edit, idempotent stop
└── integration/
    └── test_poller.py    # full cycle with a fake fetcher (no live WebIF)
```

**Structure Decision**: Single Python package `src/reshare_control/` with a thin POSIX `install.sh`
front door and a `packaging/` folder for the systemd/cron scheduling assets. The network boundary
(`webif.py`) is isolated behind a small fetcher interface so the strike engine and parsers are
unit-testable against fixtures with no live WebIF — directly serving the constitution's testability
and "no reading is inert" requirements.

## Complexity Tracking

> No Constitution Check violations. No entries required.
