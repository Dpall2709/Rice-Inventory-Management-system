# 🌾 Rice Billing App — multi-company billing & ledger SaaS

A Django billing and ledger system for rice trading businesses: purchases from mills,
GST sale invoices, stock, ledgers and payments — sold to many businesses at once on a
subscription.

- **Architecture guide:** [notes/PROJECT_ARCHITECTURE.md](notes/PROJECT_ARCHITECTURE.md)
- **What changed in the SaaS work:** [notes/SAAS_PHASE1_2.md](notes/SAAS_PHASE1_2.md)
- **Where to host it:** [notes/HOSTING.md](notes/HOSTING.md)

---

## Run it locally (macOS / Linux)

You need Python 3.12+ and PostgreSQL. If you have Docker, the database is one command.

```bash
# 1. Database (Docker). Skip if you already run PostgreSQL locally.
docker run -d --name rice-postgres \
  -e POSTGRES_PASSWORD='Admin@123' -e POSTGRES_DB=rice_trading_db \
  -p 5432:5432 -v rice_pgdata:/var/lib/postgresql/data postgres:16

# 2. Python environment
python3 -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env
# Then edit .env: set DEBUG=True, DB_PASSWORD, and a SECRET_KEY. Generate one with:
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

# 4. Database tables and subscription plans
python manage.py migrate
python manage.py seed_plans

# 5. Start
python manage.py runserver
```

Open http://127.0.0.1:8000/ and register a company at `/register/` — it starts on a
14-day free trial.

To reach the staff screens (`/billing/manage/` and `/admin/`), create yourself an account:

```bash
python manage.py createsuperuser
```

## Run the tests

```bash
python manage.py test
```

23 tests cover the rules that must never break: company data isolation, subscription
expiry and read-only mode, role permissions, and per-company invoice numbering.

---

## How the SaaS side works

| Thing | Where |
|---|---|
| Free trial length | `TRIAL_DAYS` in `.env` (default 14) |
| Plans and prices | `python manage.py seed_plans`, then Django admin → Plans |
| A company's subscription | Django admin → Subscriptions, or `/billing/manage/` |
| Expired company | Read-only: every page opens, nothing saves, renew banner shown |
| Online payment | Razorpay. Add `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` to `.env` |
| Offline payment | Leave Razorpay keys empty, then extend by hand from `/billing/manage/` |
| Razorpay webhook URL | `https://yourdomain.com/billing/webhook/razorpay/` |

Roles, set per user in Django admin → User profiles:

| Role | Can do |
|---|---|
| `owner` | everything, including billing and deleting |
| `manager` | add, edit and delete records; no billing |
| `staff` | add and view records only |

---

## Going to production

Never run with `DEBUG=True` in production. With `DEBUG=False`, HTTPS redirects, secure
cookies, HSTS and clickjacking protection switch on automatically — so the server needs
a real certificate (Caddy or nginx does this for free).

Required in `.env` on the server:

```
DEBUG=False
SECRET_KEY=<a fresh random key>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
DB_PASSWORD=<strong password>
DB_SSL=True            # if the database is managed (Supabase, Neon, RDS)
EMAIL_HOST=...         # so password reset emails actually send
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Then:

```bash
python manage.py migrate
python manage.py collectstatic
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

See [notes/HOSTING.md](notes/HOSTING.md) for the server, database and backup plan.

---

## Tech stack

Python 3.12+ · Django 6.0.1 · PostgreSQL · ReportLab (PDF invoices) · openpyxl (Excel) ·
qrcode · Razorpay · plain HTML/CSS/JS (no frontend framework)
