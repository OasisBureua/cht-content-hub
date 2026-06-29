# infra/modules/cognito/

Cognito user pool module. Single pool with unified groups (superadmins, admins, editors, hcps, kols). Configures app client, hosted UI, identity providers. Inputs: callback URLs, allowed scopes. Outputs: pool ID, app client ID, JWKS URL.
