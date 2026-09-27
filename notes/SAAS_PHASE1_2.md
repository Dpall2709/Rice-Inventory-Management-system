# Phase 1 + 2 — what changed and why

*27 September 2026. Branch: `saas-phase1-2`.*

Phase 1 = make the product safe to charge money for.
Phase 2 = the subscription engine.

Everything below is done, migrated and covered by tests (`python manage.py test` → 23 tests).

---

## 1. Company data can no longer leak between tenants

**The problem.** Every query filtered by company *by hand*. Two report exports had
forgotten to, so any logged-in user could download another company's supplier ledger by
changing the id in the URL:

```python
# core/views.py — before
def mill_report_excel(request, mill_id):
    mill = get_object_or_404(Mill, id=mill_id)          # any company's mill!
    purchases = Purchase.objects.filter(mill=mill)      # and its purchases
```

**The fix.** A new file [core/tenancy.py](../core/tenancy.py) gives every company-owned
model one safe way to query:

```python
from core.tenancy import company_of, tenant_object_or_404

company = company_of(request)                       # from the middleware, no extra query
mill    = tenant_object_or_404(Mill, request, mill_id)   # 404 if it is not yours
mills   = Mill.objects.for_company(company)              # only your rows
```

`for_company()` also works on `PurchaseItem` and `SaleItem`, which have no company column
of their own — they declare `company_path = "purchase__company"` / `"sale__company"` and
the manager follows it.

Fixed leaks:

| Place | Was | Now |
|---|---|---|
| `mill_report_excel` | any company's ledger | 404 unless it is yours |
| `mill_report_pdf` | any company's ledger | 404 unless it is yours |
| `add_sale.py` stock lots (2 places) | could sell from another company's purchase | scoped |
| `add_sale.py` broker, product | could attach another company's records | scoped |
| `broker_report_detail` | broker's sales unscoped | scoped |
| `sale_invoice_pdf` items | unscoped | scoped |

**Use these helpers in all new code.** A query written without them is how the next leak
happens.

## 2. Invoice numbers are per company, and race-safe

Before: `Sale.objects.filter(invoice_no__startswith=...)` looked at **every company's**
sales, and `invoice_no` was globally unique — so two businesses shared one number series,
and two users saving at the same second could take the same number.

Now [core/services/invoice_number.py](../core/services/invoice_number.py) keeps a counter
row per company (`InvoiceSequence`) and locks it with `select_for_update()` while handing
out the next number. Each company can also set its own `invoice_prefix`.

```
Demo Rice Co     SAL-20260927-0001
Bihar Traders    BRT-20260927-0001      <- its own series and prefix
```

`Sale.invoice_no` is now unique **per company** (`unique_sale_invoice_no_per_company`).

## 3. Invoices print the tenant's own company

`sale_invoice_pdf.py` used to read the seller name, GSTIN and bank details from constants
in `settings.py`, so every customer's invoice said "Sanjana Rice Mill". Those details now
come from the tenant's own `Company` row, with the settings values as a fallback only.

New fields on `Company`: `pan_number`, `invoice_prefix`, `bank_account_name`,
`bank_account_no`, `bank_name`, `bank_ifsc`, `bank_branch`, `upi_id`, `invoice_terms`.

**Tell each customer to fill these in** (Django admin → Companies) or their invoice falls
back to your details.

## 4. Roles actually mean something

`UserProfile.role` existed but nothing used it. Now [core/permissions.py](../core/permissions.py)
provides `@role_required(...)`, `@owner_required` and `@manager_required`:

| Role | Add | Edit | Delete | Billing |
|---|---|---|---|---|
| owner | ✅ | ✅ | ✅ | ✅ |
| manager | ✅ | ✅ | ✅ | ❌ |
| staff | ✅ | ✅ | ❌ | ❌ |

Applied to `delete_mill`, `delete_product`, `delete_purchase`, `delete_customer` and the
billing checkout. Extend it to more views as you decide the rules.

## 5. Secrets are out of the code

- `config/settings.py` no longer contains a database password. Everything reads from `.env`.
- With `DEBUG=False` and no `SECRET_KEY`, the app now **refuses to start** instead of
  running on a published default key.
- `.env.example` no longer contains real credentials — it is a blank template.
- `.env` is generated fresh with a random `SECRET_KEY`.

> ⚠️ The old `.env.example` in git history still contains a real Supabase host and
> password. **Change that password in Supabase.** Removing the file does not remove it
> from history.

- `DEBUG=False` now switches on HTTPS redirect, secure cookies, HSTS, nosniff,
  `X-Frame-Options: DENY` and proxy SSL headers automatically.

## 6. The subscription engine (new `billing` app)

```
billing/
├── models.py       Plan, Subscription, SubscriptionPayment
├── services.py     trial, activation, Razorpay order/verify/webhook
├── middleware.py   expiry enforcement (read-only mode)
├── views.py        tenant billing pages + your staff screens
├── urls.py         /billing/...
└── management/commands/seed_plans.py
```

**Plan** — what you sell: name, price, billing period, `duration_days`, `max_users`,
feature list. Seeded with Monthly ₹499 / Quarterly ₹1299 / Yearly ₹4499 — change these to
your real prices in `seed_plans.py` or in the admin.

**Subscription** — one row per company: plan, `start_date`, `end_date`, status
(`trial` / `active` / `expired` / `cancelled`). Renewing early **adds** to the current end
date, so nobody loses paid days; renewing after expiry starts from today.

**SubscriptionPayment** — every payment attempt, with the Razorpay order/payment/signature
ids, or `manual` for money received by UPI or bank transfer.

Signup now starts a **14-day trial** (`TRIAL_DAYS`). Before, `registration_service.py`
hardcoded a free ten-year subscription for everyone.

### Expiry = read-only, not locked out

`billing/middleware.py` puts `request.subscription` and `request.read_only` on every
request. When a subscription has ended:

- every page still opens, every report still works — **their data is never held hostage**
- any POST is stopped and redirected to `/billing/` with a clear message
- a red banner appears site-wide; an amber one appears in the last 7 days before expiry

This is deliberate. People renew when they can still see their own ledger; they walk away
when they are locked out of it.

### Payments

Razorpay is wired end to end: order creation → checkout on `/billing/checkout/<plan>/` →
signature verification → activation, plus a webhook at
`/billing/webhook/razorpay/` so a payment still activates if the customer closes the
browser. **Never trust the browser alone** — `confirm_payment()` verifies the signature.

With no Razorpay keys in `.env` (as on your machine now), the same screens record a
*manual payment request* instead, and you activate it yourself. So nothing here is wasted
if you delay the gateway.

### Your own screens

`/billing/manage/` (staff only) lists every company with plan, status, expiry date and
days left, and has a one-click **Extend** for offline payments — which also records a
`manual` payment row so your revenue history stays complete.

## 7. Password reset

Django's own reset flow is now wired up at `/password-reset/` with templates in
`core/templates/core/auth/`, and a "Forgot password?" link on the login page. In
development the email is printed in the terminal; set `EMAIL_HOST` in `.env` to send real
mail.

**Still missing: email verification at signup.** Anyone can register with any email
address. Worth adding before you advertise publicly.

## 8. Dead code removed

| Removed | Why |
|---|---|
| `core/views.py` lines 1342–1943 | **680 lines** of unreachable code sitting after a `return` inside `generate_sale_invoice_no()` — two old copies of `add_sale` |
| `sale_review`, `sale_confirm_save` views + URLs | dead duplicates of the live sale flow; `sale_confirm_save` had **no `@login_required`** and could create sales |
| the save form in `sale_print.html` | posted empty data to that view, creating junk sales |
| `core/function/register_view.py` | old copy, imported nowhere |
| `core/utils/company.py` | replaced by `core/tenancy.py` |
| `core/view/product/add_purchase.py` | never routed, and had no company filtering at all |

`core/views.py` went from 2,196 to 1,525 lines.

## 9. Tests, from zero

`core/tests.py` was empty. It now holds 23 tests in five groups: tenant isolation
(including the two exports that leaked), subscription trial/expiry/read-only/renewal, role
permissions, per-company invoice numbering, and the staff screens. Run with
`python manage.py test`.

## 10. Other fixes

- `requirements.txt` was UTF-16 with CRLF; it is plain UTF-8 now, grouped and commented,
  with `razorpay` added.
- `STATICFILES_DIRS` no longer points at a missing folder (the startup warning is gone).
- `MEDIA_URL` / `MEDIA_ROOT` configured, so company logo uploads work.
- Session lifetime, logging and email settings added.
- The sidebar now shows the tenant's own company name, a Subscription link, and an
  "All companies" link for staff.

---

## What is still left (next phases)

**Phase 3 — product value**

1. Link `Sale` to `Customer` (it still stores the customer as free text), then build the
   customer ledger, receivables and aging report.
2. Stock validation: nothing stops selling more bags than were bought. Also count stock in
   kg, not mixed 20/30 kg bags.
3. `profit_estimate` in `sale_detail` compares a GST-inclusive selling total with a
   GST-free buying cost, so the profit shown is too high by the GST amount.
4. The dashboard is still a static page — no numbers on it.
5. GST reports (sales register, HSN summary), day book, expenses, broker commission.
6. Mill ledger maths is copy-pasted in three places (HTML, Excel, PDF) — move it into one
   service before changing any formula.
7. Audit log (who created or changed a record) and soft delete everywhere.
8. Email verification at signup; subscription reminder emails (7/3/1 days before expiry) —
   a management command plus a daily cron.
9. Enforce `Plan.max_users` — it is stored but not checked anywhere yet.

**Phase 4 — mobile**

10. Move business logic out of the views into `core/services/`, then expose a DRF API with
    JWT (both packages are already installed), scoped by the same `for_company()` manager.
11. A PWA first (manifest + service worker + mobile-first CSS) before any native app.

**Engineering**

12. Duplicate view files still exist (`core/views.py` vs `core/view/`) — finish moving
    everything into `core/view/` and delete the old copies.
13. Django admin still shows all companies' data to any staff user; filter it per company
    if you ever give a customer admin access.
