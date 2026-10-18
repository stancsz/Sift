# Stratus Cloud — Internal IAM Policy Notes
#
# Effective-date semantics: a section is "in force" when its effective
# date pre-dates the request's effective date AND no later section
# explicitly supersedes it. Conflict resolution: a later section that
# *narrows* an earlier rule does NOT remove the earlier constraint on
# unrelated subjects or resources.

## §1 Baseline read-only access
Effective: 2024-01-15
All engineers in the analytics org may `s3:GetObject` on
`arn:aws:s3:::analytics-prod/*` and `arn:aws:s3:::logs-archive/*`,
and may `kms:Decrypt` the analytics KMS key.

## §2 Restriction on direct production database access
Effective: 2024-09-01
No engineer role shall hold `dynamodb:Query` on tables whose name
contains `prod` in the `sessions` family, nor `rds:DescribeDBInstances`
on the production RDS cluster `prod-cluster`. Analytics access to those
data stores must flow through the warehouse (Redshift).
Note: this restriction is NOT superseded by §4.

## §3 S3 PII bucket policy
Effective: 2025-06-10
`s3:GetObject` on `arn:aws:s3:::user-uploads/*` is denied by default.
A request from HR (alice.chen is HR-only by group, not engineering) is
NOT sufficient. This section remains in force.

## §4 Expanded analytics scope (later, narrower rule)
Effective: 2026-05-01
Senior data engineers may read `arn:aws:s3:::analytics-prod/*` and
`arn:aws:s3:::logs-archive/*` and may `kms:Decrypt` the analytics key,
subject to §1. This section narrows §1 to a specific job family; it
does NOT modify the §2 production-database restriction and does NOT
relax the §3 S3 PII bucket policy.

## §5 Break-glass procedure
Effective: 2023-11-01
Break-glass roles are issued for incident response only and are not
considered normal usage evidence for least-privilege reviews.
