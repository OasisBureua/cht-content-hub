# infra/modules/monitoring/cloudtrail/

Account-level CloudTrail. Reused from the existing CHT account-level setup if already in place; this module is a data source reference in that case. If CHT does not have an account-level trail, this module provisions one.
