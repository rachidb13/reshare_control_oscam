# Tasks: OSCAM Reshare Control

**Input**: Design documents from `/specs/001-oscam-reshare-control/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Targeted tests are mandatory for constitution-critical strike transitions, build-shape parsing with md5 join, least-intrusive enforcement edits, and full poller cycles with a fake fetcher.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Paths shown below follow the exact source structure from `specs/001-oscam-reshare-control/plan.md`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create the Python package skeleton in `src/reshare_control/__init__.py`
- [x] T002 [P] Create executable entry-point scaffolding for commands in `src/reshare_control/cli.py`
- [x] T003 [P] Create installer scaffolding with POSIX shell mode and usage comments in `install.sh`
- [x] T004 [P] Create systemd scheduling asset scaffolds in `packaging/reshare-control.service` and `packaging/reshare-control.timer`
- [x] T005 [P] Create test directories and fixture placeholders in `tests/unit/`, `tests/integration/`, and `tests/fixtures/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T006 Implement `InstanceConfig` defaults, validation, atomic owner-only `0600` read/write, and username/password log masking in `src/reshare_control/config.py`
- [x] T007 [P] Implement `state.json` load/save, `0600` preservation, atomic temp+rename writes, and file locking primitives in `src/reshare_control/state.py`
- [x] T008 [P] Define normalized user records and the `NO_READING` sentinel shared by parser, strike engine, and poller in `src/reshare_control/parse.py`
- [x] T009 Implement the fake-able WebIF fetcher boundary, curl command builder, `--anyauth` handling, empty-credential open WebIF mode, timeout mapping, auth-vs-transport result codes, and reinit request helper in `src/reshare_control/webif.py`
- [x] T010 Wire global `--config-dir`, shared config loading, command dispatch, stdout/stderr conventions, JSON option handling, and exit-code plumbing in `src/reshare_control/cli.py`
- [x] T011 [P] Add captured WebIF JSON/HTML/XML fixture files covering documented build shapes, hidden username `usermd5`, disabled users, and missing/non-numeric `total_ecm_min` in `tests/fixtures/`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Guided one-line install with credential collection (Priority: P1) 🎯 MVP

**Goal**: Operator pastes one SSH command, answers WebIF host/port/user/password prompts from the interactive terminal, gets validated config saved owner-only, and monitoring scheduled.

**Independent Test**: Run `curl -fsSL https://<host>/install.sh | bash`, answer the four prompts, and confirm validation succeeds, `/etc/reshare-control/config.json` is mode `600`, and the recurring schedule is installed without manual config edits.

### Implementation for User Story 1

- [x] T012 [US1] Implement `/dev/tty` host, port, username, and hidden password prompts with no stdin reads from the piped stream in `install.sh`
- [x] T013 [US1] Implement validation loop behavior for successful login, authentication failure re-prompt, and unreachable host/port correction or abort in `install.sh`
- [x] T014 [US1] Implement `reshare-control test` connectivity validation against `/oscamapi.json?part=userstats` with exit codes 0, 2, 3, and 4 in `src/reshare_control/cli.py`
- [x] T015 [US1] Implement parseable-user validation for installer and `test` command responses in `src/reshare_control/parse.py`
- [x] T016 [US1] Implement install-time `config.json` creation/update with required host/port, optional open-WebIF credentials, defaults, one-instance semantics, and mode `0600` in `install.sh`
- [x] T017 [US1] Implement idempotent re-run behavior that updates the existing config and avoids duplicate service/timer or cron entries in `install.sh`
- [x] T018 [US1] Implement systemd timer installation using `packaging/reshare-control.service` and `packaging/reshare-control.timer`, with cron `*/5 * * * *` fallback in `install.sh`
- [x] T019 [US1] Fill `packaging/reshare-control.service` with the oneshot `reshare-control run` invocation and config-dir defaults in `packaging/reshare-control.service`
- [x] T020 [US1] Fill `packaging/reshare-control.timer` with the default approximately 5-minute recurring cadence in `packaging/reshare-control.timer`

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Scheduled reshare detection and flagging (Priority: P2)

**Goal**: Each scheduled cycle reads active users, handles WebIF build variations, applies sustained-strike rules, persists state, and flags suspected resharers without stopping anyone by default.

**Independent Test**: With enforcement off, drive a fake or test user over the limit for the configured consecutive cycles and confirm it becomes flagged, while a single spike resets and a no-reading cycle changes no user's standing.

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T021 [P] [US2] Add strike engine tests for strike, reset, sustained flagging, and no-reading-is-inert transitions in `tests/unit/test_strike.py`
- [x] T022 [P] [US2] Add parser tests for documented JSON/HTML/XML build shapes, single-object wrapping, `{ "user": {...} }` unwrapping, `name`/`username`, `md5(username)==usermd5` join, disabled-user skip, and missing/non-numeric ECM as `NO_READING` in `tests/unit/test_parse.py`
- [x] T023 [P] [US2] Add full detection cycle integration tests with a fake fetcher, persisted state, no live WebIF, enforcement off, no-reading outage inertness, and disabled/stopped skips in `tests/integration/test_poller.py`

### Implementation for User Story 2

- [x] T024 [US2] Implement pure strike evaluation for numeric over-limit increment, numeric at/under-limit reset, `NO_READING` inertness, threshold flagging, and default safe detection-only behavior in `src/reshare_control/strike.py`
- [x] T025 [US2] Implement tolerant WebIF stats normalization and `total_ecm_min` numeric conversion from `/oscamapi.json?part=userstats` in `src/reshare_control/parse.py`
- [x] T026 [US2] Implement username resolution from plaintext names or `/userconfig.html` md5 join for hidden-name builds in `src/reshare_control/parse.py`
- [x] T027 [US2] Implement active-user filtering so `disabled == "1"` users are skipped before strike evaluation in `src/reshare_control/parse.py`
- [x] T028 [US2] Implement persisted per-user strike records, absent-user-as-`NO_READING`, `last_observed_ecm_min` numeric-only updates, `last_evaluated_at` updates, status values, and exempt flag mirroring in `src/reshare_control/state.py`
- [x] T029 [US2] Implement one poll cycle orchestration fetch → parse → evaluate → persist, with fetcher injection for tests and no live WebIF dependency in `src/reshare_control/poller.py`
- [x] T030 [US2] Implement `reshare-control run`, `run --dry-run`, `run --json`, and `status` output including masked usernames in non-JSON output in `src/reshare_control/cli.py`
- [x] T031 [US2] Implement WebIF outage, timeout, unsuccessful response, auth failure, absent user, and unparseable/missing ECM handling as `NO_READING` for the engine while recording auth vs transport distinction in `src/reshare_control/poller.py`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Automatic stop of sustained resharers and recovery (Priority: P3)

**Goal**: When explicitly enabled, sustained non-exempt resharers are disabled by editing only their `oscam.user` block, applying WebIF reinit live, auditing the action, and supporting operator recovery.

**Independent Test**: With enforcement enabled, drive a fake or test user over the threshold and confirm only that user's account is disabled and reinit is called; then run `enable-user <name>` and confirm the account is active, strikes reset, and audit records exist.

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T032 [P] [US3] Add enforcement tests for only-target-block `oscam.user` edits, add/update `disabled` line, idempotent stop for already-disabled users, re-enable reset, permission preservation, and reinit call stubbing in `tests/unit/test_enforce.py`
- [x] T033 [P] [US3] Extend fake-fetcher poller integration tests for enforcement-on stop, enforcement-off no stop, exempt never stopped, already-stopped no re-log, and audit record creation in `tests/integration/test_poller.py`

### Implementation for User Story 3

- [x] T034 [US3] Implement target `[account]` block parsing and least-intrusive `disabled = 1` / `disabled = 0` edits with atomic writes and permission preservation in `src/reshare_control/enforce.py`
- [x] T035 [US3] Implement live apply via `GET /userconfig.html?action=reinit` after stop and re-enable operations in `src/reshare_control/enforce.py`
- [x] T036 [US3] Implement append-only stop and reinstate audit records with timestamp, user, observed ECM/min, threshold, strike count, and result in `src/reshare_control/enforce.py`
- [x] T037 [US3] Integrate auto-stop decisions in `src/reshare_control/poller.py` so enforcement only runs when `auto_stop_enabled=true`, strike threshold is met, user is not exempt, and user is not already stopped
- [x] T038 [US3] Implement `disable-user <name>`, `enable-user <name>`, `exempt-user <name>`, and `unexempt-user <name>` CLI commands in `src/reshare_control/cli.py`
- [x] T039 [US3] Implement re-enable recovery state reset to `consecutive_strikes=0`, `status=ok`, and live reinit coordination in `src/reshare_control/state.py`

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T040 [P] Run and fix `shellcheck install.sh` findings for prompt safety, quoting, idempotent scheduling, and password non-leak behavior in `install.sh`
- [x] T041 [P] Run and fix targeted unit tests for strike, parser, and enforcement behavior in `tests/unit/test_strike.py`, `tests/unit/test_parse.py`, and `tests/unit/test_enforce.py`
- [x] T042 Run and fix full fake-fetcher integration tests for detection and enforcement cycles in `tests/integration/test_poller.py`
- [ ] T043 Validate quickstart smoke tests SC-001 through SC-007 and record any required fixes in `specs/001-oscam-reshare-control/quickstart.md`
- [ ] T044 Review FR-001 through FR-023 traceability against implemented files and close any gaps in `specs/001-oscam-reshare-control/tasks.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel where file ownership allows
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Uses foundational WebIF/config/state boundaries and remains independently testable with fake fetchers
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Integrates with US2 strike state for auto-stop, but manual `disable-user`/`enable-user` can be tested independently with fixture `oscam.user`

### Within Each User Story

- Tests (if included) MUST be written and FAIL before implementation
- For US1, complete T014 (`reshare-control test`) and T015 (parseable-user validation) before
  wiring the installer validation loop T013 — the installer's validation calls that command.
- For US2, complete T021-T023 before T024-T031
- For US3, complete T032-T033 before T034-T039
- Parser and strike engine tasks should complete before poller orchestration
- Enforcement file-edit tasks should complete before poller auto-stop integration
- Story complete before moving to next priority checkpoint

### Requirements Coverage

- **FR-001**: T003, T012, T018
- **FR-002**: T012
- **FR-003**: T012, T040
- **FR-004**: T006, T012, T030, T040
- **FR-005**: T009, T013, T014, T015
- **FR-006**: T006, T016, T043
- **FR-007**: T016, T017
- **FR-008**: T004, T018, T019, T020
- **FR-009**: T017
- **FR-010**: T009, T011, T022, T025, T026, T029
- **FR-011**: T022, T027, T029
- **FR-012**: T021, T024
- **FR-013**: T021, T023, T024, T031
- **FR-014**: T009, T031
- **FR-015**: T021, T024, T029
- **FR-016**: T007, T028, T029
- **FR-017**: T006, T016, T024
- **FR-018**: T023, T024, T030, T033, T037
- **FR-019**: T032, T034, T035, T037
- **FR-020**: T028, T033, T037, T038
- **FR-021**: T023, T033, T037
- **FR-022**: T036, T038
- **FR-023**: T032, T035, T036, T038, T039

> **Infrastructure/meta tasks (intentionally not mapped to a single FR)**: T001, T002, T005, T008,
> T010 (setup + shared scaffolding/boundaries), and T041, T042, T044 (validation/traceability).
> These enable or verify the FR-bearing tasks rather than implementing a specific requirement.
> T041/T042 validate SC-003/SC-004/SC-005/SC-006; T008 underpins FR-013 (the `NO_READING` sentinel).

### Constitution-Critical Behaviors

- **No-reading-is-inert (FR-013, Principle I)**: T021, T023, T024, T031
- **Sustained strikes only (FR-012/FR-015, Principle II)**: T021, T024, T029
- **Safe-by-default enforcement off (FR-017/FR-018, Principle III)**: T006, T016, T024, T030, T033, T037
- **Network boundary isolated behind fake-able fetcher (Principles I/IV)**: T009, T023, T029, T033
- **Build-shape parser + md5 join (Principle IV)**: T011, T022, T025, T026
- **Least-intrusive `oscam.user` edit + live reinit (FR-019, Principle V)**: T032, T034, T035, T037
- **Piped install reads prompts from `/dev/tty` (FR-003)**: T012, T040
- **Validate-on-install (FR-005)**: T013, T014, T015
- **Owner-only `0600` config/state (FR-006/FR-016)**: T006, T007, T016, T043

---

## Parallel Opportunities

- T002, T003, T004, and T005 can run in parallel after T001 is started because they touch different files.
- T007, T008, T010, and T011 can run in parallel once package directories exist.
- T019 and T020 can run in parallel with installer implementation T012-T018 because they touch packaging assets.
- T021, T022, and T023 can run in parallel because they cover separate test files.
- T025, T026, and T027 are parser-focused and can be split by fixture shape if coordinated in `src/reshare_control/parse.py`.
- T032 and T033 can run in parallel because enforcement unit tests and poller integration extensions touch separate test files.
- T034, T035, and T036 are all in `src/reshare_control/enforce.py` and should be sequenced by one owner; T037 and T038 can proceed after their interfaces are stable.
- Polish tasks T040 and T041 can run in parallel; T042 should run after T041; T043 and T044 should run last.

---

## Parallel Example: User Story 2

```bash
# Launch all mandatory US2 tests together:
Task: "Add strike engine tests for strike, reset, sustained flagging, and no-reading-is-inert transitions in tests/unit/test_strike.py"
Task: "Add parser tests for documented JSON/HTML/XML build shapes and md5 join in tests/unit/test_parse.py"
Task: "Add full detection cycle integration tests with a fake fetcher in tests/integration/test_poller.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test one-line install, `/dev/tty` prompts, login validation, `0600` config, and schedule registration independently
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP)
3. Add User Story 2 → Test independently with fake fetcher and fixtures → Deploy/Demo detection-only mode
4. Add User Story 3 → Test independently with fixture `oscam.user` and fake reinit → Deploy/Demo enforcement opt-in mode
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 installer and scheduling
   - Developer B: User Story 2 parser, strike engine, state, and poller
   - Developer C: User Story 3 enforcement, audit, and recovery CLI
3. Stories complete and integrate independently through the fake-able fetcher and persisted config/state contracts

---

## Notes

- [P] tasks = different files, no dependency on another incomplete task
- [Story] label maps task to US1, US2, or US3 for traceability
- Every task description names an exact repository file path
- Targeted tests are intentionally limited to the mandatory constitution and requested integration coverage
- Avoid live WebIF in tests; use fixtures and fake fetchers
