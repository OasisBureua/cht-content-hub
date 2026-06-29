# services/shared/auth/

Cognito JWT validation and RBAC.

## User pool

Single shared pool across Content Hub (covers both `cht-content-hub-api` and `cht-platform-backend`). Same session JWT validates on both services.

## Groups

| Group | Access |
|---|---|
| `chm-admin` | Full platform + studio. Replaces legacy `superadmin` and `admin`. |
| `chm-editor` | Studio only, scoped by `client_ids` claim. Replaces legacy `editor`. |
| `chm-viewer` | Read-only studio. Replaces legacy `viewer`. |

End users (HCPs, KOLs) authenticate via the consumer app's session cookie; they do not appear in any of the above groups. Their permissions are inferred from the absence of group membership + `client_ids` scoping.

## Implementation

- JWKS fetched and cached at startup with periodic refresh
- Validates RS256 JWTs against the Cognito user pool issuer
- Extracts group claims and `client_ids` for RBAC
- Helper decorators for FastAPI route protection and Lambda handler authorization

## Replaces

MediaHub's `services/auth_service.py` (GoTrue HS256) is retired. End-user authentication on the legacy MediaHub UI is blocked per Phase 0.4 of the migration plan.
