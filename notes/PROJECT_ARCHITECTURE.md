# Rice Inventory Management System — Full Architecture Guide

*Last updated: 27 September 2026. Written for anyone who opens this codebase for the first time.*

> Companion documents: [SAAS_PHASE1_2.md](SAAS_PHASE1_2.md) lists what the Phase 1 + 2 SaaS
> work changed, and [HOSTING.md](HOSTING.md) covers where to run the database and app.

---

## 1. What this project is, in plain words

This is a **billing and ledger system for a rice trading business**.

The business buys rice from **mills** (suppliers) in bags, keeps it as stock, then sells it to
**customers** by truck. Sometimes a **broker** brings the customer. Money does not come or go
all at once, so the app also has to remember **who owes how much**.

The software answers five daily questions for the owner:

| Question | Where the app answers it |
|---|---|
| What did I buy, and from which mill? | Purchases |
| How much money do I still owe each mill? | Mill Report (ledger) |
| What did I sell, and to whom? | Sales |
| How much money do customers still owe me? | Sales list (Paid / Partial / Due) |
| How many bags of each rice do I have left? | Product Report (current stock) |
| Did I make profit on that truck? | Sale Detail (buy cost vs sell price) |

It is built as a **multi-company (multi-tenant) app**: many rice businesses can use one
installation, and each one only sees its own data. That is the foundation for selling it as a
subscription product.

---

## 2. Technology used, and why

| Layer | Technology | What it does here |
|---|---|---|
| Language | Python 3.12+ | Everything on the server |
| Web framework | Django 6.0.1 | URLs, database, login, HTML templates |
| Database | PostgreSQL 16 | Stores all data (a Docker container locally) |
| DB driver | psycopg2-binary | Lets Python talk to PostgreSQL |
| HTML | Django Templates | The pages the user sees |
| CSS / JS | One plain `style.css` + one `script.js` | Styling and the add-row buttons in forms. No React, no Bootstrap, no jQuery |
| PDF | ReportLab | Draws the GST sale invoice, and the mill report PDF |
| QR code | qrcode | Puts a QR code on the invoice |
| Excel | openpyxl | Mill report `.xlsx` download |
| Amount in words | num2words | "Rupees One Thousand Only" on the invoice |
| Config | python-dotenv, python-decouple | Reads the `.env` file |
| Payments | razorpay | Subscription payments (UPI, cards, netbanking) |
| Installed but unused | djangorestframework, simplejwt, PyJWT | No API yet; needed for the mobile app in Phase 4 |

There is **no REST API and no JavaScript framework**. Every page is rendered on the server and
sent as finished HTML. This is the simplest possible Django design, which is good for
maintenance but means the whole UI reloads on every click.

---

## 3. The big picture — what happens on one click

```
   Browser  (user clicks "Mills")
      |
      |  GET /mills/
      v
   config/urls.py            <- the front door of the whole project
      |  sends everything except /admin/ to core
      v
   core/urls.py              <- the road map: which URL runs which function
      |
      v
   MIDDLEWARE (config/settings.py)
      |  1. security, sessions, CSRF
      |  2. AuthenticationMiddleware  -> puts request.user in place
      |  3. core.middleware.CompanyMiddleware -> puts request.company in place
      v
   VIEW FUNCTION  (core/views.py, or core/view/..., or core/function/...)
      |  a) find out which company the logged-in user belongs to
      |  b) ask the database ONLY for that company's rows
      |  c) calculate totals, balances, dues in Python
      v
   TEMPLATE  (core/templates/core/mill_list.html)
      |  fills the values into HTML, wrapped in base.html
      v
   Browser shows the page
```

The important idea: **the view function is where all the thinking happens**. Models only store
data, templates only display it, and there is no service layer in between (except one small
file for registration).

---

## 4. Folder structure — every file explained

```
Rice-Inventory-Management-system/
│
├── manage.py                  Django's command tool (runserver, migrate, shell)
├── requirements.txt           Python package list (saved as UTF-16 — see §12)
├── .env.example               Sample environment file (contains real Supabase keys — see §12)
├── .gitignore
├── README.md                  Short setup steps (written for Windows)
├── notes/                     <- this document
│
├── config/                    THE PROJECT (settings, not business logic)
│   ├── settings.py            Database, installed apps, middleware, company/bank constants
│   ├── urls.py                Top-level URLs: /admin/ and everything else -> core
│   ├── wsgi.py / asgi.py      Entry points for a real production server
│
├── billing/                   THE SUBSCRIPTION APP (how you get paid)
│   ├── models.py              Plan, Subscription, SubscriptionPayment
│   ├── services.py            trial, activation, Razorpay order/verify/webhook
│   ├── middleware.py          expiry -> read-only mode
│   ├── views.py               tenant billing pages + your staff screens
│   ├── urls.py                /billing/...
│   ├── admin.py
│   ├── templates/billing/     home, checkout, manage_companies
│   └── management/commands/seed_plans.py
│
└── core/                      THE RICE BUSINESS APP
    ├── models.py              11 database tables (§6)
    ├── tenancy.py             company scoping helpers - USE THESE (§5)
    ├── permissions.py         role rules: owner / manager / staff
    ├── views.py               1525 lines — most of the app lives here (§7)
    ├── urls.py                All routes
    ├── forms.py               Registration form, Company form, Customer form
    ├── admin.py               Registers all models in Django admin (plain, no customisation)
    ├── middleware.py          CompanyMiddleware — finds the logged-in user's company
    ├── tests.py               23 tests: isolation, subscription, roles, invoice numbers
    │
    ├── migrations/            Database change history
    │   ├── 0001_initial.py    Created all main tables
    │   └── 0002_customer.py   Added the Customer table later
    │
    ├── view/                  A NEWER, tidier way of organising views (one file per screen)
    │   ├── __init__.py        Re-exports the functions so urls.py can do `view.add_mill`
    │   ├── base_imports.py    One file of shared imports (`from .base_imports import *`)
    │   ├── dashboard.py       Dashboard (renders a static page)
    │   ├── auth/              login_view, logout_view, register_view
    │   ├── mill/              add_mill, mill_list, edit_mill, delete_mill
    │   └── customer/          customer_view.py — all 4 customer screens
    │
    ├── function/              Big single-purpose logic files
    │   ├── add_sale.py        The whole sale-entry brain (§8.6)
    │   └── sale_invoice_pdf.py Draws the GST invoice PDF
    │
    ├── services/
    │   ├── registration_service.py  Creates Company + User + UserProfile + free trial
    │   └── invoice_number.py        Per-company, race-safe invoice numbers
    │
    ├── templates/core/        HTML pages (base.html + one per screen)
    │   └── auth/              password reset screens
    └── static/core/           style.css and script.js
```

### Why the same view exists in two places

The project is **mid-refactor**. The author started with everything in `views.py`, then began
moving screens into small files under `core/view/`. Both copies still exist:

| Screen | Old copy | New copy | Which one actually runs |
|---|---|---|---|
| Dashboard | `views.py:35` | `view/dashboard.py` | **new** (`view.dashboard`) |
| Mills (4 screens) | `views.py:423-541` | `view/mill/*.py` | **new** (`view.add_mill` etc.) |
| Add purchase | `views.py:39` | `view/product/add_purchase.py` | **old** (`views.add_purchase`) |
| Login / logout | `views.py` | `view/auth/*.py` | **old** (`views.login_view`) |
| Register | *(old copy deleted)* | `view/auth/register_view.py` | **new** |

`core/urls.py` mixes both: it imports `views` **and** `view`, and picks one per line. When you
change something, always check `core/urls.py` first to see which file is live, or you will edit
code that never runs.

---

## 5. The multi-tenant design (the "company" idea) — most important section

This is the heart of the product. One installation serves many rice businesses.

```
        Company  "Sanjana Rice Mill"            Company  "Bihar Rice Traders"
             |                                        |
      UserProfile(role=owner) -- User "ayush"   UserProfile -- User "raj"
             |                                        |
   mills, products, purchases,              mills, products, purchases,
   sales, brokers, customers, payments      sales, brokers, customers, payments
   (every row carries company_id = 1)       (every row carries company_id = 2)
```

**How separation works, step by step:**

1. A `User` (Django's built-in login table) is linked to exactly one `Company` through
   `UserProfile` (one-to-one with User, foreign key to Company).
2. Every business table — Mill, Product, Purchase, Sale, Broker, Payment, Customer — has a
   `company` foreign key.
3. `core/middleware.py` runs on every request and sets `request.company` and
   `request.user_profile` from the logged-in user's profile.
4. Each view then filters by company, for example:

```python
company = request.user.userprofile.company              # who am I?
mills = Mill.objects.filter(company=company)            # only my mills
mill = get_object_or_404(Mill, id=mill_id, company=company)   # and only my mill by id
```

The `company=company` part in `get_object_or_404` is what stops company A from opening company
B's record by typing a different id in the URL.

**Always use the helpers in `core/tenancy.py` for new code:**

```python
from core.tenancy import company_of, tenant_object_or_404

company = company_of(request)                            # from the middleware, no extra query
mill    = tenant_object_or_404(Mill, request, mill_id)   # 404 if it belongs to someone else
mills   = Mill.objects.for_company(company)              # only this company's rows
```

`for_company()` works on child tables too: `PurchaseItem` and `SaleItem` have no company
column of their own, so they declare `company_path = "purchase__company"` /
`"sale__company"` and the manager follows the link.

Older views still fetch the company with `request.user.userprofile.company` directly, which
works but costs one extra query. The filtering is still written per query — nothing in the
database forces it — so a query written without `for_company()` is how the next leak would
happen. Two such leaks existed and are fixed; see [SAAS_PHASE1_2.md](SAAS_PHASE1_2.md).

---

## 6. The database — all 10 tables

### Relationship map

```
              Company  (the tenant / one rice business)
                 |
  +--------------+--------------+----------------+-------------+-----------+
  |              |              |                |             |           |
UserProfile   Mill           Product          Broker       Customer     Payment
  |            |                |                |                         |
 User       Purchase            |                |                         |
            (invoice header)    |                |                         |
                 |              |                |                         |
            PurchaseItem -------+                |                         |
            (one rice line)                      |                         |
                                                 |                         |
                                 Sale  <---------+  (broker, optional)     |
                                (truck invoice header) <-------------------+
                                   |                     (payments point to
                              SaleItem                    a sale, a purchase,
                        (internal buy breakup)             or a mill)
```

### Table by table

**Company** — the tenant. Name, owner, email, mobile, GST number, PAN, address, logo, and
the legacy subscription mirror (`subscription_start`, `subscription_end`, `is_active`).
It also carries the tenant's **invoice identity**, used when printing bills:
`invoice_prefix`, `bank_account_name`, `bank_account_no`, `bank_name`, `bank_ifsc`,
`bank_branch`, `upi_id`, `invoice_terms`.

**InvoiceSequence** — one counter row per company per day, so each company gets its own
gap-free invoice series even when two users save at the same moment.

**Plan / Subscription / SubscriptionPayment** (in the `billing` app) — what you sell, who is
paying for it until when, and every payment attempt. See
[SAAS_PHASE1_2.md](SAAS_PHASE1_2.md) §6.

**UserProfile** — connects a `User` to a `Company`, plus `role` ("owner" / "manager" / "staff"),
`phone`, `designation`, `is_active`.

**Mill** — a supplier. `mill_name`, `mobile`, `address`, `gst_number`, and `opening_balance`
(money already owed to this mill before you started using the software).

**Product** — a type of rice. `rice_name`, `hsn_code` (GST product code), `gst_percent`,
`is_active`.

**Customer** — a buyer, with billing/shipping address, GST number, `opening_balance`. Added
last (migration 0002) and **not yet connected to sales** — see §12.

**Broker** — a middleman who brings customers. Same shape as Mill.

**Purchase** — one purchase invoice from one mill: `mill`, `invoice_no`, `purchase_date`,
`total_amount` (calculated and saved by the view).

**PurchaseItem** — one rice line inside that purchase: `product`, `bag_weight` (20 or 30 kg),
`bag_count`, `purchase_price` (rate per kg). *This row is also the stock lot* — when you sell,
you point at the PurchaseItem you are selling from.

**Sale** — one truck invoice. It holds a lot:
- customer: `customer_name`, `customer_gst` (plain text, not a link to Customer)
- `broker` (optional), `sale_date`
- truck details: `vehicle_number`, `driver_name`, `transporter_name`
- transport money, kept **separate** from rice money: `transport_rate_per_ton`,
  `transport_charge`, `transport_paid_by_dealer`, `transport_paid_by_customer`
- rice money: `total_quantity_kg`, `taxable_amount`, `gst_percent`, `gst_amount`,
  `total_amount`, `advance_received`, `balance_amount`
- `invoice_no` — auto-generated, unique across the whole database

**SaleItem** — the **internal breakup**: which purchase lots this truck was filled from. Holds
`mill`, `product`, `bag_weight`, `bag_count`, and the **buying** rate/amount
(`rate_per_kg`, `amount`). This is the owner's private cost data — the customer's invoice never
shows it. Comparing Sale totals (selling) with SaleItem totals (buying) gives the profit.

**Payment** — one money movement, used for both directions. `related_type` is either
`"sale"` (money received from a customer) or `"purchase"` (money paid to a mill), plus
`amount`, `payment_mode`, `payment_date`, `notes`, and a link to the relevant `sale`,
`purchase` or `mill`.

### How stock is calculated — there is no stock table

Stock is never stored. It is **counted on demand** (`views.py:613` product_report):

```
current stock of a rice = SUM(PurchaseItem.bag_count)  -  SUM(SaleItem.bag_count)
                          (bought bags)                   (sold bags)
```

Consequences you must know:
- Stock is always "live", never wrong because of a forgotten update. Good.
- It is counted in **bags only, mixing 20 kg and 30 kg bags together**, so the number is not a
  true weight.
- There is **no check before selling**. Nothing stops a sale of 500 bags when only 100 were
  bought; stock simply goes negative.
- There is no warehouse/godown, no damage/return entry, and no opening stock.

---

## 7. URL map — every screen in the app

| URL | Runs | Template | What the user does |
|---|---|---|---|
| `/` | `view.dashboard` | dashboard.html | Home page (static links only) |
| `/register/` | `view.register_view` | register.html | A new company signs up |
| `/login/` `/logout/` | `views.login_view` / `logout_view` | login.html | Sign in / out |
| `/mills/` | `view.mill_list` | mill_list.html | List + search mills |
| `/add_mill/` | `view.add_mill` | add_mill.html | Add a supplier |
| `/mills/edit/<id>/` `/mills/delete/<id>/` | `view.*` | edit_mill / delete_mill | Change, remove |
| `/mills/report/<id>/` | `views.mill_report_detail` | mill_report_detail.html | **Supplier ledger** |
| `/mills/<id>/export/excel/` | `views.mill_report_excel` | → .xlsx file | Download ledger |
| `/mills/<id>/export/pdf/` | `views.mill_report_pdf` | → .pdf file | Print ledger |
| `/payment/mill/add/<id>/` | `views.add_mill_payment` | add_mill_payment.html | Pay a mill |
| `/products/` `/products/add/` `/products/edit/<id>/` `/products/delete/<id>/` | `views.*` | product_*.html | Rice types |
| `/products/report/<id>/` | `views.product_report` | product_report.html | **Current stock** |
| `/purchase/add/` | `views.add_purchase` | add_purchase.html | Enter a purchase bill |
| `/purchase/list/` `/purchase/<id>/` | `views.*` | purchase_list / purchase_detail | See purchases |
| `/purchase/edit/<id>/` `/purchase/delete/<id>/` | `views.*` | edit / delete | Fix a purchase |
| `/payment/purchase/add/<id>/` | `views.add_purchase_payment` | add_purchase_payment.html | Pay one bill |
| `/sales/` | `views.sale_list` | sale_list.html | Sales + Paid/Partial/Due |
| `/sales/add/` | `function.add_sale` | add_sale.html | **Create a sale (§8.6)** |
| `/billing/` | `billing.home` | billing/home.html | Subscription status + plans |
| `/billing/checkout/<code>/` | `billing.checkout` | billing/checkout.html | Pay for a plan (owner only) |
| `/billing/webhook/razorpay/` | `billing.razorpay_webhook` | — | Razorpay confirms payment |
| `/billing/manage/` | `billing.manage_companies` | billing/manage_companies.html | **Staff only:** all companies |
| `/password-reset/` | Django auth views | core/auth/*.html | Forgot password flow |
| `/sales/<id>/` | `views.sale_detail` | sale_detail.html | Sale + cost + profit |
| `/sales/<id>/print/` | `views.sale_print` | sale_print.html | Printable HTML bill |
| `/sales/<id>/invoice.pdf` | `function.sale_invoice_pdf` | → .pdf file | **GST invoice PDF** |
| `/sales/<id>/payment/add/` | `views.add_sale_payment` | add_sale_payment.html | Receive money |
| `/brokers/` `/brokers/add/` | `views.*` | broker_*.html | Brokers |
| `/brokers/report/<id>/` | `views.broker_report_detail` | broker_report_detail.html | Broker's sales |
| `/customers/` `/customers/add/` `/customers/edit/<id>/` `/customers/delete/<id>/` | `view.customer_*` | customer_*.html | Customer master |
| `/admin/` | Django admin | — | Raw table access for you, the developer |

---

## 8. How each feature works, step by step

### 8.1 Company registration

`/register/` → `core/view/auth/register_view.py` → form `CompanyRegistrationForm`
(`core/forms.py`) → service `core/services/registration_service.py`.

The form checks: company name not already taken, username free, email free, both passwords
match, and password strength (Django's `validate_password`). Then the service creates **three
rows together**: `Company`, `User` (password hashed by `create_user`), and `UserProfile` with
`role="owner"`. Finally it redirects to the login page.

Note: subscription dates are **hardcoded** in the service:

```python
subscription_start="2026-01-01",
subscription_end="2036-01-01",
```

So anyone who signs up gets a free 10-year subscription. This is the single biggest thing to
change before selling the product.

### 8.2 Login

`views.login_view` does four checks in order: username/password correct → a `UserProfile`
exists → `profile.is_active` is true → `profile.company.is_active` is true. Then
`login(request, user)` and redirect to the dashboard. **`subscription_end` is never checked**,
so an expired company can still log in and work normally.

### 8.3 Masters: Mills, Products, Brokers, Customers

All four follow the same simple pattern: list (with a search box) → add → edit → delete.
Mills, Products and Brokers are written the plain way (read `request.POST.get(...)` by hand).
Customers are the only module written the **proper Django way**, using a `ModelForm`
(`CustomerForm`) and a soft delete (`is_active = False` instead of removing the row). New code
should follow the Customer module's style.

### 8.4 Purchase entry (`views.add_purchase`)

The form has one header (mill, invoice no, date) and many rice rows added by JavaScript
(`product[]`, `bag_weight[]`, `bag_count[]`, `purchase_price[]` arrays).

```
for each row:  line_total = bag_count × bag_weight × rate_per_kg
purchase.total_amount = sum of all line totals
```

The whole save runs inside `transaction.atomic()`, so a half-saved purchase is impossible. The
chosen mill and each product are re-checked with `company=company`, so a tampered form cannot
attach another company's mill. **This view is the best-written code in the project — copy its
style.**

### 8.5 Mill ledger (`views.mill_report_detail`)

This is the "how much do I owe this supplier" screen.

```
balance = mill.opening_balance + SUM(all purchases) - SUM(all payments of type "purchase")
```

Per invoice it also shows total bags, total kg, average rate per kg
(`total_amount ÷ total_kg`), amount paid against that invoice, and the due (never shown below
zero). The same numbers are re-created in `mill_report_excel` (openpyxl) and
`mill_report_pdf` (ReportLab) — the logic is **copy-pasted three times**, so a formula change
must be made in three places.

### 8.6 Sale entry — the most complex part (`core/function/add_sale.py`, 954 lines)

A sale has two sides, and this is the key business idea of the whole app:

| Side | What it is | Shown to customer? | Stored in |
|---|---|---|---|
| **Selling side** | total kg, rate, GST, transport, advance | Yes, on the invoice | `Sale` header |
| **Buying side ("breakup")** | which mill/lot each bag came from, and its cost | **Never** | `SaleItem` rows |

The flow uses the **session as a draft**, so nothing is lost if the page reloads:

```
GET /sales/add/
   loads this company's products, mills, brokers, and purchase lots
   (purchase lots are also passed to the page as JSON for the dropdowns)
   restores any earlier draft from request.session["sale_draft"]
        |
POST /sales/add/  with step=save
   1. save everything into session ("sale_draft" + "sale_draft_lists")
   2. VALIDATE:
        - breakup rows must exist
        - bags in the breakup must equal total bags of the sale
          ("Breakup must match total bags (12 != 15)")
        - number of lot ids must match number of bag counts
   3. calculate: taxable amount, GST, transport charge, balance
   4. inside one transaction:
        - generate invoice no  SAL-YYYYMMDD-0001
        - create Sale
        - create one SaleItem per breakup row, with the BUY rate from its PurchaseItem
   5. clear the session draft
        |
   redirect to the sale list
```

There is also an older **two-step path** (`/sales/review/` → `/sales/confirm-save/` in
`views.py`, rendering `sale_review.html`). The "Review" button is **commented out** in
`add_sale.html:122`, so today the app saves in one step and the review code is dead weight.

Invoice numbers come from `core/services/invoice_number.py`. Each company has its own
counter row (`InvoiceSequence`), locked with `select_for_update()` while the next number is
handed out, so numbers never repeat and never skip:

```
Demo Rice Co     SAL-20260927-0001, SAL-20260927-0002, ...
Bihar Traders    BRT-20260927-0001, ...      (its own series and its own prefix)
```

### 8.7 Sale detail and profit (`views.sale_detail`)

```
rice_total        = taxable_amount + gst_amount
rice_received     = advance_received + SUM(payments of type "sale")
rice_due          = rice_total - rice_received          (floored at 0)
transport_due     = transport_charge - (paid_by_dealer + paid_by_customer)
buy_cost_total    = SUM(SaleItem.amount)
profit_estimate   = rice_total - buy_cost_total
```

Note that `profit_estimate` compares a GST-inclusive selling total against a GST-free buying
cost, so the profit shown is **too high by the GST amount**. Worth fixing before customers rely
on it.

### 8.8 The GST invoice PDF (`core/function/sale_invoice_pdf.py`)

Drawn line by line with ReportLab `canvas` (absolute x/y positions in millimetres) — not an
HTML-to-PDF conversion. It prints the seller block, buyer block, truck details, rice lines,
GST, transport, bank details, a QR code, the amount in words (`num2words`), and a signature
area.

The seller name, address, GSTIN and bank details come from the logged-in user's own
`Company` row, so every tenant prints its own invoice. The `COMPANY_*` and `BANK_*`
constants in `config/settings.py` are only a fallback for a field the tenant has left
blank — so ask each customer to fill in their details (Django admin → Companies).

---

## 9. Frontend

- `core/templates/core/base.html` — the shell: page title, link to `style.css`, the top
  navigation (Dashboard, Mills, Products, Add Purchase, Sales, Brokers, Customers, Logout),
  the Django messages area, and `{% block content %}`. Two nav links are still `href="#"`
  placeholders.
- Every other template `{% extends "core/base.html" %}` and fills that block.
- `static/core/style.css` — all styling, written by hand (cards, tables, buttons, badges).
- `static/core/script.js` — small helpers, mainly "add another row" in the purchase and sale
  forms.
- There is **no mobile-first layout**, no dark mode and no component library. On a phone the
  wide tables will scroll sideways.
- `dashboard.html` is **static**: it contains no numbers from the database, only links. The
  natural next step is to show today's sales, cash in/out, stock alerts and total dues there.

---

## 10. Configuration and environment

`config/settings.py` holds:

- `SECRET_KEY` and `DEBUG` read from the environment (`os.getenv`), with unsafe defaults.
- `ALLOWED_HOSTS = []` — empty, so `runserver` refuses to start unless `DEBUG=True`.
- `DATABASES` — read entirely from `.env` (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`,
  `DB_PORT`, plus `DB_SSL=True` for managed databases). No password lives in the code.
- `DEBUG=False` automatically switches on HTTPS redirect, secure cookies, HSTS, nosniff and
  `X-Frame-Options: DENY`, and the app refuses to start without a real `SECRET_KEY`.
- Subscription settings: `TRIAL_DAYS`, `SUBSCRIPTION_WARN_DAYS`, the `RAZORPAY_*` keys, and
  the `EMAIL_*` block for password resets.
- The `COMPANY_*` and `BANK_*` constants used by the PDF (§8.8).
- `LOGIN_URL = 'login'`, `LOGIN_REDIRECT_URL = 'dashboard'`, `LOGOUT_REDIRECT_URL = 'login'`.
- `STATICFILES_DIRS` only includes the project `static/` folder if it actually exists, so
  the old startup warning is gone. `MEDIA_ROOT` holds uploaded company logos.

**Local setup (what is actually running on this machine):** PostgreSQL 16 in a Docker container
named `rice-postgres` (data in the Docker volume `rice_pgdata`), a `venv/` with Python 3.12,
and a `.env` containing `DEBUG=True`. To start: `docker start rice-postgres`, then
`source venv/bin/activate`, then `python manage.py runserver`.

---

## 11. Where to make which change (quick map for future work)

| You want to change... | Open this |
|---|---|
| A database field | `core/models.py`, then `makemigrations` + `migrate` |
| A URL | `core/urls.py` (check whether the line uses `views.` or `view.`) |
| Purchase logic | `core/views.py:38-131` |
| Sale logic | `core/function/add_sale.py` |
| The invoice PDF layout | `core/function/sale_invoice_pdf.py` |
| Mill ledger numbers | `core/views.py:678-822` **and** the Excel copy (917) **and** the PDF copy (988) |
| Signup / subscription dates | `core/services/registration_service.py` |
| Login rules | `core/views.py:2144` |
| Navigation menu | `core/templates/core/base.html` |
| Styling | `core/static/core/style.css` |

---

## 12. Known gaps and rough edges (honest list)

Phase 1 + 2 (September 2026) fixed the security, tenancy and subscription items. What
follows is what is still true today. The full before/after list is in
[SAAS_PHASE1_2.md](SAAS_PHASE1_2.md).

**Fixed** — tenant data leaks in the Excel/PDF exports and the sale-entry lookups; secrets
in code; the invoice printing the wrong company; globally shared invoice numbers; unused
roles; no subscription enforcement; the 10-year free signup; no password reset; 680 lines of
dead code; zero tests.

**Business logic still incomplete**

1. The `Customer` table is not connected to `Sale` — sales still store the customer as free
   text, so there is no customer ledger, receivables or aging report.
2. Stock is never validated: nothing stops selling more bags than were bought, and stock can
   go negative.
3. Stock counts bags without distinguishing 20 kg from 30 kg, so the figure is not a weight.
4. `profit_estimate` in `sale_detail` compares a GST-inclusive selling total against a
   GST-free buying cost, so the profit shown is too high by the GST amount.
5. The dashboard is still a static page with no numbers on it.
6. No GST return report (GSTR-1 / HSN summary), no day book, no expenses, and broker
   commission is not calculated.
7. `Plan.max_users` is stored but never enforced.
8. No email verification at signup — any email address can be used.
9. No subscription reminder emails yet (the data is there; a daily command is needed).

**Code health**

10. Duplicate view code still exists in `core/views.py` and `core/view/` — check
    `core/urls.py` to see which copy is live before editing.
11. Mill ledger maths is copy-pasted three times (HTML view, Excel export, PDF export), so a
    formula change must be made in three places.
12. `core/views.py` is still 1,525 lines holding ~28 screens.
13. No audit log (who created or changed a record) and no soft delete except for customers.
14. The Django admin shows all companies' data to any staff user — fine while only you have
    access, a problem if a customer is ever given admin rights.
15. The old `.env.example` in git history still contains a real Supabase host and password.
    **Change that password in Supabase** — deleting the file does not clean history.

## 13. Glossary of business words used in the code

| Word | Meaning |
|---|---|
| Mill | The supplier who mills and sells rice to this business |
| Broker | Middleman who brings a customer; may earn commission (not yet calculated) |
| Bag weight | Size of one bag, 20 kg or 30 kg |
| Bag count | Number of bags in a line |
| Breakup | The internal record of which purchase lots filled one truck (`SaleItem`) |
| Opening balance | Money already owed, before the software was started |
| Transport charge | Truck fare, tracked separately from the rice amount |
| Due | Money still not received (sales) or not paid (purchases) |
| HSN code | GST product classification code, printed on the invoice |
| Taxable amount | Rice value before GST |
