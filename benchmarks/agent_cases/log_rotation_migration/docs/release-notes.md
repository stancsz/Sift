# Release notes

## 2.4.0

Introduced `APP_LOG_*` names while keeping all five `LOG_*` variables working
for existing deployments. Canonical names take priority per setting when
both forms are set. Invalid explicit configuration now fails startup rather
than silently falling back. The migration command writes a deterministic
effective-settings JSON artifact for deployment review.
