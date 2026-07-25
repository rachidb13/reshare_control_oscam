# CLI Contract: reshare-control

Invoked as `reshare-control <command>` (a thin wrapper over `python3 -m reshare_control`).
Global option: `--config-dir PATH` (default `/etc/reshare-control`). Text in → stdout; errors →
stderr; JSON available via `--json` where noted. Exit 0 = success, non-zero = failure.

## `run`
One poll cycle: fetch → parse → evaluate strike engine → (enforce if enabled) → persist state.
This is what the scheduler (systemd timer / cron) invokes every `poll_interval_min`.

- Options: `--dry-run` (evaluate + log, never write state or enforce), `--json`.
- Output: per-user line `name  ecm_per_min  status  strikes` (username masked unless `--json`).
- Exit: 0 always if the cycle ran (a WebIF outage is `NO_READING`, not a failure); non-zero only on
  config/IO errors.

## `status`
Print current per-user `state.json` (strikes, status, last reading, last evaluated). `--json` for
machine output. Read-only.

## `test`
Validate connectivity + credentials now (the same check `install.sh` runs): one authenticated fetch
of `/oscamapi.json?part=userstats`.
- Exit 0 = authenticated + parseable; 2 = auth failed; 3 = unreachable/timeout; 4 = reachable but
  unparseable/`total_ecm_min` absent (warning).

## `disable-user <name>`
Manually stop a user: set `disabled=1` in `oscam.user` target block, `reinit`, mark `stopped`,
write `AuditRecord(action=stop)`. Respects "only the target block" invariant.

## `enable-user <name>`
Re-enable (recover a false positive): set `disabled=0`, `reinit`, reset `strikes=0`/`status=ok`,
write `AuditRecord(action=reinstate)`.

## `exempt-user <name>` / `unexempt-user <name>`
Add/remove a username in `config.exempt_users`. Exempt users are evaluated and shown but never
auto-stopped.

## Behavioral guarantees (map to FRs)
- `run` never stops a user when `auto_stop_enabled=false` (FR-018).
- `run` skips `disabled==1` and already-`stopped` users (FR-011, FR-021).
- No command edits any file other than `state.json`, `config.json`, and the target user's block in
  `oscam.user` (FR-019, Principle V).
- Passwords never appear in output or logs; usernames masked in non-JSON logs (FR-004, FR-006).
