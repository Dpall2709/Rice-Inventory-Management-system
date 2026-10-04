# Where to host the database and the app

*Written 27 September 2026. Prices are approximate — check current rates before committing,
and note they change often.*

Your users are rice traders in India, mostly Bihar. Two things follow from that: the server
should be **in an India region**, and the monthly bill must stay small until the
subscriptions cover it.

---

## 1. Keep the current database design

One PostgreSQL database, every row tagged with `company_id` — what the project already does
— is the right choice. Do **not** move to "one schema per customer" or "one database per
customer":

| | Shared database (current) | Schema / DB per tenant |
|---|---|---|
| Cost at 100 customers | one small database | 100 schemas to migrate, much bigger server |
| `migrate` | runs once | runs 100 times, and can half-fail |
| Cross-customer reports (your revenue) | one query | 100 queries |
| Risk | one forgotten `company` filter | isolated by design |

That single risk is exactly what `core/tenancy.py` now handles. Shared-database is how
almost every small SaaS runs, and it is the cheapest by a wide margin.

---

## 2. Recommended setup: one VPS in India

App and database on the same small server, in Mumbai or Bangalore.

```
        Internet
           │  HTTPS (free certificate, auto-renewed)
        ┌──▼──────────────────────────────┐
        │  One VPS, 2 vCPU / 4 GB, Mumbai │
        │                                 │
        │  Caddy  ── reverse proxy + TLS  │
        │    │                            │
        │  gunicorn (3 workers) ─ Django  │
        │    │                            │
        │  PostgreSQL 16 (Docker volume)  │
        │    │                            │
        │  nightly pg_dump ──────────────►│──► Cloudflare R2 / Backblaze B2
        └─────────────────────────────────┘        (off-server backup)
```

**Why the same server:** a database call takes under a millisecond over a loopback
connection. Split the app and database across providers and every page becomes slower —
Django makes many small queries per page.

**Providers** (all have an India region): DigitalOcean Bangalore, AWS Lightsail Mumbai,
Hostinger VPS, E2E Networks (Indian company, rupee billing), Azure/GCP Mumbai. Hetzner is
the cheapest in the world but has **no** India region — skip it for this product.

### Rough monthly cost

| Customers | Server | Backups | Domain | Total |
|---|---|---|---|---|
| 1–30 | 2 vCPU / 4 GB — ~₹700–1,000 | ~₹50 | ~₹100 | **≈ ₹900–1,200** |
| 30–100 | 4 vCPU / 8 GB — ~₹1,500–2,200 | ~₹80 | ~₹100 | **≈ ₹1,700–2,400** |
| 100–400 | 8 vCPU / 16 GB, or split the DB out | ~₹150 | ~₹100 | **≈ ₹3,500–5,000** |

At ₹499/month per customer, **three paying customers cover the first tier**. Data volume is
tiny — a busy rice trader writes a few thousand rows a month, so 100 customers is still
only a few hundred MB. You are paying for CPU and RAM, not storage.

---

## 3. The managed alternative

If you would rather not patch a server, use a managed database and a managed app host:

| Service | Free tier | Paid from | India region | Notes |
|---|---|---|---|---|
| **Neon** | yes, generous | ~$19/mo | Singapore (no India) | Postgres that scales to zero; +40–60ms latency from India |
| **Supabase** | yes, but **pauses when idle** | ~$25/mo | Mumbai available | Free tier pausing is unacceptable for paying customers |
| **DigitalOcean Managed PG** | no | ~$15/mo | Bangalore | Simple, same provider as the app |
| **AWS RDS** | 12-month trial | ~$15–30/mo | Mumbai | Most work to set up |
| **Render / Railway** (app) | limited | ~$7–20/mo | Singapore | Easy deploys, no India region |

**My recommendation:** start on the single VPS. Move the database to DigitalOcean Managed
PostgreSQL (Bangalore) when either of these becomes true:

- losing a day of customer data would end your business (managed gives point-in-time restore), or
- you no longer want to be the person who patches PostgreSQL.

Whatever you pick, set `DB_SSL=True` in `.env` for any managed database — the traffic then
leaves your server encrypted.

---

## 4. Backups — the part people skip

A subscription product that loses a customer's ledger is finished. Minimum:

```bash
# /etc/cron.daily/rice-backup  (runs at 2am)
docker exec rice-postgres pg_dump -U postgres rice_trading_db \
  | gzip > /tmp/rice-$(date +%F).sql.gz

# copy off the server (rclone works with R2, B2, S3, Drive)
rclone copy /tmp/rice-$(date +%F).sql.gz remote:rice-backups/
find /tmp -name 'rice-*.sql.gz' -mtime +7 -delete
```

Rules worth following:

1. **Off the server.** A backup on the same disk is not a backup.
2. **Keep 30 daily + 12 monthly.** Storage is pennies; a customer reporting "these entries
   vanished last month" is not.
3. **Test a restore once a month.** An untested backup is a guess.
4. Also back up `media/` (company logos) — or move uploads to R2/S3 later.

---

## 5. Server security checklist

- PostgreSQL must **not** listen on a public port. With Docker, publish it as
  `-p 127.0.0.1:5432:5432`, not `-p 5432:5432` as on your development machine.
- Firewall: allow only 22, 80 and 443.
- SSH keys only, root login disabled, plus fail2ban.
- `DEBUG=False`, real `ALLOWED_HOSTS`, a fresh `SECRET_KEY` — see the README.
- Unattended security upgrades on.
- Rotate the Supabase password that is still in this repository's git history.

---

## 6. When the mobile app arrives

It changes nothing here. The app will talk to the **same** Django server over the DRF API
(Phase 4) and the same database. What matters:

- **Region still matters most** — a phone on 4G in Bihar already pays 50–80ms; do not add
  a Singapore hop on top.
- **JWT tokens** (`djangorestframework-simplejwt`, already installed) instead of session
  cookies for the app.
- Serve static and media through a CDN (Cloudflare's free plan) once images are involved —
  it keeps mobile data usage and your bandwidth bill down.
- The same `for_company()` scoping must be applied to every API view. A leaky API is worse
  than a leaky page, because it returns clean JSON.

---

## 7. Moving your local data to the server

```bash
# on your Mac
docker exec rice-postgres pg_dump -U postgres rice_trading_db | gzip > rice.sql.gz
scp rice.sql.gz user@your-server:/tmp/

# on the server
gunzip -c /tmp/rice.sql.gz | docker exec -i rice-postgres psql -U postgres rice_trading_db
python manage.py migrate      # safe to run again
python manage.py seed_plans
```

---

## 8. Summary

| Question | Answer |
|---|---|
| Database design? | Keep one shared PostgreSQL with `company_id` |
| Where? | One VPS in Mumbai or Bangalore, app + database together |
| Cost to start? | About ₹1,000/month — two paying customers |
| Managed database? | Later: DigitalOcean Bangalore, when backups or patching become a worry |
| Backups? | Nightly `pg_dump` to Cloudflare R2 or Backblaze B2, restore-tested monthly |
| Avoid? | Supabase free tier in production (it pauses), and any US/EU-only region |
