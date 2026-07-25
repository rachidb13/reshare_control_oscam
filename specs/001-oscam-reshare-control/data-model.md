# Phase 1 Data Model: OSCAM Reshare Control

## Entities

### 1. InstanceConfig  (persisted: `config.json`, mode 0600)

The single monitored OSCAM instance plus tuning. Written by `install.sh`, read every cycle.

| Field | Type | Default | Validation |
|---|---|---|---|
| `host` | string | — (required) | non-empty; hostname or IP |
| `port` | integer | — (required) | 1–65535 (no universal default; operator supplies) |
| `webif_user` | string | `""` | may be empty (open WebIF) |
| `webif_pass` | string (secret) | `""` | may be empty; never logged/echoed |
| `base_path` | string | `/usr/local/etc` or detected | dir containing `oscam.user`; must exist for enforcement |
| `max_ecm_per_min` | number | `20` | > 0 |
| `strike_count` | integer | `3` | >= 1 |
| `auto_stop_enabled` | boolean | `false` | — |
| `poll_interval_min` | integer | `5` | >= 1 (drives scheduler) |
| `request_timeout_s` | integer | `5` | >= 1 |
| `exempt_users` | string[] | `[]` | list of usernames never auto-stopped |

**Notes**: `webif_pass` stored in the 0600 file (encryption at rest deferred). Re-running install
updates fields in place (FR-009).

---

### 2. MonitoredUser  (transient, per cycle — not persisted)

Normalized from the WebIF response, regardless of build shape.

| Field | Type | Source |
|---|---|---|
| `name` | string | plaintext `name`/`username`, or resolved from HTML via md5 join |
| `usermd5` | string \| null | JSON `usermd5` (join key when name hidden) |
| `disabled` | bool | JSON `disabled == "1"` → skipped |
| `ecm_per_min` | number \| NO_READING | `number(total_ecm_min)`, else `NO_READING` |
| `raw_webif_stats` | map | all scalar fields preserved (status, ip, protocol, cwok, …) |

`NO_READING` is a distinct sentinel, never coerced to a number.

---

### 3. UserStrikeState  (persisted: `state.json`, mode 0600)

Per-user memory that makes "consecutive" meaningful across runs. Keyed by `name`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `consecutive_strikes` | integer | `0` | the streak |
| `last_observed_ecm_min` | number \| null | `null` | last numeric reading only |
| `last_evaluated_at` | ISO-8601 string | — | updated every cycle incl. NO_READING |
| `status` | enum | `ok` | `ok` \| `flagged` \| `stopped`; `flagged` only when `strikes >= strike_count` |
| `exempt` | boolean | `false` | mirrors config exemption; shown but never stopped |

**State transitions** (per active, non-disabled user each cycle):

```
  reading == NO_READING  -> streak unchanged (update last_evaluated_at only)
  reading  >  max        -> strikes += 1
  reading <=  max        -> strikes  = 0

  # status is DERIVED from the streak (not set on a single over-limit reading):
  status = flagged   iff  strikes >= strike_count      # FR-015 / SC-003
  status = ok        otherwise

  if auto_stop_enabled and strikes >= strike_count
     and not exempt and not already disabled:
        STOP(user); status = stopped
```

- **Flag only at threshold**: a single over-limit spike increments the streak but does NOT flag the
  user; `status=flagged` requires `strikes >= strike_count` (FR-015, SC-003). The intermediate
  build-up is visible via `consecutive_strikes`.
- `NO_READING` is inert: neither strike nor reset (Principle I).
- Once `stopped`, the user is skipped in later cycles until re-enabled (FR-021).
- Re-enable resets `consecutive_strikes=0`, `status=ok` (FR-023).

---

### 4. AuditRecord  (append-only log line)

Every stop/reinstate. Written to an audit log (usernames masked in the general log; the audit log
records the action trail).

| Field | Type |
|---|---|
| `timestamp` | ISO-8601 |
| `action` | `stop` \| `reinstate` |
| `user` | string |
| `observed_ecm_min` | number \| null |
| `threshold` | number (max_ecm_per_min at time of action) |
| `strike_count` | integer (streak at time of action) |
| `result` | `ok` \| `error:<reason>` |

**On `stop`**: `observed_ecm_min` is the numeric reading that triggered the stop; `strike_count` is
the streak that met the threshold. **On `reinstate`** (manual `enable-user`): there may be no current
reading — record the user's `last_observed_ecm_min` if present, else `null`; `strike_count` is the
pre-reset streak (0 if never struck). `null` is a valid `observed_ecm_min` for reinstate and does not
count as an error.

---

## Relationships

- One `InstanceConfig` ⟷ many `UserStrikeState` (keyed by username).
- Each cycle maps many `MonitoredUser` (transient) onto `UserStrikeState` by `name`.
- Each `STOP`/`reinstate` emits one `AuditRecord`.

## Derived / invariants

- A user present in `state.json` but absent from a cycle's response → `NO_READING` (streak held).
- `state.json` never contains a numeric reading that wasn't observed as numeric.
- `disabled==1` users are skipped before the engine (never create/advance state).
