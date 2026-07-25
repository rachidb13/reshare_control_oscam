# Feature Specification: Web Multi-Instance Control

**Feature Branch**: `002-web-multi-instance-control`

## User Story

An operator installs the tool on a client VPS with one copy-paste command. After installation, the
script prints a browser URL plus generated admin credentials. In the browser, the operator adds one
or more OSCam instances running on that VPS by entering WebIF connection details and the local OSCam
config path that contains `oscam.user`.

## Requirements

- The installer MUST create a protected web admin account and print the URL, username, and generated
  password.
- The web interface MUST require authentication before showing or changing OSCam data.
- The web interface MUST allow adding multiple OSCam instances with WebIF host/port/credentials,
  local config path, ECM/min threshold, strike count, poll interval, auto-stop setting, and exempt
  users.
- Scheduled monitoring MUST run all configured OSCam instances.
- Per-instance state and audit records MUST be stored separately.
- Existing single-instance config files MUST continue to load through migration.

## Acceptance Checks

- Browser request without credentials returns `401`.
- Browser request with valid credentials renders the dashboard.
- Adding an OSCam instance through the form persists it to config.
- `run-all` runs each configured instance independently.
- Existing unit and integration tests continue passing.
