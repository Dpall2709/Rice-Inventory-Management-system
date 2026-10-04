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
    │   ├── customer/          customer_view.py — customer screens + the customer ledger
    │   ├── sale/              sale_views.py — sale list, entry, invoice page, receipts
    │   └── broker/            broker_views.py — broker list, form, ledger, commission paid
    │
    ├── function/
    │   └── sale_invoice_pdf.py Builds the GST invoice PDF (§8.8)
    │
    ├── services/
    │   ├── registration_service.py  Creates Company + User + UserProfile + free trial
    │   ├── invoice_number.py        Per-company, race-safe invoice numbers
    │   ├── sale_service.py          Sale totals, stock per lot, FIFO allocation, profit
    │   └── customer_ledger.py       Customer and broker ledgers
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

**Customer** — a buyer, with billing/shipping address, state, GST number, `opening_balance`.
Every sale points at one (`Sale.customer`), which gives each buyer a ledger (§8.7).

**Broker** — a middleman who brings customers. Holds his usual commission
(`commission_type`: ₹ per bag / ₹ per quintal / % of sale value, and `commission_rate`),
an `opening_balance` of commission already owed, and `is_active` (deactivated, never deleted).

**Purchase** — one purchase invoice from one mill: `mill`, `invoice_no`, `purchase_date`,
`total_amount` (calculated and saved by the view).

**PurchaseItem** — one rice line inside that purchase: `product`, `bag_weight` (20 or 30 kg),
`bag_count`, `purchase_price` (rate per kg). *This row is also the stock lot* — when you sell,
you point at the PurchaseItem you are selling from.

**Sale** — one invoice (usually one truck). It holds:
- `customer` (link) plus a **snapshot** of the buyer as it was that day: `customer_name`,
  `customer_gst`, `billing_address`, `shipping_address`, `place_of_supply` — so editing the
  customer later never rewrites an invoice already given
- `broker` (optional) with this sale's `broker_commission_type`, `broker_commission_rate` and
  the resulting `broker_commission` (owed by you to the broker; never on the invoice)
- `sale_date`, optional `due_date` (unpaid invoices past it show as overdue)
- truck: `vehicle_number`, `driver_name`, `driver_mobile`, `transporter_name`
- transport money, kept **separate** from rice money: `transport_rate_per_ton`,
  `transport_charge`, `transport_paid_by_dealer`, `transport_paid_by_customer`
- rice money: `tax_type` (CGST+SGST / IGST / none), `total_bags`, `total_quantity_kg`,
  `taxable_amount`, `cgst_amount`, `sgst_amount`, `igst_amount`, `gst_amount`, `round_off`,
  `total_amount`, `advance_received` + `advance_mode`, `balance_amount`
- `invoice_no` — per-company series

**SaleItem** — one line **on the customer's invoice**: `product`, `bag_weight`, `bag_count`,
the **selling** `rate_per_kg`, `gst_percent`, and the computed `total_weight`, `amount`
(before GST), `gst_amount`, `line_total`. Optionally `purchase_item` = the lot the user picked.

**SaleLot** — the owner's private **breakup**: which purchase lot (`purchase_item`, `mill`)
each line's bags came out of, with the mill's bill rate and the **landed cost per kg** (bill
rate + that purchase's transport/labour/expenses, no GST). Never shown to the customer.

**Payment** — one money movement. `related_type` is `"sale"` (money received from a customer
— against a `sale`, or on account with only `customer`), `"purchase"` (money paid to a mill)
or `"broker"` (commission paid to a `broker`), plus `amount`, `payment_mode`, `payment_date`,
`notes`.

### How stock is calculated — there is no stock table

Stock is never stored. It is **counted on demand** (`core/services/sale_service.py`):

```
stock of one lot          = PurchaseItem.bag_count - SUM(SaleLot.bag_count for that lot)
stock of a rice + bag size = SUM(PurchaseItem.bag_count) - SUM(SaleItem.bag_count)
```

Consequences you must know:
- Stock is always "live", never wrong because of a forgotten update.
- **A sale cannot take more bags than are in stock** — checked per lot and per rice + bag
  size, inside a transaction that locks the lots, so two people cannot sell the same last bags.
- Without a chosen lot, bags come out of the **oldest** lot of that rice and bag size first
  (FIFO); a sale line can span several lots.
- The product report still adds 20 kg and 50 kg bags together in its single bag figure.
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
| `/sales/` | `view.sale_list` | sale_list.html | Sales + Paid/Partial/Due/Overdue |
| `/sales/add/` | `view.add_sale` | sale_form.html | **Create a sale (§8.6)** |
| `/sales/<id>/edit/` `/sales/<id>/delete/` | `view.edit_sale` / `view.delete_sale` | sale_form.html / delete_sale.html | Change or remove a sale |
| `/billing/` | `billing.home` | billing/home.html | Subscription status + plans |
| `/billing/checkout/<code>/` | `billing.checkout` | billing/checkout.html | Pay for a plan (owner only) |
| `/billing/webhook/razorpay/` | `billing.razorpay_webhook` | — | Razorpay confirms payment |
| `/billing/manage/` | `billing.manage_companies` | billing/manage_companies.html | **Staff only:** all companies |
| `/password-reset/` | Django auth views | core/auth/*.html | Forgot password flow |
| `/sales/<id>/` | `view.sale_detail` | sale_detail.html | Invoice + received + cost + profit |
| `/sales/<id>/print/` | `view.sale_print` | sale_print.html | Printable HTML invoice (follows the language) |
| `/sales/<id>/invoice.pdf` | `function.sale_invoice_pdf` | → .pdf file | **GST invoice PDF** |
| `/sales/<id>/payment/add/` | `view.add_sale_payment` | receipt_form.html | Receive money against an invoice |
| `/payments/<id>/delete/` | `view.delete_payment` | — | Remove a receipt / commission payment |
| `/brokers/` `/brokers/add/` `/brokers/<id>/edit/` `/brokers/<id>/toggle/` | `view.*broker*` | broker_*.html | Brokers |
| `/brokers/report/<id>/` `/brokers/<id>/payment/add/` | `view.broker_report_detail` / `view.add_broker_payment` | broker_report_detail.html / receipt_form.html | Broker's sales, commission ledger, pay commission |
| `/customers/` `/customers/add/` `/customers/edit/<id>/` `/customers/delete/<id>/` | `view.customer_*` | customer_*.html | Customer master (with balance due) |
| `/customers/<id>/` `/customers/<id>/payment/add/` | `view.customer_ledger` / `view.add_customer_payment` | customer_ledger.html / receipt_form.html | Customer ledger, money received on account |
| `/i18n/setlang/` | Django `set_language` | — | English / Hindi switch (top bar) |
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

### 8.6 Sale entry (`core/view/sale/sale_views.py` + `core/services/sale_service.py`)

A sale has two sides, and this is the key business idea of the whole app:

| Side | What it is | Shown to customer? | Stored in |
|---|---|---|---|
| **Selling side** | rice lines, selling rate, GST, transport, advance | Yes, on the invoice | `Sale` + `SaleItem` |
| **Buying side ("breakup")** | which purchase lot each bag came from, and its cost | **Never** | `SaleLot` |

```
GET /sales/add/               (?customer=<id> pre-selects a customer)
   SaleForm (customer, dates, tax type, broker, truck, transport, money received)
   SaleItemFormSet (one row per rice line, with an optional "take stock from" lot)
   JSON for the page: customers (address, state, suggested tax), brokers (commission),
   products (GST %, stock per bag size, cost per kg) and the lots that still have stock
        |
POST /sales/add/
   1. validate the forms (customer required, no future date, money received needs a mode…)
   2. inside one transaction:
        - next invoice number for this company        SAL-YYYYMMDD-0001
        - copy the customer's details onto the sale (snapshot)
        - lock this company's lots, allocate bags: chosen lot, else oldest first
          -> not enough stock: roll everything back (the invoice number too) and show
             "Katarni (50 kg bags): only 12 bags in stock, you asked for 20."
        - compute totals (per-line GST, CGST/SGST or IGST, round to rupees), freight,
          broker commission
        - save Sale, SaleItem rows, SaleLot rows (with landed cost per kg)
        |
   redirect to the invoice page (or a fresh form with "Save & make another")
```

Editing (`/sales/<id>/edit/`, manager/owner) replaces the lines and lots; the sale's own bags
count as available while it is edited. Deleting (`/sales/<id>/delete/`) puts the bags back in
stock and is refused while payments exist against the invoice.

Invoice numbers come from `core/services/invoice_number.py`. Each company has its own
counter row (`InvoiceSequence`), locked with `select_for_update()` while the next number is
handed out, so numbers never repeat and never skip:

```
Demo Rice Co     SAL-20260927-0001, SAL-20260927-0002, ...
Bihar Traders    BRT-20260927-0001, ...      (its own series and its own prefix)
```

### 8.7 Invoice page, profit and the customer / broker ledgers

`core/services/customer_ledger.py` is the selling-side twin of the mill ledger:

```
received on an invoice = advance typed on the sale + payments against that sale
on account             = payments to the customer without naming a sale
                         -> applied to the opening balance, then the oldest unpaid invoice
due                    = invoice total - received          (an overpayment becomes an advance)
```

The sale list, the invoice page and the customer ledger (`/customers/<id>/`) all use it, so
they always agree. Money is received from the invoice page or, on account, from the ledger.

```
profit = taxable amount (selling, before GST - GST is not your income)
       - SUM(SaleLot.cost_amount)   (landed cost of the bags actually sold)
       - broker commission
```

The broker page (`/brokers/report/<id>/`) shows every sale he brought, the commission earned
on each, commission paid (`Payment` type `"broker"`) and what is still owed.

### 8.8 The GST invoice PDF (`core/function/sale_invoice_pdf.py`)

Built with ReportLab's flowing layout (`platypus` tables), A4 with 12 mm margins: every box
grows with its text, long names and addresses wrap, and a long invoice continues on the next
page with the table header repeated. It prints TAX INVOICE (or BILL OF SUPPLY when there is no
GST), the seller block, invoice and transport details, bill-to / ship-to, one row per rice
line, CGST/SGST or IGST, round off, received and balance due, the amount in words, bank
details, a QR code (a UPI scan-to-pay code when the company has a UPI id), terms and a
signature area. Freight is printed as an information line, outside the invoice total.

`/sales/<id>/print/` is an HTML version of the same invoice for the browser's own print; it
follows the chosen language, so it prints in Hindi when the app is in Hindi. The PDF stays in
English (ReportLab cannot shape Devanagari text correctly).

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
| Sale logic | `core/services/sale_service.py` (maths, stock) and `core/view/sale/sale_views.py` |
| Customer / broker balances | `core/services/customer_ledger.py` |
| A Hindi translation | `locale/hi/LC_MESSAGES/django.po`, then `compilemessages` (see README) |
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

**Fixed in October 2026** — sales are linked to customers with a customer ledger and
receivables (on-account money, advances, overdue invoices); stock is checked per lot before a
sale is saved; profit leaves out GST and takes off the broker's commission; broker commission
is calculated, with a broker ledger; the invoice PDF layout; the whole app can be switched
between English and Hindi.

1. No aging report (0-30 / 31-60 / 60+ days) across all customers yet — the data is there.
2. The product report adds 20 kg and 50 kg bags together in one figure.
3. Old sales made before stock lots existed have no lot breakup, so their profit is unknown
   until each is edited and saved once.
4. No sales returns / credit notes.
5. The dashboard is still a static page with no numbers on it.
6. No GST return report (GSTR-1 / HSN summary) and no day book.
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
