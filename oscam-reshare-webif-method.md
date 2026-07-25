# OSCAM WebIF — Reshare Detection & Auto‑Stop Method

**Purpose of this document.** It is a **standalone, protocol‑level spec** of how to log in to an OSCAM WebIF, pull per‑user statistics (especially **ECM/min**), detect resharers, and stop them. It is written so that a script author (or an AI in a *different* project) can build a self‑contained VPS tool — a `.sh` script, a small Go/Python/Node daemon, whatever — **without access to the original PHP codebase**. Everything here is the *method*, not a code dependency.

It was distilled from a working PHP implementation (`OscamWebifUserStatsClient`, `OscamWebifReloadClient`, `OscamUserDirectWriteService` and the reshare "strike engine"). Where a value is a default (port, timeout, threshold), it is called out as such.

---

## 1. Overview — what the script must do, end to end

Run on a schedule (e.g. every **5 minutes**) and for each OSCAM instance you manage:

1. **Connect** to the OSCAM WebIF over HTTP: `http://{host}:{port}`.
2. **Authenticate** if challenged (HTTP **Digest**, falling back to **Basic**).
3. **Fetch two endpoints** and correlate them:
   - `/userconfig.html` → gives **plaintext usernames** (and basic online/idle state).
   - `/oscamapi.json?part=userstats` → gives **detailed counters incl. `total_ecm_min`**, but keys users by **`usermd5`** (an MD5 hash), *not* plaintext name.
   - Correlate with **`md5(username) == usermd5`**.
4. **Extract per‑user `ecm_per_min`** (from the JSON field `total_ecm_min`).
5. **Run the strike engine**: compare each user's ECM/min to a threshold; count *consecutive* over‑limit polls.
6. **Stop** a user who has been over the limit for N consecutive polls: set `disabled=1` in that user's block in `oscam.user` and **reload** OSCAM so the change takes effect.
7. **Persist per‑user state** (strike counts) between runs so "consecutive" is meaningful across the schedule.

Key correctness rule baked into the algorithm: **a missing/failed reading is neither a strike nor a reset** — only a *successfully fetched, numeric* ECM/min value is evaluated. A single momentary spike must never stop a user; only *sustained* over‑limit does.

---

## 2. WebIF connection basics

- **Base URL:** `http://{host}:{port}` — plain **HTTP**, not HTTPS, by default. OSCAM's WebIF is typically an internal/LAN service.
- **Default port:** OSCAM's WebIF port is whatever is set as `httpport` in `oscam.conf` (commonly **8888**, but there is no universal default — you must know/configure it per instance).
- **Timeouts:** use a short connect/read timeout (**~5 seconds**). WebIFs are local and either answer fast or are down.
- **Two endpoints, and why both are needed:**

  | Endpoint | Gives you | Missing |
  |---|---|---|
  | `GET /userconfig.html` | **plaintext usernames**, online/offline, IP, protocol, idle time | detailed counters |
  | `GET /oscamapi.json?part=userstats` | detailed counters incl. **`total_ecm_min`**, cwok/cwnok, status, ip, protocol, idlesecs, disabled | **plaintext username** (only `usermd5`) |

  The JSON API deliberately exposes `usermd5` (an MD5 of the username) instead of the plaintext name. So you fetch usernames from the HTML page, then **join** each username to its JSON stats by computing `md5(lowercased-or-exact username)` and matching it against `usermd5`. In the reference implementation the hash is `md5(username)` using the username exactly as it appears in the HTML.

> If your OSCAM build's `/oscamapi.json` *does* include a plaintext `name` field per user (some builds do), you can skip the HTML step entirely and read `total_ecm_min` directly. Treat the HTML+correlation path as the robust fallback that works on builds that hash the username.

---

## 3. Authentication (the crux)

OSCAM WebIF may be open (no auth) or protected. Support all three cases with this flow:

### 3.1 Probe first (no credentials)
Send the request **without** an `Authorization` header.
- If it returns **200**, the WebIF is open — use the body directly.
- If it returns **401 or 403**, read the `WWW-Authenticate` response header to pick the scheme.

### 3.2 HTTP Digest (preferred when offered)
If `WWW-Authenticate: Digest ...` is present, parse its parameters (`realm`, `nonce`, and optionally `qop`, `opaque`, `algorithm`). Compute the response:

```
HA1 = MD5( username : realm : password )
# If algorithm is "MD5-SESS":
HA1 = MD5( HA1 : nonce : cnonce )

HA2 = MD5( method : uri )          # method = "GET", uri = the path incl. query, e.g. "/oscamapi.json?part=userstats"

# If qop is "auth" (or "auth-int"):
cnonce = <random hex, e.g. 8 bytes>
nc     = "00000001"                # request counter, zero-padded 8 hex digits
response = MD5( HA1 : nonce : nc : cnonce : qop : HA2 )

# If qop is absent (legacy):
response = MD5( HA1 : nonce : HA2 )
```

Send it back as:

```
Authorization: Digest username="<user>", realm="<realm>", nonce="<nonce>",
  uri="<uri>", algorithm=<MD5|MD5-SESS>, response="<response>"
```

Append `, qop=<qop>, nc=<nc>, cnonce="<cnonce>"` **only** when `qop` was offered, and `, opaque="<opaque>"` if the challenge included an `opaque` value.

Important detail: the **`uri` used in HA2 and in the header must be the exact request path including the query string** (e.g. `/oscamapi.json?part=userstats`), and the **method is `GET`**. Recompute digest per endpoint because the URI differs.

### 3.3 Basic (fallback)
If no Digest challenge is parseable, fall back to:

```
Authorization: Basic base64( "<user>:<password>" )
```

### 3.4 After auth
Re‑send the request with the `Authorization` header. If it **still** returns 401/403, the credentials are wrong — treat the instance as *unreadable this cycle* (no strike, no reset). Distinguish clearly between "auth failed" and "unreachable/transport error".

---

## 4. Parsing users & extracting ECM/min

### 4.1 OSCAM JSON `userstats` structure
`GET /oscamapi.json?part=userstats` returns (fields vary by build):

```json
{
  "oscam": {
    "userstats": {
      "totalusers": 12,
      "totalconnected": 5,
      "totalonline": 5,
      "user": [
        {
          "name": "someuser",          // present on some builds; ABSENT on builds that hash
          "usermd5": "e3b0c442...",     // md5 of the username — the JOIN key
          "status": "online",
          "ip": "105.235.139.162",
          "protocol": "cccam (2.3.2-4000)",
          "idlesecs": "10",
          "disabled": "0",
          "cwok": "50",
          "cwnok": "1",
          "total_ecm_min": "18"          // ← THE RESHARE SIGNAL: ECM per minute
        }
      ]
    }
  }
}
```

**Build‑specific shapes you must tolerate** (the reference client handles all of these):
- The user list may live at `oscam.userstats.user[]`, or `oscam.users[]`, or `oscam.status.client[]`, or flat `oscam.user` / `oscam.client`.
- The container may be a **direct JSON list** of user objects, or an object with a `user`/`client` sub‑array.
- A **single** user may be returned as an object instead of a 1‑element array — wrap it.
- Some builds wrap each entry as `{ "user": { ...fields... } }` — **unwrap** the single `user` key.
- Field name for the username is `name` on some builds, `username` on others.
- **Skip users with `disabled == "1"`.**

### 4.2 The ECM/min value
The reshare signal is the JSON field **`total_ecm_min`** on each user object. Read it, coerce to a number, and use that as the user's current ECM/min. In the reference pipeline all scalar JSON fields per user are preserved into a `raw_webif_stats` map and `ecm_per_min` is simply `raw_webif_stats.total_ecm_min`.

Treat as **"no reading"** (do not strike, do not reset) when: the fetch failed / instance unreachable, the HTTP status wasn't a success, the user isn't present in the response, or `total_ecm_min` is missing/non‑numeric.

### 4.3 HTML fallback (for usernames / when JSON lacks names)
`GET /userconfig.html` returns an HTML table (OSCAM r11724‑style):
- Each user row is a `<tr class="online|offline|...">`.
- Username is in `td.usercol1` as `data-sort-value="username"` (or the link text).
- `td.usercol2` holds `<B>online</B>`/`<B>offline</B>` and the IP; `td.usercol3` is idle time like `00:00:10`; `td.usercol4` is protocol.
- Parse usernames from here, then correlate to JSON stats via `md5(username)`.

### 4.4 XML fallback (some builds)
A few builds answer `api.html?part=status` with XML: `status/client[]` where `type="c"` are client (user) connections, `name` is the username, and `times[idle]` is idle seconds. Aggregate multiple connections per username. (ECM/min counters aren't reliably present here — XML is mainly a presence/idle fallback.)

---

## 5. Reshare detection algorithm (the "strike engine")

State to persist **per user** (keyed by username, and ideally per OSCAM instance if you manage several): `consecutive_strikes`, `last_observed_ecm_min`, `last_evaluated_at`, `status` (`ok` / `flagged` / `stopped`), and an `exempt` flag for trusted users.

Config (global, tunable):
- `max_ecm_per_min` — the threshold. **Default 20.**
- `strike_count` — consecutive over‑limit polls required to stop. **Default 3.**
- `auto_stop_enabled` — master switch. **Default OFF** (detection‑only) so you can watch who gets flagged before enforcing.

Each poll, for each active (non‑disabled) user:

```
reading = current numeric total_ecm_min   # or NONE if unreachable/missing/non-numeric

if reading is NONE:
    # neither strike nor reset — just note we tried
    last_evaluated_at = now
    continue

if reading > max_ecm_per_min:
    consecutive_strikes += 1
    status = 'flagged'            # any user with >=1 strike and not stopped is "flagged"
else:                            # reading <= threshold
    consecutive_strikes = 0
    status = 'ok'

last_observed_ecm_min = reading
last_evaluated_at = now

if auto_stop_enabled
   and consecutive_strikes >= strike_count
   and not exempt
   and user is not already disabled:
        STOP(user)                # see section 6
        status = 'stopped'
```

Guarantees this encodes:
- **No single‑spike stops:** one over‑limit poll followed by an under‑limit poll resets the streak.
- **Absent data is inert:** an unreachable instance never accidentally resets a building streak *or* adds a false strike.
- **Detection‑only mode:** with `auto_stop_enabled = false`, users still accumulate strikes and show as flagged, but are never stopped.
- **Exemptions:** an exempt (trusted) user is evaluated/shown but never auto‑stopped.

Audit every stop/reinstate (who, when, observed ECM/min, threshold, strike count) — you'll want the trail.

---

## 6. Stopping (and re‑enabling) a resharer

OSCAM users live as blocks in the **`oscam.user`** file, e.g.:

```
[account]
user     = someuser
pwd      = secret
disabled = 0
...
```

**To stop a user** (the mechanism the panel uses):
1. Read the instance's `oscam.user` (path is `{base_path}/oscam.user` on that VPS).
2. In that user's block, set **`disabled = 1`** (add the line if absent). Do **not** touch `oscam.conf` / `oscam.server` — only the user's account block in `oscam.user`.
3. **Reload OSCAM** so it re‑reads config *without a full restart*:

   ```
   GET http://{host}:{port}/userconfig.html?action=reinit
   ```
   using the **same Digest/Basic auth** as the stats calls. This is OSCAM's "reinit user file" action and applies the disable live.

**To re‑enable** (recover a false positive): set `disabled = 0` in the block and hit the same `?action=reinit` reload; reset that user's `consecutive_strikes` to 0 and `status` to `ok`.

> Editing `oscam.user` requires the script to run on (or have file access to) the box hosting that OSCAM instance. If your standalone tool is remote, you either (a) run an agent locally on each VPS, or (b) if the WebIF build exposes a user‑write/disable action, use that — but the file‑edit‑plus‑`reinit` recipe above is the portable one and matches the reference implementation.

---

## 7. Gotchas & operational notes

- **HTTP, not HTTPS** on the WebIF by default. Don't assume TLS.
- **Per‑endpoint digest:** recompute the Digest `uri`/HA2 for each path — `/userconfig.html` and `/oscamapi.json?part=userstats` produce different responses.
- **Timeouts ~5s**, and treat *transport failure* and *auth failure* as "no reading" for the strike engine (never as under‑limit).
- **Poll cadence ~5 min.** Faster polling gives quicker enforcement but more WebIF load; the "consecutive strikes" window scales with your interval (3 strikes × 5 min ≈ 15 min of sustained abuse before a stop).
- **Skip `disabled=1` users** in parsing; also skip already‑stopped users so you don't double‑act or double‑log.
- **`total_ecm_min` availability varies** by OSCAM build. Verify it's present on your target build; if not, you may need to derive a rate from ECM counters over two polls (Δcwok / Δminutes) as a fallback.
- **Credentials:** store WebIF user/pass securely (not world‑readable); the reference implementation encrypts them at rest. Mask usernames in logs.
- **Multiple connections per user:** the same username can appear on several connection rows — aggregate them; ECM/min in the JSON is already the per‑user total.

---

## 8. Minimal working examples (`curl` + `jq`)

**8.1 Unauth probe** (discover whether auth is needed and which scheme):
```bash
curl -sS -i --max-time 5 "http://$HOST:$PORT/oscamapi.json?part=userstats" | head -n 20
# Look at the status line and any `WWW-Authenticate:` header.
```

**8.2 Digest‑authenticated fetch** (curl computes the digest for you):
```bash
curl -sS --max-time 5 --digest -u "$WEBUSER:$WEBPASS" \
  "http://$HOST:$PORT/oscamapi.json?part=userstats"
```

**8.3 Basic‑authenticated fetch** (fallback):
```bash
curl -sS --max-time 5 -u "$WEBUSER:$WEBPASS" \
  "http://$HOST:$PORT/oscamapi.json?part=userstats"
```
> Tip: `curl --anyauth -u user:pass` will negotiate Digest‑or‑Basic automatically from the challenge, which mirrors the probe‑then‑auth flow in section 3.

**8.4 Extract ECM/min per user from the JSON** (handles the common `oscam.userstats.user[]` shape):
```bash
curl -sS --max-time 5 --anyauth -u "$WEBUSER:$WEBPASS" \
  "http://$HOST:$PORT/oscamapi.json?part=userstats" \
| jq -r '
    .oscam.userstats.user[]
    | select((.disabled // "0") != "1")
    | [ (.name // .usermd5), (.total_ecm_min // "NA"), (.status // "") ]
    | @tsv
  '
# Output columns: name-or-usermd5   total_ecm_min   status
```

**8.5 Correlate usernames (from HTML) to usermd5 (from JSON)** — pseudocode:
```
usernames = parse_userconfig_html( GET /userconfig.html )     # -> ["someuser", ...]
json_by_md5 = index( GET /oscamapi.json?part=userstats , key = .usermd5 )
for name in usernames:
    stats = json_by_md5[ md5(name) ]                          # join
    ecm_per_min = number(stats.total_ecm_min)                 # the reshare signal
```

**8.6 Disable a resharer, then reload:**
```bash
# 1) edit the block in {base_path}/oscam.user: set `disabled = 1` for [account] user=<name>
#    (do this with a safe in-place edit that only touches that user's block)
# 2) tell OSCAM to re-read the user file live:
curl -sS --max-time 5 --anyauth -u "$WEBUSER:$WEBPASS" \
  "http://$HOST:$PORT/userconfig.html?action=reinit" > /dev/null
```

---

### Summary for the downstream implementer
Poll each OSCAM WebIF every ~5 min over plain HTTP; probe unauthenticated, then satisfy a **Digest** (or **Basic**) challenge; pull `/userconfig.html` for plaintext usernames and `/oscamapi.json?part=userstats` for counters, joining them via `md5(username) == usermd5`; read **`total_ecm_min`** as each user's ECM/min. Keep a per‑user **consecutive‑strike** counter (over threshold → +1, at/under → reset, **no reading → unchanged**); after N consecutive strikes (default 20 ECM/min, 3 strikes, enforcement off by default) set **`disabled = 1`** in that user's `oscam.user` block and call **`/userconfig.html?action=reinit`** to apply it live. Re‑enable by reverting the flag and reloading. That is the entire method the panel uses — everything above is protocol‑level and language‑agnostic, ready to become a `.sh` (or other) auto‑install script.
