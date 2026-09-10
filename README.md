# TeamPulse

See your team's operational health at a glance — on-call burden, deploy risk, and
incident trends — without stitching together PagerDuty, GitHub, and spreadsheets
yourself.

## Running it locally

```bash
cp .env.example .env
```

Fill in `SECRET_KEY` and `CREDENTIALS_ENCRYPTION_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then:

```bash
docker compose up
```

- API — http://localhost:8001 (docs at `/docs`)
- Web — http://localhost:5173
- Postgres — host port **5433** (5432 inside the compose network)

Ports 5433 and 8001 are used on the host to avoid colliding with other local
services. Change them in `docker-compose.yml` if you prefer the defaults.

### Demo data

There are no PagerDuty or GitHub accounts required to see the product working.
The mock providers generate 90 days of realistic incidents, on-call shifts and
deploys, and run through the *same* mappers and persistence path as the live
integrations:

```bash
docker compose exec api python -m app.seed
```

Sign in as `admin@example.com` / `teampulse-demo-2026`.

## How it fits together

```
PagerDuty / GitHub ─┐
                    ├─> normalized shapes ─> Postgres ─> metric rollups ─> API ─> React
mock fixtures ──────┘   (integrations/base)   (events)    (metrics/)
```

**Integrations** (`app/integrations/`) — each provider implements `IncidentSource`
or `DeploySource` from `base.py` and normalizes into provider-neutral dataclasses.
Adding Opsgenie or GitLab means writing one adapter; nothing downstream changes.
Credentials are Fernet-encrypted at rest.

**Team attribution** — `team_resources` maps PagerDuty services/schedules and
GitHub repos to teams. Every incident, shift and deploy inherits its team through
that table, so team metrics are exactly as good as that mapping.
`external_identities` does the same for people, auto-linking provider users to
org users by email and leaving unmatched ones claimable in settings.

**Metrics** (`app/metrics/`) — `compute.py` is pure math: it takes plain values
and returns plain values, no database and no clock. That is what makes it
testable, and these are the numbers customers make staffing decisions on.
`rollups.py` loads events and writes `metric_rollups`.

**Jobs** (`app/jobs/`) — a Postgres queue using `SELECT … FOR UPDATE SKIP LOCKED`.
No Redis. The worker also schedules recurring work; the dedupe key is a time
bucket so running several workers still produces one job per bucket.

## Two things worth knowing about the numbers

**After-hours is evaluated in the paged person's local timezone** (user → team →
org fallback). A 03:00 page in Lagos is after-hours even if it is mid-afternoon
at head office. Rollup buckets are UTC days; the bucket is *when* it happened,
the classification is *what it cost them*.

**A rate over a window is computed from the events in that window, never by
averaging daily rates.** Averaging lets a quiet day weigh as much as a brutal
one — which is how the same person once read 33% on one screen and 64% on
another. `MetricRollup` rows still back the charts; totals are recomputed.

## Tuning the toil score

`backend/metrics.yaml` holds the working-hours definition, the change-failure
window, and the score weights. Each component is normalized 0-100 between a
`good` and a `bad` value and combined by weight. Components with no data are
renormalized out, so a team with no GitHub connection still gets a meaningful
on-call score rather than one dragged toward zero.

Edit the file and restart — no code changes.

## Tests

```bash
cd backend && pytest
```

Coverage is concentrated on the metric calculations and the provider mappers,
per the brief. Everything under test is pure, so the suite runs in well under a
second and needs no database.

## What is deliberately not here

Custom alerting, static analysis, providers beyond PagerDuty and GitHub, SSO,
mobile, and billing. `organizations.plan` exists as a stub; there is no Stripe.

## Not yet done

- The OAuth flow for GitHub is written but unverified — it needs a real OAuth app.
  The PAT path (`POST /api/integrations/github`) is the tested one.
- User invites set an initial password directly; replace with an invite-token
  flow once email delivery is configured.
- Row-level security is not enabled. Tenant isolation is enforced by `org_id`
  filters at the repository layer.
