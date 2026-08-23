# Deploying StockWatch

The extension cannot work from the Chrome Web Store until the backend is
reachable over https: an installed extension has no way to talk to a laptop,
and `npm run build:release` refuses to produce a build that tries.

This is the whole path from a domain to an extension that works for someone who
is not you.

Running it free on Oracle's Always Free tier with a DuckDNS hostname? Use
[deploy-oracle.md](deploy-oracle.md) instead — same steps, with every
Oracle-specific decision already made.

## What you need first

| | |
|---|---|
| A host | 2 vCPU / 4 GB is comfortable for the API, worker, Postgres and Redis together |
| A domain | An A record for `api.yourdomain.com` pointing at the host, before you start |
| Ports 80 and 443 | Open. Caddy needs 80 for the certificate challenge and the redirect |
| A Resend account | With that domain verified — see [Email](#email) |

## 1. Configure

```bash
git clone https://github.com/NekoTensor/stockwatch.git && cd stockwatch
cp .env.example .env
```

Edit `.env`. The values that matter in production:

```bash
ENVIRONMENT=production
SECRET_KEY=          # python -c "import secrets; print(secrets.token_urlsafe(48))"
POSTGRES_PASSWORD=   # not the default
API_DOMAIN=api.yourdomain.com
RESEND_API_KEY=
EMAIL_FROM=StockWatch <alerts@yourdomain.com>
```

`ENVIRONMENT=production` makes the API check itself on the way up and refuse to
start on an unset `SECRET_KEY` (a generated one logs everybody out on every
restart), `DEBUG=true`, SQLite, or a sender address it knows will bounce. Read
the logs of a failed start before changing anything — it lists every problem it
found, not just the first.

## 2. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The overlay keeps Postgres and Redis off the public interface, puts Caddy in
front for TLS, and moves rate-limit counters into Redis so that the two uvicorn
workers share one allowance rather than one each. Migrations run in the API
container before it serves.

Give Caddy a minute for the certificate, then:

```bash
curl https://api.yourdomain.com/api/health
```

## 3. Build the extension against it

```bash
cd extension
STOCKWATCH_API_URL=https://api.yourdomain.com/api npm run build:release
```

The address is baked into the bundle and the manifest's host permissions are
derived from it, so there is no second place to update and no way for the two to
disagree. `dist/` is what you zip for the Web Store — see
[store-listing.md](store-listing.md), which also covers the test account a
reviewer needs before they can see the extension do anything.

## Email

Alerts reach people who are not sitting in front of Chrome only by email, so
this is not optional in the way it looks.

1. Add your domain in Resend and publish the DNS records it gives you.
2. Put the API key in `RESEND_API_KEY`. That alone turns sending on.
3. Set `EMAIL_FROM` to an address at the verified domain.

A sending domain with no history is a sending domain nobody trusts. Expect the
first few days of alerts to land in spam, and keep the volume low while it
settles.

## Operating it

**Logs.** `docker compose logs -f api worker` — the worker is where a store
blocking you shows up first.

**Backups.** Everything a user would be upset to lose is in Postgres: accounts,
what they track, and the price history that makes the verdicts mean anything.

```bash
docker compose exec -T db pg_dump -U stockwatch stockwatch | gzip > backup-$(date +%F).sql.gz
```

**Scaling.** The worker is the part that runs out first, and the limit is
politeness rather than CPU: `PER_HOST_DELAY_SECONDS` serialises requests to each
store across every user, so more concurrency past a point buys nothing. When
checks start falling behind their schedule, that throttle — not the container —
is what to look at.

**Upgrading.**

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations run on the way up. Take a dump first.

## Somewhere other than one host

Any platform that runs containers works; StockWatch is three processes and two
datastores, and only the first one takes traffic:

| Process | Command |
|---|---|
| API | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` |
| Worker | `celery -A app.worker.celery_app worker --loglevel=info --concurrency=4` |
| Scheduler | `celery -A app.worker.celery_app beat --loglevel=info` |

Add managed Postgres and Redis, set the same environment variables, and set
`TRUST_PROXY_HEADERS=true` and `RATE_LIMIT_STORAGE_URI` to the Redis URL — the
platform's router is a proxy, and rate limits that live in one instance's memory
are not limits once there are two instances.

Run exactly one scheduler. Two will queue every check twice, which doubles the
requests each store sees from you.
