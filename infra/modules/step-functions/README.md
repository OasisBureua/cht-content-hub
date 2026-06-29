# infra/modules/step-functions/

Step Function state machine module.

## Inputs

- State machine name (`cht-content-hub-{domain}-{purpose}`)
- ASL definition file path (loaded from `services/step_functions/<name>/definition.asl.json`)
- Type: `STANDARD` (default; long-running, auditable) or `EXPRESS` (high-volume short workflows)
- IAM execution role permissions (typically: invoke specific Lambdas + write to SQS)
- CloudWatch log group + retention

## Outputs

- State machine ARN
- Execution role ARN

## Notes

- Step Functions only for genuinely multi-step orchestration. Simple cron jobs use EventBridge → Lambda direct.
- Initial state machines arrive with post-R1 HCP Intel and video pipeline work.
