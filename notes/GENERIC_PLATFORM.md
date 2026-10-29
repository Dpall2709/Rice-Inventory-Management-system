# Generic trading platform — what changed and how it works

*Written 29 October 2026, on branch `saas-phase1-2`.*

The app started as rice-only billing. It now serves any trading business —
rice, biscuits/FMCG, grocery wholesale, packaging, building material, agri
commodities — without code changes per industry.

## 1. Products, units and categories

| Model | Purpose |
|---|---|
| `Unit` (per company) | Bag, Box, Carton, Packet, Piece, Kg, Quintal, Ton, Litre + any custom unit. `allow_decimal` marks units that can be split. |
| `ProductCategory` (per company) | Free grouping; seeded from the company's `industry`. |
| `Product` | `name` (was `rice_name`), `sku`, `category`, `unit` (pack unit), `rate_unit`, `default_pack_size`, `hsn_code`, `gst_percent` (now decimal), `description`. |

Every line follows one rule:

```
line value = quantity (packs) × pack size (rate units per pack) × rate (per rate unit)
```

| Business | Pack unit | Rate unit | Pack size |
|---|---|---|---|
| Rice, 50 kg bags priced per kg | Bag | Kg | 50 |
| Biscuits, cartons of 24 priced per piece | Carton | Piece | 24 |
| Cement priced per bag | Bag | Bag | 1 |
| Oil, tins priced per litre | Tin (custom) | Litre | 15 |

**Column names kept on purpose.** To avoid rewriting every ledger, report and
test, the database still says `bag_count` (= quantity), `bag_weight`
(= pack size), `rate_per_kg` / `purchase_price` (= rate), `total_kg` /
`total_weight` / `total_quantity_kg` (= total in rate units), `total_bags`
(= total quantity), and `Mill` (= supplier). Screens, PDFs and the API use
the generic words. The API never exposes the old names.

New companies get default units and categories on sign-up
(`core/services/catalog.py`). Migration `0015` gives existing companies the
defaults and marks their products as *Bag, priced per Kg* with the bag size
they buy most.

Screens: **Products → Units & categories** (`/products/units/`).

## 2. Precision

* Quantities, pack sizes, rates, freight rate per ton, commission rate and
  CD %: **3 decimals** (`12.345`).
* Money stays at 2 decimals (paise). Line values are worked out at full
  precision and rounded once per line, half-up.
* Display: `{{ value|qty }}` (template) / `core.utils.qty_str()` — up to 3
  decimals, no trailing zeros.

## 3. Freight arrangements (`Sale.freight_borne_by`)

| Value | Scenario | On the goods invoice | Buyer's share | Your cost |
|---|---|---|---|---|
| `us` | **A** Seller pays (FOR delivery) | nothing | 0 | all freight |
| `customer` | **B** Buyer pays | freight added | all | 0 |
| `shared` | **C** Shared | buyer's share added | `freight_customer_share` | the rest |
| `bill` | **D** Separate transport invoice | nothing (own `TRN-…` invoice) | all | 0 |
| `included` | **E** Included in the rate | nothing shown | 0 | all freight |
| `separate` | Buyer ↔ transporter directly | nothing | — not in books — | 0 |

The stored values `us`, `customer` and `separate` are unchanged from the
first version, so old sales keep their meaning.

The calculation lives in `sale_service.freight_figures()`:

```
total freight  = freight_amount typed in, else weight/1000 × rate per ton,
                 else what was paid to the transporter
adjustment     = buyer's share − what the buyer paid the transporter
net receivable = goods payable (after CD, brokerage, shortage) + adjustment
your cost      = total freight − buyer's share        (used in profit)
```

Freight on the invoice (B, C) is never reduced by a transit shortage and
never gets cash discount. The transport invoice PDF is at
`/sales/<id>/transport-invoice.pdf`. Each company picks its usual
arrangement in **Business profile** (`Company.default_freight_mode`).

## 4. Manual GST adjustment

Sales and purchases have `manual_cgst`, `manual_sgst`, `manual_igst` and
`gst_adjust_reason`. Empty = automatic. When a figure is typed:

1. It replaces the calculated head (only the heads valid for the tax type).
2. The total and round-off are worked out again.
3. A reason is required.
4. `TaxAdjustment` stores calculated vs entered, user, reason and time. It
   is shown as *GST adjustments (audit trail)* on the sale page.

Code: `core/services/gst.py`.

## 5. Quick create from sale / purchase

The “➕ New” buttons next to the customer, supplier and product dropdowns open
a pop-up (`core/static/core/quick_create.js`). It loads a form from
`/quick/customer/`, `/quick/supplier/` or `/quick/product/`. On save, the
server answers with JSON. The new record is then added to every matching
dropdown, including new lines added later, and selected. A `quick-created`
event lets the page fill in GST %, state and pack size.

## 6. REST API for the mobile app (`/api/v1/`)

JWT login (`auth/token/`, `auth/token/refresh/`), company-scoped, with the
same roles as the web: staff read + create, manager/owner also edit/delete.
An expired subscription makes the API read-only. The endpoint list is in
`api/urls.py` and the tests are in `api/tests.py`. Sales and purchases are
created through the same services as the web, so numbering, stock checks,
freight and GST match. Editing an existing sale or purchase is web-only for
now.

The Flutter app lives on the separate branch **`flutter-app`**. See its README.

## 7. Running tests without Postgres

```
python manage.py test core accounts billing api --settings=<module that swaps DATABASES to sqlite>
```

The suite passes on SQLite. Production stays on PostgreSQL.
