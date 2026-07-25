# Phase 0 Research: OSCAM Reshare Control

All Technical Context unknowns are resolved below. Source of truth for protocol behavior is
`oscam-reshare-webif-method.md` (referenced as "method doc").

## R1. Runtime & HTTP transport

- **Decision**: Python 3 (stdlib only) that shells out to `curl` for every WebIF request.
- **Rationale**: `python3` is effectively ubiquitous on Linux VPSes; stdlib-only means the install
  one-liner needs no `pip`. `curl --anyauth -u user:pass` implements the method doc's probe →
  Digest → Basic negotiation (method doc §8.2/§8.4) — the fiddliest part (Digest `qop`/`nonce`/
  `nc`/`cnonce`, per-endpoint URI) is delegated to battle-tested `curl` instead of reimplemented.
  `hashlib.md5` does the `md5(username)==usermd5` join; `html.parser`/`json` handle the ~6 build
  shapes cleanly where shell+jq would be brittle.
- **Alternatives considered**:
  - *Pure POSIX shell + curl + jq* — fragile multi-shape JSON/HTML/XML parsing; `jq` not always
    present; rejected as the weakest link for build tolerance (Principle IV).
  - *Go static binary* — best robustness/zero-dep, but adds a build/release/arch-hosting pipeline
    that cuts against "one paste, no infra". Deferred; can be revisited if minimal boxes appear.
  - *Python with `requests`* — needs `pip`; rejected to keep the one-liner dependency-free.

## R2. Digest/Basic auth negotiation

- **Decision**: Use `curl --anyauth -u "<user>:<pass>" --max-time 5` per request; on empty
  credentials (open WebIF) omit `-u` and probe unauthenticated.
- **Rationale**: `--anyauth` reads the `WWW-Authenticate` challenge and picks Digest (preferred) or
  Basic automatically, mirroring method doc §3. curl recomputes the Digest `uri`/HA2 per endpoint,
  satisfying the "per-endpoint digest" gotcha (method doc §7) for `/userconfig.html` vs
  `/oscamapi.json?part=userstats` vs `?action=reinit`.
- **Failure mapping**: curl exit codes → tri-state. Connection/timeout (exit 7/28/6) = `NO_READING`
  (transport). HTTP 401/403 after auth = `AUTH_FAILED` (logged distinctly, but `NO_READING` for the
  engine, per Principle I/FR-014). HTTP 200 = parse body.
- **Alternatives**: hand-rolled digest in `urllib` — rejected (reimplements the error-prone part).

## R3. Username ↔ stats correlation

- **Decision**: Primary path — read `/oscamapi.json?part=userstats`; if a user object exposes
  plaintext `name`/`username`, use it directly. Otherwise fetch `/userconfig.html`, extract
  plaintext usernames, and join to JSON stats via `md5(username) == usermd5`.
- **Rationale**: Method doc §2/§4: some builds hash the username to `usermd5`; the HTML page always
  carries plaintext names. Direct `name` avoids the extra fetch when available.
- **Alternatives**: HTML-only or JSON-only — rejected; neither is universally sufficient across
  builds.

## R4. Build-shape tolerance

- **Decision**: A normalization function accepts any of: `oscam.userstats.user[]`, `oscam.users[]`,
  `oscam.status.client[]`, flat `oscam.user`/`oscam.client`; a single object instead of a
  1-element array (wrap it); entries wrapped as `{ "user": {…} }` (unwrap); `name` vs `username`
  key. XML `api.html?part=status` is a presence/idle fallback only (ECM/min not reliable there).
  Users with `disabled == "1"` are skipped.
- **Rationale**: Directly enumerated in method doc §4.1 as shapes the reference client tolerates.
- **Alternatives**: assume one shape — rejected (silent user loss corrupts the strike engine).

## R5. The ECM/min reshare signal & "no reading"

- **Decision**: `ecm_per_min = number(raw.total_ecm_min)`. Treat as `NO_READING` when: fetch failed
  / non-2xx / user absent / `total_ecm_min` missing or non-numeric.
- **Rationale**: Method doc §4.2 and Principle I. A future Δcwok/Δminutes fallback is noted for
  builds lacking `total_ecm_min` but is **out of scope for v1** (surfaced as a warning instead).
- **Alternatives**: default missing → 0 (under-limit) — explicitly forbidden (would silently reset
  streaks).

## R6. Strike engine semantics

- **Decision**: Per active user per cycle: `NO_READING` → leave streak, update `last_evaluated_at`;
  `reading > max_ecm_per_min` → `strikes += 1`; `reading <= max` → `strikes = 0`. Status is then
  derived from the streak: `status = flagged` **iff** `strikes >= strike_count`, else `status = ok`.
  Then if `auto_stop_enabled and strikes >= strike_count and not exempt and not already disabled` →
  `STOP`, status `stopped`.
- **Rationale**: Aligns with method doc §5's strike counting and Principles I–III, while honoring
  spec **FR-015/SC-003**: a user is only *flagged* once sustained to the threshold, so a single spike
  is never flagged. The building streak is still visible via `consecutive_strikes`. In detection-only
  mode, "flagged" therefore means "would have been stopped" — the exact watch-list the operator wants.
  Defaults: `max_ecm_per_min=20`, `strike_count=3`, `auto_stop_enabled=false`.
- **Alternatives**: none — this is the contract.

## R7. Stopping / re-enabling

- **Decision**: Read `{base_path}/oscam.user`; in the target `[account]` block only, set
  `disabled = 1` (add if absent); write back atomically (temp file + rename, 0600 preserved); then
  `GET {base}/userconfig.html?action=reinit` with the same auth. Re-enable reverses to `disabled=0`,
  reinit, and resets that user's `strikes=0`, `status=ok`.
- **Rationale**: Method doc §6 — the portable, reference-matching mechanism; never touches
  `oscam.conf`/`oscam.server` (Principle V). Block-scoped edit prevents collateral changes.
- **Alternatives**: full OSCAM restart — rejected (heavier, disrupts all users); a WebIF write API —
  build-specific, not portable.

## R8. Config & state storage

- **Decision**: `config.json` and `state.json` under `/etc/reshare-control/` (override via
  `--config-dir`/env), both created `0600`, owner-only. State keyed by username (single instance).
  `state.json` written atomically under an `fcntl` lock to survive overlapping runs.
- **Rationale**: Spec FR-006/FR-016; single-instance decision (FR-007) keeps keys flat. Encryption
  at rest deferred per spec Assumptions.
- **Alternatives**: SQLite — unnecessary for one instance / few hundred users; flat JSON is simpler
  and inspectable.

## R9. Interactive install under a piped one-liner

- **Decision**: `install.sh` reads every prompt from `/dev/tty` (`read -r var < /dev/tty`; password
  with `stty -echo`/`read -s < /dev/tty`), never from stdin.
- **Rationale**: `curl … | bash` binds the script's stdin to the pipe, so plain `read` gets the
  script stream, not the operator (spec FR-003, edge case). `/dev/tty` targets the terminal directly.
- **Alternatives**: `bash <(curl …)` process substitution — works but is bash-only and less portable
  than the explicit `/dev/tty` read; rejected as the primary mechanism.

## R10. Scheduling

- **Decision**: Prefer a systemd oneshot service + timer at ~5 min (`OnUnitActiveSec=5min`); if
  systemd is absent, install a cron line (`*/5 * * * *`). Installer detects and picks.
- **Rationale**: Method doc §7 cadence; single-instance oneshot avoids a long-lived daemon and lets
  each run be independently observable. Re-run install updates the existing unit/cron (FR-009).
- **Alternatives**: long-running Python daemon with internal sleep — more moving parts, worse crash
  recovery; rejected.

## R11. Validate-during-install

- **Decision**: After collecting credentials, immediately run one authenticated fetch of
  `/oscamapi.json?part=userstats`. Success (HTTP 200 + parseable users) → save. 401/403 → report
  "authentication failed", re-prompt user/pass. Connection/timeout → report "unreachable", let
  operator fix host/port or abort. (Spec FR-005; decision confirmed by operator.)
- **Rationale**: Prevents a saved "successful" install with bad credentials (SC-002).
- **Alternatives**: save-then-fail-at-first-poll — rejected by operator decision.

**Output**: All NEEDS CLARIFICATION resolved. Ready for Phase 1 design.
