# Feature Specification: Ubuntu 18.04 Installer (No Reshare Link)

**Feature Branch**: `006-ubuntu1804-installer`

**Created**: 2026-10-01

**Status**: Draft

**Input**: User description: "The current installer can set up the WireGuard VPN link and only supports newer Ubuntu releases. Build a second, separate installer that supports Ubuntu 18.04 only and has no WireGuard/VPN step. Do not touch or modify the existing installer; code may be copied from it."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Install the panel on an Ubuntu 18.04 VPS (Priority: P1)

An operator has an OSCam box running Ubuntu 18.04. Today the only installer refuses
this release. The operator runs the new 18.04 installer with one command and ends up
with the same reshare-control panel and periodic poller that newer boxes get, minus the
VPN reshare link.

**Why this priority**: This is the whole point of the feature: 18.04 boxes currently
cannot run the panel at all.

**Independent Test**: On a clean Ubuntu 18.04 VPS, run the new installer. The panel
answers on its port, the admin can log in with the printed password, and the poller
runs on schedule.

**Acceptance Scenarios**:

1. **Given** a clean Ubuntu 18.04 system with root access and internet, **When** the
   operator runs the 18.04 installer, **Then** it installs the runtime the panel needs,
   installs the panel and poller, starts them, and prints the panel URL, the user
   `admin`, and a password.
2. **Given** the install finished, **When** the box reboots, **Then** the panel and the
   poller schedule come back on their own.
3. **Given** the install finished, **When** the operator inspects the system, **Then**
   no VPN/WireGuard software was installed, no VPN interface or key exists, and no
   enrollment request was made to the fleet.

---

### User Story 2 - Refuse every system that is not Ubuntu 18.04 (Priority: P1)

An operator runs the 18.04 installer on the wrong system (Ubuntu 20.04+, Debian,
another distribution). The installer stops before changing anything and tells them
which installer to use instead.

**Why this priority**: Running the no-VPN installer on a newer box would silently give
it a lesser install than the standard installer; running it on an unknown system could
break it. Both must be impossible by mistake.

**Independent Test**: Run the installer with OS identification set to Ubuntu 20.04,
22.04, Debian 11, and an unknown distribution. Each run exits with an error, names the
standard install command for supported newer systems, and leaves no files behind.

**Acceptance Scenarios**:

1. **Given** Ubuntu 20.04 or newer, **When** the 18.04 installer runs, **Then** it
   refuses and prints the standard install command.
2. **Given** Debian or any non-Ubuntu system, **When** the 18.04 installer runs,
   **Then** it refuses with an "unsupported system" message.
3. **Given** Ubuntu 16.04 or older, **When** the 18.04 installer runs, **Then** it
   refuses and says only Ubuntu 18.04 is supported.
4. **Given** any refusal, **When** the operator checks the disk, **Then** no
   configuration, service, schedule, or package was added.

---

### User Story 3 - Re-run safely on an already-installed 18.04 box (Priority: P2)

An operator re-runs the 18.04 installer to update or repair an existing install. Their
instances, users, settings, and admin password survive; the services are refreshed.

**Why this priority**: Operators re-run installers to update; losing configuration
would be costly, but this is secondary to the first install working.

**Independent Test**: Install, change the admin password and add an instance, re-run
the installer, confirm the settings and password are unchanged and services restarted.

**Acceptance Scenarios**:

1. **Given** an existing install with configuration, **When** the installer re-runs,
   **Then** the existing configuration and admin password are kept and the output says
   the existing password is in the config file.
2. **Given** an existing install whose configuration has the VPN link turned on (e.g.
   copied from another box), **When** the 18.04 installer runs, **Then** it does not
   install or start any VPN component.

---

### Edge Cases

- The extra runtime package cannot be installed (no internet, broken package sources,
  the needed package source disabled): the installer stops with a clear message naming
  what failed and does not leave half-written services pointing at a missing runtime.
- The system default runtime is older than the panel needs: the panel and poller must
  never be started with it; they always run with the runtime the installer provided.
- A host firewall is already active: the panel port is opened; no VPN ports are opened;
  the firewall is never switched on by the installer.
- No systemd (container): the poller falls back to a cron schedule, as in the standard
  installer.
- Run without root: the installer stops with a clear message before changing anything.
- Operator overrides the source location or config directory through the same
  environment variables the standard installer accepts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST be delivered as a new, separate installer file. The
  existing installer file MUST remain byte-for-byte unchanged.
- **FR-002**: The new installer MUST proceed only on Ubuntu 18.04 and MUST refuse every
  other OS or release before making any change to the system.
- **FR-003**: When refusing Ubuntu 20.04 or newer, the installer MUST print the standard
  install command; for all other refusals it MUST state that only Ubuntu 18.04 is
  supported.
- **FR-004**: The installer MUST require root and refuse otherwise, before any change.
- **FR-005**: The installer MUST ensure a runtime version the panel supports is present,
  installing it from the operating system's standard package sources if missing.
- **FR-006**: The panel service and the poller schedule MUST run with that supported
  runtime, never with the older system default.
- **FR-007**: The installer MUST NOT install VPN software, create VPN keys or
  interfaces, or contact the fleet enrollment service, regardless of environment
  variables or existing configuration.
- **FR-008**: The installer MUST install and start the same panel and poller as the
  standard installer (same configuration location, same service names, same schedule
  rules, same admin credential handling).
- **FR-009**: The installer MUST preserve an existing configuration and admin password
  on re-run.
- **FR-010**: If a host firewall is already active, the installer MUST open only the
  panel port and MUST NOT open VPN ports or enable a firewall.
- **FR-011**: The installer MUST end by printing the panel URL, the admin user name, and
  either the generated password or where the existing one is stored.
- **FR-012**: The installer MUST fall back to a cron schedule when systemd is not
  available.
- **FR-013**: If installing the runtime fails, the installer MUST stop with a message
  naming the failure and MUST NOT install services.

### Key Entities

- **18.04 installer**: the new standalone script; its only inputs are the OS
  identification, optional environment overrides, and the app source.
- **Panel configuration**: the existing configuration file shared with the standard
  installer (same location and format); this feature reads and creates it but adds no
  new fields.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean Ubuntu 18.04 VPS, one command produces a reachable, loggable-in
  panel within 5 minutes on a normal connection.
- **SC-002**: 100% of runs on a non-18.04 system end in a refusal with zero files,
  services, schedules, or packages added.
- **SC-003**: 0 VPN components (packages, keys, interfaces, enrollment requests) after
  any run of the 18.04 installer.
- **SC-004**: The standard installer's content is identical before and after this
  feature (verifiable by checksum).
- **SC-005**: A re-run keeps 100% of existing instances, settings, and the admin
  password.

## Assumptions

- The panel's supported runtime (Python 3.8) is available in Ubuntu 18.04's standard
  package sources (bionic-updates, universe component), so no third-party source is
  needed.
- The application code itself is not changed for this feature; it already runs on the
  runtime the installer provides.
- The new installer fetches the same public application source as the standard
  installer by default, so 18.04 boxes run the same panel version.
- Features that depend on the VPN reshare link (fleet enrollment, agent API over the
  link) are simply not available on 18.04 boxes; the panel works without them.
- Debian releases that also ship an old runtime are out of scope (only Ubuntu 18.04 was
  requested).
