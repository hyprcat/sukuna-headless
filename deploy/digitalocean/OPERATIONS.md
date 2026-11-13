# DigitalOcean App Platform — Operations Guide

## First deploy

Prerequisites: `doctl` CLI authenticated, DigitalOcean Spaces bucket created, Dodo Payments products configured.

1. Edit `app.yaml`: set `github.repo` to your org/repo, set `region`.
2. Create the app:
   ```bash
   doctl apps create --spec deploy/digitalocean/app.yaml
   ```
3. Note the app ID from the output (or `doctl apps list`).
4. Set all `SECRET`-typed env vars in the DigitalOcean dashboard → App → Settings → each component's env vars. Required secrets:
   - `SECRET_KEY` — Django secret key (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
   - `ALLOWED_HOSTS` — JSON array, e.g. `["app.midsphere.ai"]`
   - `CORS_ALLOWED_ORIGINS` — JSON array, e.g. `["https://app.midsphere.ai"]`
   - `CSRF_TRUSTED_ORIGINS` — JSON array, e.g. `["https://app.midsphere.ai"]`
   - `SPACES_*` — bucket, region, endpoint, access key, secret key, CDN domain
   - `DODO_API_KEY`, `DODO_WEBHOOK_KEY`, `DODO_CREDIT_PRODUCT_IDS`, `DODO_CREDIT_ENTITLEMENT_ID`
   - `E2B_API_KEY`, `E2B_TEMPLATE_ID`
   - `MIDSPHERE_MANIFEST_KEY_ID`, `MIDSPHERE_MANIFEST_PRIVATE_KEY`
   - `MIDSPHERE_JWT_KEY_ID`, `MIDSPHERE_JWT_PRIVATE_KEY`
   - `FERNET_ENCRYPTION_KEY`
   - `SENTRY_DSN`, `POSTHOG_API_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT` (optional — leave blank to disable)
   - Frontend build-time: `PUBLIC_MS_SENTRY_DSN`, `PUBLIC_MS_POSTHOG_KEY`,
     `PUBLIC_ENVIRONMENT`, and `PUBLIC_RELEASE`
5. Trigger the first deploy. The `migrate` PRE_DEPLOY job runs migrations and collectstatic before the services start.

## Update and deploy

Push to `main` triggers auto-deploy (`deploy_on_push: true` on all components). To deploy a spec change:

```bash
doctl apps update <app-id> --spec deploy/digitalocean/app.yaml
```

To force a manual deploy without a code push:

```bash
doctl apps create-deployment <app-id> --force-rebuild
```

Deploy sequence (managed by App Platform):

1. **PRE_DEPLOY job (`migrate`)** — runs `manage.py migrate --noinput` then `manage.py collectstatic --noinput`. If this fails, the deploy is aborted and no traffic is shifted.
2. **Build** — backend, frontend, worker, beat images built from Dockerfiles.
3. **Rolling deployment** — new containers start, pass health checks, then old containers are drained.

## Rollback

App Platform keeps previous deployments. To rollback:

```bash
# List recent deployments
doctl apps list-deployments <app-id>
```

Rollback is available through the DigitalOcean dashboard or App Platform API.
From the dashboard: App → Activity → click **Rollback** beside the previous
deployment, review the diff, then confirm. Through the API, post the target
deployment ID to `/v2/apps/{app_id}/rollback`; `doctl apps create-deployment`
does not accept a rollback deployment ID flag.

Rollback does **not** reverse database migrations. If the current deploy included a migration, rolling back code may leave the database at a newer schema than the code expects. For safe rollback:

- Migrations are written to be forward-compatible (add nullable, backfill, then enforce) per backend coding standards.
- If a migration must be reversed: `doctl apps exec <app-id> --component migrate -- python manage.py migrate <app_label> <previous_migration_number>`.
- Never rollback past a destructive migration (column drop, table drop) without restoring from backup first.

## Health checks

Two endpoints, both in `config/views.py`:

| Endpoint       | Checks                              | Used for                                                                                                                                                                                                                                  |
| -------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /healthz` | Database `SELECT 1` + Redis set/get | Liveness probe. App Platform polls every 10s after 15s initial delay. Returns `{"status":"ok","checks":{"database":true,"cache":true}}` (200) or `{"status":"degraded",...}` (503). Three consecutive failures trigger container restart. |
| `GET /readyz`  | Database `SELECT 1` only            | Startup/readiness probe. Returns `{"status":"ready"}` (200) or `{"status":"not_ready"}` (503). Lighter check — no cache dependency.                                                                                                       |

The frontend has no custom health endpoint; App Platform uses the default TCP port check on 4321.

Workers and beat processes have no HTTP health checks (they are `workers`, not `services` in the app spec). Monitor their health via logs and Sentry error rate.

## Logs

```bash
# Tail live logs for a component
doctl apps logs <app-id> --component backend --follow
doctl apps logs <app-id> --component frontend --follow
doctl apps logs <app-id> --component worker --follow
doctl apps logs <app-id> --component beat --follow

# View PRE_DEPLOY job logs (most recent)
doctl apps logs <app-id> --component migrate --type=deploy
```

From the dashboard: App → Runtime Logs (per-component dropdown).

Backend emits structured JSON logs via structlog (workspace_id, request_id, run_id bound per request). Pipe to a log aggregator via App Platform's log forwarding (Settings → Log Forwarding → Papertrail, Datadog, Logtail, etc.).

Sentry captures exceptions across all backend components. PostHog captures domain events. OpenTelemetry exports traces to the configured OTLP endpoint.

## Secrets rotation

All secrets are `type: SECRET` in the app spec and set via the DigitalOcean dashboard. Rotation procedure:

**Django SECRET_KEY:**

1. Set the new key in the dashboard for backend, worker, beat, and migrate components.
2. Redeploy. Existing sessions are invalidated (users must re-login).

**DODO_API_KEY / DODO_WEBHOOK_KEY:**

1. Generate new keys in the Dodo Payments dashboard.
2. Update the env vars in DO dashboard for backend, worker, and beat.
3. Redeploy. Webhook signature verification uses the new key immediately.
4. Revoke the old key in the Dodo dashboard after confirming new deploys are healthy.

**SPACES_ACCESS_KEY / SPACES_SECRET_KEY:**

1. Create a new Spaces access key in the DO dashboard.
2. Update env vars for backend, worker, beat, and migrate.
3. Redeploy. Verify file uploads and static serving work.
4. Delete the old access key.

**E2B_API_KEY:**

1. Create the new E2B key in the E2B dashboard.
2. Update `E2B_API_KEY` for backend, worker, and beat.
3. Redeploy. Verify sandbox spawn/resume once the runtime integration is enabled.
4. Revoke the old key after the new deploy is healthy.

**Manifest/JWT Ed25519 keys:**

1. Generate a new Ed25519 private key and a new key ID.
2. Add the matching public key to the sandbox runtime configuration before
   deploying the backend change.
3. Update `MIDSPHERE_MANIFEST_*` or `MIDSPHERE_JWT_*` on backend, worker, and beat.
4. Redeploy, then remove the old public key only after all old runs and callback
   retries have aged out.

**FERNET_ENCRYPTION_KEY:**

Rotate only with a planned data migration or MultiFernet-style transition. This
key decrypts stored callback auth material; replacing it without re-encrypting
existing rows can make active runs unrecoverable.

**Sentry / PostHog / OTEL keys:** update in DO dashboard and redeploy. No overlap period needed — telemetry gaps during deploy are acceptable.

For all rotations: update the secret in every component that uses it. Backend, worker, beat, and migrate share the same secret set; frontend has its own. App Platform env vars are set per-component — there is no shared anchor like docker-compose's `x-backend-base`.

## Database backups

App Platform managed PostgreSQL includes automatic daily backups with 7-day retention. Access from the dashboard: Databases → your cluster → Backups.

To create an on-demand backup before a risky migration:

```bash
# Create a database fork (point-in-time copy)
doctl databases create <fork-name> --engine pg --version 16 --restore-from <db-cluster-id>
```

To restore from backup: create a new database cluster from a backup snapshot via the DigitalOcean dashboard (Databases → Backups → Restore), then update `DATABASE_URL` in the app env vars to point to the restored cluster.

For a SQL dump (useful for local debugging):

```bash
# Get connection string
doctl databases connection <db-cluster-id> --format URI

# Dump
pg_dump "<connection-uri>" --no-owner --no-acl > backup.sql
```

Redis data is ephemeral (cache + Celery broker). No backup needed — it repopulates on restart.

## Post-deploy smoke test

The smoke test script works against any backend/frontend URL pair:

```bash
# Against the live deployment
./scripts/smoke-test.sh \
  --backend-url https://app.midsphere.ai \
  --frontend-url https://app.midsphere.ai

# Against a specific non-production app
./scripts/smoke-test.sh \
  --backend-url https://<app-domain> \
  --frontend-url https://<app-domain>
```

The script runs 10+ checks: health endpoints, admin page, GraphQL introspection, auth endpoint, webhook endpoint, frontend pages. Exit code = number of failures (0 = all passed).

For a quick manual check after deploy:

```bash
# Health
curl -s https://app.midsphere.ai/healthz | python3 -m json.tool

# GraphQL schema is up
curl -s -X POST https://app.midsphere.ai/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { queryType { name } } }"}' | python3 -m json.tool

# Admin loads
curl -sI https://app.midsphere.ai/admin/login/ | head -5

# Frontend renders
curl -sI https://app.midsphere.ai/login | head -5
```

## Component summary

| Component | Type             | Instance        | Purpose                                                                              |
| --------- | ---------------- | --------------- | ------------------------------------------------------------------------------------ |
| backend   | service          | professional-xs | Django ASGI (Uvicorn) — GraphQL, admin, webhooks, health                             |
| frontend  | service          | basic-xxs       | Astro SSR (Node) — dashboard pages                                                   |
| worker    | worker           | basic-xxs       | `manage.py db_worker` — async task processing (billing sync, emails)                 |
| beat      | worker           | basic-xxs       | Celery beat + worker — periodic jobs (credit refresh, reconciliation, schedule tick) |
| migrate   | job (PRE_DEPLOY) | basic-xxs       | Migrations + collectstatic — runs once per deploy before traffic shift               |
| db        | database         | managed PG 16   | PostgreSQL — primary data store                                                      |
| cache     | database         | managed Redis 7 | Cache + Celery broker                                                                |
