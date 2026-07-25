# Feature Specification: OSCAM Reshare Control

**Feature Branch**: `001-oscam-reshare-control`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "The tool is installed via a one-line SSH command. During installation the script must ask the operator for the OSCAM WebIF connection details (host, port, user, password) because it uses them to log into the WebIF and read per-user details. Single instance per install, validate the login during installation, store the config as a chmod 600 plaintext file."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guided one-line install with credential collection (Priority: P1)

An operator manages an OSCAM box and wants monitoring running in under a couple of minutes.
They paste a single command into the VPS's SSH terminal. The installer interactively asks for
the WebIF **host**, **port**, **username**, and **password**, immediately confirms it can log in
and read user statistics, saves the details in a protected config file, and schedules recurring
monitoring. The operator never has to hand-edit a config file.

**Why this priority**: Nothing else in the tool can function until it can authenticate to the
WebIF. This is the entry point and the minimum viable product — a correctly configured, verified
connection with monitoring scheduled.

**Independent Test**: Run the one-line install on a box with a reachable WebIF, answer the four
prompts, and confirm the installer reports a successful login, writes an owner-only config file,
and registers a recurring schedule — with no further manual steps.

**Acceptance Scenarios**:

1. **Given** a reachable WebIF with correct credentials, **When** the operator runs the one-liner
   and answers host/port/user/password, **Then** the installer confirms a successful login, saves
   the config readable only by its owner, schedules monitoring, and reports success.
2. **Given** the installer is launched through the one-line piped command, **When** it reaches the
   prompts, **Then** it reads the operator's typed answers from the interactive terminal (not from
   the download stream) so every prompt is answered correctly.
3. **Given** a wrong username or password, **When** the installer tests the login, **Then** it
   reports an authentication failure and re-asks for the credentials rather than saving them.
4. **Given** the WebIF host/port is unreachable, **When** the installer tests the connection,
   **Then** it reports an unreachable/connection error (distinct from an auth failure) and lets the
   operator correct the value or abort.
5. **Given** the operator entered a password, **When** they type it at the prompt, **Then** the
   password is not echoed to the screen and does not appear in shell history or logs.

---

### User Story 2 - Scheduled reshare detection and flagging (Priority: P2)

Once installed, the tool runs on a recurring schedule. Each cycle it logs in, reads every active
user's current ECM/min, and tracks who is exceeding the configured limit. Users who stay over the
limit across consecutive cycles are flagged as suspected resharers so the operator can review them
before any enforcement happens.

**Why this priority**: This is the core value — surfacing resharers — and it is deliberately
separated from enforcement so operators can observe who would be affected before turning stopping on.

**Independent Test**: With detection running and enforcement off, drive a test user above the limit
for the required number of consecutive cycles and confirm it becomes flagged, while a user with a
single brief spike is never flagged.

**Acceptance Scenarios**:

1. **Given** a user's ECM/min is above the limit for the required number of consecutive cycles,
   **When** the schedule runs, **Then** the user is flagged as a suspected resharer.
2. **Given** a user exceeds the limit in one cycle but is at/under the limit in the next, **When**
   the schedule runs, **Then** the user's strike streak resets and the user is not flagged.
3. **Given** the WebIF is unreachable, times out, or omits a user, or the user's ECM/min value is
   missing/non-numeric, **When** that cycle runs, **Then** that reading is treated as "no reading":
   it neither adds a strike nor resets an existing streak.
4. **Given** enforcement is disabled (the default), **When** a user reaches the strike limit,
   **Then** the user is flagged but is not stopped.
5. **Given** a user is currently disabled at the WebIF, **When** the schedule runs, **Then** that
   user is skipped and not evaluated.

---

### User Story 3 - Automatic stop of sustained resharers and recovery (Priority: P3)

When the operator opts in to enforcement, a user who has been over the limit for the required number
of consecutive cycles is automatically stopped: their account is disabled and the change is applied
live without restarting the service. Every stop is recorded. If the operator determines a stop was a
mistake, they can re-enable the user and clear its strike history.

**Why this priority**: Enforcement is the highest-impact and highest-risk action (it can disable a
paying user), so it comes last, behind reliable detection, and is off by default.

**Independent Test**: With enforcement enabled, drive a test user over the limit for the required
consecutive cycles and confirm the account becomes disabled and active immediately; then re-enable it
and confirm it is active again and its strike count is cleared.

**Acceptance Scenarios**:

1. **Given** enforcement is enabled and a user reaches the strike limit, **When** the schedule runs,
   **Then** the user's account is disabled, the change is applied live (no full restart), and the
   action is recorded with who/when/observed ECM/min/threshold/strike count.
2. **Given** enforcement is enabled and a user is marked trusted/exempt, **When** that user exceeds
   the limit for the required cycles, **Then** the user is shown as flagged but is never stopped.
3. **Given** a user was stopped by mistake, **When** the operator re-enables that user, **Then** the
   account becomes active again live, the strike streak is reset to zero, and the recovery is recorded.
4. **Given** a user has already been stopped, **When** subsequent cycles run, **Then** the tool does
   not act on or re-log that user again.

---

### Edge Cases

- **Piped-install stdin**: prompts must come from the interactive terminal even though the installer
  itself arrives via a piped one-line command.
- **No universal default port**: the WebIF port varies per box; the installer must require/confirm it
  rather than silently assuming one.
- **Open WebIF (no auth)**: if the WebIF requires no credentials, the operator may leave user/password
  blank and the tool still reads stats.
- **WebIF that hides usernames**: some builds expose only a hashed user id; the tool must still match
  each user to its statistics.
- **Build variation in statistics format**: the tool must tolerate the known differences in how the
  WebIF returns user lists without crashing or losing users.
- **Re-running the installer**: a second run on the same box updates the existing configuration rather
  than creating a broken duplicate.
- **Missing ECM/min metric on a build**: if the reshare signal is unavailable, the tool must not
  silently treat every user as under-limit.

## Requirements *(mandatory)*

### Functional Requirements

**Installation & configuration**

- **FR-001**: The tool MUST be installable via a single command pasted into an SSH terminal.
- **FR-002**: During installation the tool MUST interactively prompt the operator for the WebIF
  **host**, **port**, **username**, and **password**.
- **FR-003**: The installer MUST read operator answers from the interactive terminal even when the
  installer is delivered through a piped one-line command, so prompts are answered by the operator's
  typing rather than the delivery stream.
- **FR-004**: The password prompt MUST NOT echo the entered value to the screen and MUST NOT leak the
  password into shell history or logs.
- **FR-005**: The installer MUST validate the entered credentials by performing a real login and
  reading user statistics before saving them; on authentication failure it MUST re-prompt, and on a
  connection/unreachable error it MUST report that distinctly and let the operator correct or abort.
- **FR-006**: The installer MUST persist the configuration in a file readable and writable only by its
  owner (equivalent to `chmod 600`), and MUST mask usernames in any logs.
- **FR-007**: Each install MUST configure exactly **one** OSCAM instance; managing another box is done
  by running the installer again on that box.
- **FR-008**: The installer MUST register recurring monitoring on a schedule (default cadence ~5
  minutes) so monitoring runs without further operator action.
- **FR-009**: Re-running the installer on an already-configured box MUST update the existing
  configuration instead of producing a broken or duplicate setup.

**Detection & strike engine**

- **FR-010**: Each cycle the tool MUST log in to the WebIF and obtain each active user's current
  ECM/min value, matching each user to its statistics even on builds that hide the plaintext username.
- **FR-011**: The tool MUST skip users that are already disabled at the WebIF.
- **FR-012**: For each active user, a numeric ECM/min reading **above** the configured limit MUST add
  one to that user's consecutive-strike count; a numeric reading **at or under** the limit MUST reset
  that count to zero.
- **FR-013**: A "no reading" — connection/timeout failure, authentication failure, unsuccessful
  response, user absent from the response, or a missing/non-numeric ECM/min value — MUST leave the
  user's strike count unchanged: it is neither a strike nor a reset.
- **FR-014**: The tool MUST distinguish authentication failure from connection/transport failure in
  its records, while treating both as "no reading" for the strike engine.
- **FR-015**: A user MUST be flagged as a suspected resharer once its consecutive-strike count reaches
  the configured strike threshold.
- **FR-016**: Strike state (consecutive strikes, last observed ECM/min, last evaluation time, status,
  exempt flag) MUST persist across cycles so "consecutive" is meaningful over the schedule.
- **FR-017**: The configurable settings MUST include the ECM/min limit (default **20**), the number of
  consecutive over-limit cycles required (default **3**), and an enforcement master switch (default
  **off**).

**Enforcement & recovery**

- **FR-018**: With enforcement **off** (the default), users MUST still accumulate strikes and be
  flagged, but MUST NEVER be stopped.
- **FR-019**: With enforcement **on**, a user reaching the strike threshold MUST be stopped by
  disabling that user's account and applying the change live, without a full service restart, and
  without altering any account other than the target user's.
- **FR-020**: A user marked trusted/exempt MUST be evaluated and shown but MUST NEVER be auto-stopped.
- **FR-021**: A user that has already been stopped MUST NOT be acted on or re-logged in later cycles.
- **FR-022**: Every stop and every re-enable MUST be recorded with the user, timestamp, observed
  ECM/min, threshold, and strike count.
- **FR-023**: The operator MUST be able to re-enable a stopped user; doing so MUST make the account
  active again live and reset that user's strike count to zero.

### Key Entities *(include if feature involves data)*

- **OSCAM Instance Configuration**: The single monitored box — its WebIF host, port, credentials, and
  operational settings (limit, strike threshold, enforcement switch, schedule cadence). Stored
  owner-only.
- **Monitored User**: A user account on the OSCAM instance, identified by name (or a hashed id on
  builds that hide names), carrying the current ECM/min reading and enabled/disabled/exempt state.
- **Strike State**: Per-user persisted record — consecutive strikes, last observed ECM/min, last
  evaluation time, and status (ok / flagged / stopped) — the memory that makes "consecutive" meaningful.
- **Audit Record**: A logged enforcement/recovery event — who, when, observed ECM/min, threshold, and
  strike count — providing a defensible trail.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can go from pasting the one-line command to a running, verified monitor in
  under 3 minutes, answering no more than four prompts.
- **SC-002**: 100% of installs that reach the "success" report have a working, validated WebIF login
  (invalid credentials never produce a saved "successful" install).
- **SC-003**: A user with a single brief over-limit spike is never flagged; only users sustained over
  the limit for the configured number of consecutive cycles are flagged (0% false stops from single
  spikes).
- **SC-004**: During any cycle where the WebIF is unreachable, no user is wrongly reset or wrongly
  struck as a result (an outage changes no user's standing).
- **SC-005**: With default settings, no user is ever automatically stopped (enforcement off by default
  is observable).
- **SC-006**: Every automatic stop and every re-enable appears in the audit trail with all five
  required fields.
- **SC-007**: The saved configuration file is not readable by any account other than its owner.

## Assumptions

- The tool runs on (or has file access to) the box hosting the OSCAM instance it monitors, since
  stopping a user requires editing that instance's user file and reloading it live.
- The WebIF is typically a plain, non-encrypted LAN/internal service; the operator supplies whatever
  port that instance uses (there is no universal default).
- The reshare signal (per-user ECM/min) is available on the target build; where it is not, the tool
  surfaces the gap rather than treating everyone as under-limit.
- "Consecutive cycles" are measured against the configured schedule cadence (default ~5 minutes), so
  the default 3-strike window corresponds to roughly 15 minutes of sustained abuse before a stop.
- Detection-only is the intended out-of-the-box posture; operators opt in to enforcement deliberately.
- Credentials are entered by a trusted operator during install; owner-only file permissions are the
  agreed protection level for this version (encryption at rest is out of scope for v1).
