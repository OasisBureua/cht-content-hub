# infra/modules/lambda/

Reusable Lambda module — handles function creation, IAM role, CloudWatch log group, environment variables, and SNS failure topic subscription. Inputs: handler path, memory, timeout, env vars, trigger config. Outputs: function ARN, log group name.
