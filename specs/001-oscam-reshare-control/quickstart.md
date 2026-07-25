# Quickstart: OSCAM Reshare Control

## Install (one line, on the OSCAM box)

```bash
curl -fsSL https://<host>/install.sh | bash
```

The installer prompts you (reading from your terminal, even through the pipe):

```
OSCAM WebIF host [e.g. 127.0.0.1]: 127.0.0.1
OSCAM WebIF port (from httpport in oscam.conf): 8888
WebIF username (blank if open): admin
WebIF password (hidden):
```

It then **validates the login immediately**:
- ✅ *"Login OK — 12 users read."* → writes `/etc/reshare-control/config.json` (chmod 600) and
  installs a systemd timer (or cron `*/5 * * * *`) running detection every 5 minutes.
- ❌ *"Authentication failed"* → re-asks username/password.
- ❌ *"Unreachable"* → lets you fix host/port or abort.

Detection runs in **detection-only mode by default** — nobody is stopped until you enable it.

## Verify

```bash
reshare-control test        # re-check connectivity + credentials
reshare-control run --dry-run   # one cycle, log only, no state/enforcement
reshare-control status      # show per-user strikes / flags
```

## Turn on enforcement (after you trust the flags)

Edit `/etc/reshare-control/config.json`:
```json
"auto_stop_enabled": true
```
Now a user over `max_ecm_per_min` (default 20) for `strike_count` (default 3) consecutive cycles
(~15 min) is disabled in `oscam.user` and applied live via `?action=reinit`.

## Recover a false positive

```bash
reshare-control enable-user someuser   # re-enables live + clears strikes
```

## Exempt a trusted user

```bash
reshare-control exempt-user vipuser    # evaluated & shown, never auto-stopped
```

## Acceptance smoke test (maps to spec Success Criteria)

1. **SC-001/002**: fresh install ≤ 4 prompts, ≤ 3 min, and a wrong password never yields a saved
   "success".
2. **SC-003**: drive a test user over-limit once then under-limit → never flagged; over-limit for 3
   cycles → flagged.
3. **SC-004**: stop the WebIF for a cycle → no user's strikes change.
4. **SC-005**: with defaults, no user is ever stopped.
5. **SC-006**: every stop/enable appears in the audit log with all five fields.
6. **SC-007**: `stat -c '%a' /etc/reshare-control/config.json` → `600`.
