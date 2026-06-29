# infra/modules/s3/

S3 bucket module. Standard ContentHub bucket with versioning, encryption (SSE-KMS), lifecycle policies, and signed-URL access. Inputs: bucket name, lifecycle config, public-read flag (almost always false). Outputs: bucket ARN.
