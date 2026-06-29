# services/shared/auth/

Cognito JWT validation and RBAC.

- JWKS fetched and cached at startup with periodic refresh
- Validates RS256 JWTs against the Cognito user pool
- Extracts group claims (`superadmins`, `admins`, `editors`, `hcps`, `kols`)
- Helper decorators for FastAPI route protection and Lambda handler authorization
