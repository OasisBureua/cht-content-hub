# infra/modules/security/kms/

KMS encryption keys for `cht-content-hub-*` resources.

- One CMK per environment for service-side encryption of RDS, S3, SQS, Secrets Manager.
- Key alias pattern: `alias/cht-content-hub-{env}-{purpose}`.
