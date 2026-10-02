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

## Scan a supplier's bill (Purchases → 📷 Scan bill)

Instead of typing a mill's bill, take a photo of it (or upload its PDF):

- **QR code** — a GST e-invoice QR gives the supplier GSTIN, bill number, date and total.
  It is found automatically in the photo, or scanned with the camera, or typed by a
  handheld scanner. This works offline and costs nothing, but the QR never contains the rice lines.
- **Photo / PDF** — Claude reads the whole bill: supplier, every rice line (bags, bag
  weight, rate per kg, GST), discount, freight and labour. Rates per quintal or per bag
  are converted to per kg. Switch it on by adding your key to `.env`:

  ```
  ANTHROPIC_API_KEY=sk-ant-...
  ```

  Each bill costs roughly ₹1–3 (model `claude-opus-5-5`; change with `BILL_SCAN_MODEL`).
  The bill image is sent to Anthropic's API to be read.

The supplier is matched by GSTIN or name (a new one is added in one tap), the rice by name.
The normal purchase form opens pre-filled and shows the bill's total next to the form's
total. Nothing is saved until you press Save. The original bill file is attached to the
purchase and only opens for your own company. The camera needs HTTPS (or localhost); on a
phone over plain HTTP, use "take a photo" instead.

## English / हिन्दी

Every screen can be switched between English and Hindi with the **EN / हिं** button in the
top bar (and on the login page). The choice is remembered in a cookie for a year.

The Hindi text lives in `locale/hi/LC_MESSAGES/django.po`. After adding or changing any
on-screen text:

```bash
python manage.py makemessages -l hi --ignore=venv --ignore=staticfiles   # collect new text
# translate the new empty msgstr "" entries in django.po
python manage.py compilemessages -l hi --ignore=venv                      # build django.mo
```

`compilemessages` needs GNU gettext (`brew install gettext` on macOS,
`apt install gettext` on Linux). The compiled `django.mo` is committed, so a server only
needs it when the text changes.

## Run the tests

```bash
python manage.py test
```

The tests cover the rules that must never break: company data isolation, subscription
expiry and read-only mode, role permissions, per-company invoice numbering, purchase GST
maths, stock checks on every sale, customer and broker ledgers, and the language switch.

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
