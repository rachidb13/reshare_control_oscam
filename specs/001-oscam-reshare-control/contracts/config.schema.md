# Contract: config.json

Location: `{config-dir}/config.json` (default `/etc/reshare-control/config.json`). Mode **0600**,
owner-only. Written by `install.sh`; validated on load.

```json
{
  "host": "192.168.1.10",
  "port": 8888,
  "webif_user": "admin",
  "webif_pass": "secret",
  "base_path": "/usr/local/etc",
  "max_ecm_per_min": 20,
  "strike_count": 3,
  "auto_stop_enabled": false,
  "poll_interval_min": 5,
  "request_timeout_s": 5,
  "exempt_users": []
}
```

## Rules
- `host` non-empty; `port` 1–65535 (required, no default — operator supplies).
- `webif_user`/`webif_pass` may be empty (open WebIF).
- `base_path` must contain `oscam.user` for enforcement; if missing, `run` still detects/flags but
  `disable-user`/auto-stop error clearly.
- `max_ecm_per_min > 0`; `strike_count >= 1`; `poll_interval_min >= 1`; `request_timeout_s >= 1`.
- Defaults applied when a key is absent: `max_ecm_per_min=20`, `strike_count=3`,
  `auto_stop_enabled=false`, `poll_interval_min=5`, `request_timeout_s=5`, `exempt_users=[]`.
- File MUST be created/rewritten with mode 0600; loader warns and re-chmods if it finds looser perms.
- `webif_pass` MUST never be echoed to stdout/stderr or written to non-config logs.
