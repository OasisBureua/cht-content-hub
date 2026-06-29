# infra/modules/cognito/

Cognito user pool module — shared identity across `cht-content-hub-api` and `cht-platform-backend`.

## Inputs

- Pool name (`cht-content-hub-users`)
- App client configuration (callback URLs, allowed scopes)
- Identity providers (email/password initially; federation later)
- MFA policy (required for `chm-admin`, optional for `chm-editor` / `chm-viewer`)

## Outputs

- Pool ID
- App client ID(s)
- JWKS URL

## Groups

The module pre-creates three groups:

- `chm-admin` — full platform + studio
- `chm-editor` — studio only, scoped by `client_ids` claim
- `chm-viewer` — read-only studio

End users (HCPs, KOLs) are pool members without group membership; their access is gated by `client_ids` claim scoping.

## Notes

- Single pool spans both products. Same session JWT validates on both `cht-content-hub-api` and `cht-platform-backend`.
- The Cognito pool is shared infrastructure across both services. If provisioned externally rather than from this repo's Terraform, this module is replaced by a data source reference.
