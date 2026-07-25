<!--
SYNC IMPACT REPORT
Version change: (template / unversioned) → 1.0.0
Bump rationale: Initial ratification. First concrete constitution derived from
  oscam-reshare-webif-method.md; establishes 5 core principles + 2 supporting
  sections. MAJOR (0→1) because this is the first governing baseline.

Principles defined (all new):
  I.   Reading Integrity — No Reading, No Action
  II.  Sustained Evidence Before Enforcement
  III. Safe by Default (Detection Before Enforcement)
  IV.  Protocol Fidelity & Build Tolerance
  V.   Least-Intrusive Mutation & Full Auditability

Added sections:
  - Security & Operational Constraints
  - Development Workflow & Quality Gates
  - Governance

Removed sections: none (template placeholders replaced)

Templates reviewed:
  ✅ .specify/templates/plan-template.md   — "Constitution Check" gate is generic; no change needed
  ✅ .specify/templates/spec-template.md   — no constitution-specific slots; no change needed
  ✅ .specify/templates/tasks-template.md  — task categories generic; no change needed
  ✅ .specify/templates/checklist-template.md — not principle-bound; no change needed

Follow-up TODOs: none. RATIFICATION_DATE set to today (first adoption).
-->

# Reshare Control (OSCAM) Constitution

This project builds a self-contained tool that polls OSCAM WebIF instances, detects
resharers via ECM/min statistics, and optionally stops them. The principles below are
derived from `oscam-reshare-webif-method.md` and are NON-NEGOTIABLE correctness rules.

## Core Principles

### I. Reading Integrity — No Reading, No Action

A user is evaluated ONLY on a *successfully fetched, numeric* `total_ecm_min` value.
A missing, failed, non-numeric, or unreachable reading MUST be treated as inert: it
counts as neither a strike nor a reset.

- Transport failures, HTTP non-success, absent users, and non-numeric `total_ecm_min`
  MUST all map to "no reading" — never to an implicit under-limit (reset).
- Auth failure MUST be distinguished from transport failure in logs, but both are
  "no reading" for the strike engine.
- Rationale: an unreachable instance must never accidentally reset a building streak or
  inject a false strike. Data integrity is the foundation of every enforcement decision.

### II. Sustained Evidence Before Enforcement

Enforcement MUST require N *consecutive* over-limit polls (`strike_count`, default 3).
A single momentary spike MUST NOT stop a user.

- One over-limit poll followed by an at/under-limit poll MUST reset the streak to zero.
- The strike counter is only ever: incremented on a numeric over-limit reading, reset on
  a numeric at/under-limit reading, or left unchanged on "no reading" (Principle I).
- Rationale: resharing is proven by *sustained* abuse, not by one noisy sample.

### III. Safe by Default (Detection Before Enforcement)

Automatic stopping MUST be OFF by default (`auto_stop_enabled = false`). Strikes and
flagging still accrue so operators can observe before enforcing.

- Trusted users marked `exempt` MUST be evaluated and displayed but NEVER auto-stopped.
- Already-disabled/already-stopped users MUST be skipped to avoid double-acting or
  double-logging.
- Defaults are conservative: `max_ecm_per_min = 20`, `strike_count = 3`, enforcement off.
- Rationale: an enforcement tool that can disable paying users must fail safe, not fail loud.

### IV. Protocol Fidelity & Build Tolerance

The WebIF client MUST follow the documented protocol flow and tolerate OSCAM build
variation without crashing.

- Auth flow MUST be: probe unauthenticated → satisfy HTTP **Digest** if challenged →
  fall back to **Basic**. The Digest `uri`/HA2 MUST be recomputed per endpoint (the path
  including query string) with method `GET`.
- Usernames MUST be joined to JSON stats via `md5(username) == usermd5`; the plaintext
  `name` field MUST be used directly when a build exposes it.
- Parsers MUST tolerate the documented build-specific shapes (list vs. wrapped object,
  single-object-as-array, alternate container keys, `name` vs `username`) and MUST skip
  `disabled == "1"` users.
- Rationale: WebIF responses vary by build; robustness here prevents silent data loss that
  would corrupt the strike engine.

### V. Least-Intrusive Mutation & Full Auditability

Stopping a user MUST change only that user's account block in `oscam.user` and apply the
change via reload, never a full restart. Every enforcement action MUST be audited.

- To stop: set `disabled = 1` in the target `[account]` block only; never touch
  `oscam.conf` / `oscam.server`. Apply live via `GET /userconfig.html?action=reinit`
  using the same auth as the stats calls.
- To re-enable: revert `disabled = 0`, reinit, and reset that user's `consecutive_strikes`
  to 0 and `status` to `ok`.
- Every stop/reinstate MUST record who, when, observed ECM/min, threshold, and strike count.
- Rationale: minimal, reversible, and logged mutations make false positives recoverable
  and every decision defensible.

## Security & Operational Constraints

- **Transport**: WebIF is plain **HTTP** by default; do NOT assume TLS. Use short
  connect/read timeouts (~5s).
- **Credentials**: WebIF user/pass MUST be stored securely (not world-readable) and SHOULD
  be encrypted at rest. Usernames MUST be masked in logs.
- **State persistence**: per-user strike state (`consecutive_strikes`,
  `last_observed_ecm_min`, `last_evaluated_at`, `status`, `exempt`) MUST persist across
  runs, keyed by username and per OSCAM instance, so "consecutive" is meaningful.
- **Poll cadence**: default ~5 minutes; the enforcement window scales with the interval
  (e.g. 3 strikes × 5 min ≈ 15 min of sustained abuse before a stop).
- **File access reality**: editing `oscam.user` requires file access to the hosting box;
  the file-edit-plus-`reinit` recipe is the portable, reference-matching mechanism.

## Development Workflow & Quality Gates

- Every feature plan MUST include a Constitution Check confirming Principles I–V are upheld,
  with any deviation justified in the plan's Complexity Tracking.
- The strike engine's three transitions (strike / reset / no-reading) MUST be covered by
  tests, including the "no reading is inert" case (Principle I).
- Changes to auth, JSON/HTML parsing, or the stop/reinit path MUST be reviewed against the
  build-tolerance and least-intrusive-mutation rules before merge.
- The tool MUST remain language-agnostic in method: the protocol behavior defined in
  `oscam-reshare-webif-method.md` is the source of truth, independent of implementation.

## Governance

- This constitution supersedes ad-hoc practices for this project. When a decision conflicts
  with a principle, the principle wins unless the constitution is formally amended.
- **Amendments** require: a documented change, a version bump per the policy below, and
  propagation to dependent templates (`plan`, `spec`, `tasks`, `checklist`).
- **Versioning policy** (semantic):
  - MAJOR — backward-incompatible removal or redefinition of a principle or governance rule.
  - MINOR — a new principle/section or materially expanded guidance.
  - PATCH — clarifications, wording, or non-semantic refinements.
- **Compliance review**: all plans and PRs MUST verify adherence to Principles I–V.
  Complexity or deviation MUST be explicitly justified; unjustified violations block merge.

**Version**: 1.0.0 | **Ratified**: 2026-07-02 | **Last Amended**: 2026-07-02
