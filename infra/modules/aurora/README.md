# infra/modules/aurora/

Aurora Global cluster module. Handles primary cluster + reader cluster in second region, parameter groups, subnet groups, security groups, secrets in Secrets Manager. Inputs: cluster size, regions, retention. Outputs: cluster endpoint, reader endpoint, secret ARN.
