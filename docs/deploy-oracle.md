# Deploying on Oracle Always Free with DuckDNS

The whole stack, permanently, for nothing: Oracle's Always Free tier is not a
trial, and DuckDNS gives you a hostname a certificate can be issued for.

[deploy.md](deploy.md) is the general guide. This is the same thing with every
Oracle-specific decision already made — including the two firewalls, which is
where most people lose an afternoon.

## 1. The server

Sign up at <https://cloud.oracle.com>. A card is required for identity checks;
Always Free resources do not draw on it.

Create a compute instance:

| Setting | Value |
|---|---|
| Image | **Ubuntu 24.04** (or 22.04) |
| Shape | **VM.Standard.A1.Flex** — 4 OCPU, 24 GB RAM |
| Boot volume | 50 GB is plenty; the free allowance is 200 GB total |
| SSH keys | Generate, and **save the private key** — it is shown once |

**If the shape says "out of capacity", that is normal.** The free ARM shape is
heavily oversubscribed in popular regions. Try a different availability domain,
try again over a few days, or pick a less busy home region. Do not fall back to
the AMD micro shape unless you have to — 1 GB RAM runs Postgres, Redis, two
workers and Caddy only with swap and a lot of squinting.

**Reserve the public IP.** Networking → the instance's VNIC → the public IP →
change from *ephemeral* to *reserved*. An ephemeral address changes when the
instance stops, and your certificate and DNS both point at it.

## 2. The two firewalls

This is the step everyone misses. Oracle blocks inbound traffic in **two**
independent places, and opening one does nothing on its own.

**Cloud level.** Networking → Virtual Cloud Networks → your VCN → Security
Lists → Default. Add two ingress rules:

| Source | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

**Operating system level.** Oracle's Ubuntu images ship with iptables rules
that reject everything except SSH, and there is a catch-all REJECT at the
bottom — so a rule appended to the end never matches. Insert, do not append:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
```

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
```

```bash
sudo netfilter-persistent save
```

If `curl` from your laptop still hangs after this, it is one of these two, not
the application. Check both before debugging anything else.

## 3. The hostname

At <https://www.duckdns.org>, sign in and create a subdomain — say
`stockwatch-api`. That gives you `stockwatch-api.duckdns.org`.

Put your instance's **reserved public IP** in the box and update. Confirm from
your laptop before going further, because a certificate cannot be issued until
this resolves:

```bash
nslookup stockwatch-api.duckdns.org
```

DuckDNS is on the Public Suffix List, so your subdomain gets its own
Let's Encrypt rate limit rather than sharing one with every other user.

The reserved IP means the address will not drift, so no update daemon is
needed. If you ever move the instance, change it in the DuckDNS box.

## 4. Install and run

SSH in (`ubuntu` is the default user on Ubuntu images):

```bash
ssh -i /path/to/your-key ubuntu@YOUR_PUBLIC_IP
```

Docker:

```bash
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER
```

Log out and back in so the group membership applies. Then:

```bash
git clone https://github.com/NekoTensor/stockwatch.git && cd stockwatch
```

```bash
cp .env.example .env && nano .env
```

The values that matter:

```bash
ENVIRONMENT=production
SECRET_KEY=            # see below
POSTGRES_PASSWORD=     # anything long; nothing else reads it
API_DOMAIN=stockwatch-api.duckdns.org
REQUIRE_EMAIL_VERIFICATION=true
RESEND_API_KEY=
EMAIL_FROM=StockWatch <alerts@yourdomain.com>
```

Generate the secret key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start everything:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Give Caddy a minute for the certificate, then from your **laptop**, not the
server:

```bash
curl https://stockwatch-api.duckdns.org/api/health
```

`{"status":"ok","environment":"production"}` means every layer worked — DNS,
both firewalls, TLS, and the API.

## 5. Point the extension at it

On your machine, not the server:

```bash
cd extension && STOCKWATCH_API_URL=https://stockwatch-api.duckdns.org/api npm run build:release
```

Load `extension/dist` unpacked and sign in. That is the whole system running
without your laptop involved — close it and the checks continue.

For the Web Store, zip the *contents* of `dist/` and follow
[store-listing.md](store-listing.md).

## 6. Before anyone else uses it

**Email.** Alerts only reach people with the browser closed by email. Verify a
domain in Resend, set `RESEND_API_KEY`, and note that `REQUIRE_EMAIL_VERIFICATION`
above depends on it — with no working email, nobody can verify and nobody can
track.

**Backups.** Nothing else is going to do this for you.

```bash
docker compose exec -T db pg_dump -U stockwatch stockwatch | gzip > ~/backup-$(date +%F).sql.gz
```

Put it in a daily `crontab -e` line, and restore one once to prove it works. A
backup nobody has restored is a hope, not a backup.

**The Discord bot**, if you want it — add `DISCORD_BOT_TOKEN` and:

```bash
docker compose --profile discord up -d bot
```

## Things that will go wrong

| Symptom | Cause |
|---|---|
| `curl` hangs from outside, works on the server | One of the two firewalls in step 2 |
| Caddy loops retrying the certificate | DNS not resolving to this box yet, or port 80 closed |
| API container restarts on boot | Read its logs — production refuses to start on an unset `SECRET_KEY`, on SQLite, or on a `.local` sender address, and says which |
| Everyone logged out after a restart | `SECRET_KEY` was left empty, so a new one is generated per process |
| Extension says it cannot reach the server | Built against the wrong address; the URL is baked in at build time |
