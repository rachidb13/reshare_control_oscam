# WebIF Endpoint Contract (external dependency)

The tool depends on an OSCAM WebIF at `http://{host}:{port}`, plain HTTP, ~5s timeout. Auth is
negotiated probe → Digest → Basic (`curl --anyauth`; omit `-u` when credentials are empty). Digest
`uri`/HA2 is per-endpoint (curl handles this).

## GET `/oscamapi.json?part=userstats`  (primary — counters)
- **Consumes**: authenticated GET.
- **Provides**: user objects with `usermd5`, `disabled`, `status`, `ip`, `protocol`, `idlesecs`,
  `cwok`, `cwnok`, and the reshare signal **`total_ecm_min`**. Some builds also include plaintext
  `name`/`username`.
- **Tolerated shapes** (normalizer): `oscam.userstats.user[]` | `oscam.users[]` |
  `oscam.status.client[]` | flat `oscam.user`/`oscam.client`; single object → wrap; `{ "user": {…} }`
  → unwrap; `name` vs `username`.
- **Failure → engine**: non-2xx / timeout / unparseable → `NO_READING` for all users that cycle.

## GET `/userconfig.html`  (fallback — plaintext usernames)
- **Consumes**: authenticated GET (only when JSON lacks plaintext names).
- **Provides**: HTML table; username in `td.usercol1` (`data-sort-value` or link text); online/idle.
- **Use**: join to JSON stats via `md5(username) == usermd5`.

## GET `/userconfig.html?action=reinit`  (apply enforcement live)
- **Consumes**: authenticated GET, same credentials.
- **Effect**: OSCAM re-reads `oscam.user` without a full restart; applies a `disabled` change live.
- **Called after**: any edit to `oscam.user` (stop or re-enable).

## GET `api.html?part=status`  (XML presence/idle fallback — optional)
- **Provides**: `status/client[]` (`type="c"` = user connections), `name`, `times[idle]`.
- **Limitation**: ECM/min not reliably present → presence/idle only, not a strike source.

## Non-endpoint dependency: `{base_path}/oscam.user` (filesystem)
- Read/edited in place; **only** the target `[account]` block's `disabled` line is changed. Never
  `oscam.conf` / `oscam.server`.
