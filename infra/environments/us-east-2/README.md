# infra/environments/us-east-2/

Disaster recovery region composition. Hosts:

- Aurora Global reader cluster (prod only)
- Route53 failover records (when configured)

No application compute deployed here under normal operation — purely a DR target for Aurora Global.
