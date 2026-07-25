# Contract: state.json

Location: `{config-dir}/state.json` (default `/etc/reshare-control/state.json`). Mode **0600**.
Keyed by username. Written atomically (temp + rename) under an `fcntl` lock so overlapping cycles
don't corrupt it.

```json
{
  "version": 1,
  "users": {
    "someuser": {
      "consecutive_strikes": 2,
      "last_observed_ecm_min": 24,
      "last_evaluated_at": "2026-07-02T14:05:00Z",
      "status": "flagged",
      "exempt": false
    }
  }
}
```

## Rules
- `status` ∈ { `ok`, `flagged`, `stopped` }.
- `consecutive_strikes >= 0`.
- `last_observed_ecm_min` holds only values that were observed **numeric**; `NO_READING` never
  writes here (stays at prior value; may be `null` if never read).
- `last_evaluated_at` updates every cycle the user was seen, **including** `NO_READING` cycles.
- A user in `state.json` but absent from a cycle's response → treated as `NO_READING` (streak held);
  entry is retained, not deleted.
- Writing MUST preserve mode 0600.
