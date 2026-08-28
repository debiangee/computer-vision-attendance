# Pilot RBAC and Scope Design

## Status

**Local engineering controls:** implemented and covered by signed-session scope tests.

**Pilot identity/role authority:** pending approval. In pilot mode, signed claims must be issued by the approved identity provider or identity gateway; local database role rows are not treated as an authenticated authority.

**Pilot gate:** open until Security, the RBAC owner, and the business owner approve the identity-to-role mapping, site assignments, subject assignments, and separation-of-duties account model.

## Role matrix

| Role | Allowed operations | Explicit restrictions |
|---|---|---|
| Kiosk service | Append a recognition interaction/event | No administration, browsing, export, templates, policy changes, or role management |
| Enrollment administrator | Create/enroll, suspend, reset, rotate, and de-enroll assigned subjects | No unrestricted event correction/export or RBAC management |
| Attendance administrator | View and correct assigned-site/subject events; approved export | No template access, enrollment, or RBAC management |
| Auditor | Read approved event and audit data | No mutation, enrollment, correction, or role management |
| System operator | Device health, deployment, and queue operations | No routine biometric/template access or attendance correction |
| RBAC administrator | Manage approved role assignments and access scope | Separate account from routine enrollment/correction work |

The existing permission mapping remains default-deny. Signed session roles must also pass the separation-of-duties policy. The local pilot policy rejects these combinations:

- enrollment administrator + attendance administrator;
- RBAC administrator + enrollment administrator;
- RBAC administrator + attendance administrator;
- RBAC administrator + system operator.

The pilot owner may approve a stricter policy, but must not silently weaken these combinations without a documented review.

## Scope claims

Signed admin sessions require:

- `sites`: one or more approved site identifiers, or `*` only when the RBAC owner explicitly approves global scope;
- `subjects`: one or more approved subject identifiers, or `*` only when the enrollment/correction owner explicitly approves all-subject scope.

Kiosk sessions require a site scope and the `kiosk-service` role. The kiosk does not receive administrative subject scope and cannot access admin routes.

The API enforces scope at the server boundary:

- every signed request must include the configured local site in its site scope;
- user listing is filtered to the subject scope;
- enrollment, status changes, demo enrollment/reset, template registration, and role assignment reject subjects outside scope;
- event listing and export filter by site and subject scope;
- corrections load only events in scope and reject changes that would move an event outside scope;
- cross-site and cross-subject requests return a generic `403` without revealing whether the resource exists.

Legacy static-token mode remains unrestricted for the supervised demo/tests only and must not be used for the pilot.

## Separation of duties

The pilot identity owner must create distinct named accounts for at least:

1. RBAC administration;
2. enrollment administration;
3. attendance correction/export;
4. auditing;
5. system operations;
6. kiosk service operation.

Shared administrator accounts are not acceptable for the pilot because they prevent individual attribution and revocation.

## Authorization and audit requirements

- Every denied scope or permission decision returns a bounded generic response.
- Sensitive mutations require recent signed authentication as defined in `docs/pilot-authentication-design.md`.
- Enrollment, de-enrollment, reset, role assignment, correction, export, revocation, and authorization failures are audited.
- Audit records must not contain credentials, frames, crops, template vectors, or unnecessary personal data.
- Role and scope changes require an approved owner and an auditable change record.

## External approval/deployment requirements

The implementation cannot determine these decisions:

- approved IdP and token issuer;
- role-to-group mapping;
- site and subject assignment source;
- global-scope approval process;
- separation-of-duties exceptions;
- administrator lifecycle and offboarding;
- access-review frequency;
- emergency access and break-glass process;
- audit review and alert ownership.

These must be completed and signed by the RBAC, Security, business, and site owners before participant enrollment.

## Evidence

Local evidence includes:

- signed session claims for roles, site scope, and subject scope;
- default-deny token-kind and permission checks;
- cross-subject denial;
- cross-site denial;
- conflicting-role denial;
- filtered user/event query paths;
- correction scope enforcement;
- bounded denial audit behavior.

Pilot evidence still required:

- approved identity-provider configuration;
- role/scope access matrix;
- named-account review;
- offboarding/revocation rehearsal;
- periodic access-review record;
- trusted issuer/key and TLS deployment evidence.

## Decision

**P0-03 engineering controls:** prepared.

**P0-03 pilot gate:** OPEN until the approved identity provider, role/scope mapping, named-account separation, access review, and operational revocation process are deployed and signed off.
