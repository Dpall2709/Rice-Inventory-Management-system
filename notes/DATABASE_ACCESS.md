# Looking at the data — pgAdmin, PostgreSQL and Django admin

*Set up 27 September 2026. Local development machine only.*

---

## 1. What is running

Both the database and pgAdmin run in Docker. Nothing was installed into macOS itself, so
removing them later is one command each.

| What | Container | Address | Image |
|---|---|---|---|
| PostgreSQL 16 (your data) | `rice-postgres` | `localhost:5432` | `postgres:16` |
| pgAdmin 4 (the viewer) | `rice-pgadmin` | **http://localhost:5050** | `dpage/pgadmin4` |

They talk to each other over a Docker network called `rice-net`. Your data lives in the
Docker volume `rice_pgdata`, which survives container deletion.

> PostgreSQL was **already installed** — it is the container holding your records. Installing
> a second PostgreSQL on macOS would fight for port 5432 and start empty, so pgAdmin was
> pointed at the existing one instead.

---

## 2. Open pgAdmin

1. Go to **http://localhost:5050**
2. There is **no login screen** (it runs in desktop mode).
3. In the left panel open **Rice Inventory → Rice Billing (local)**.
4. It asks for the database password once: **`Admin@123`** — tick *Save password*.

Then walk down the tree:

```
Rice Inventory
└── Rice Billing (local)
    └── Databases
        └── rice_trading_db
            └── Schemas
                └── public
                    └── Tables          ← all 20 tables are here
```

Right-click any table → **View/Edit Data → All Rows** to see its contents in a grid you can
sort, filter and edit. For your own queries use **Tools → Query Tool**.

### Connection details (for pgAdmin, TablePlus, DBeaver, or any client)

| Setting | From pgAdmin's container | From a Mac app / terminal |
|---|---|---|
| Host | `rice-postgres` | `localhost` |
| Port | `5432` | `5432` |
| Database | `rice_trading_db` | `rice_trading_db` |
| Username | `postgres` | `postgres` |
| Password | `Admin@123` | `Admin@123` |

The host differs because inside Docker the container name is the address; from macOS it is
`localhost`. These are the same values the Django app reads from `.env`.

---

## 3. Which table holds what

| Table | What is in it |
|---|---|
| `core_company` | Your tenants — one row per rice business |
| `core_userprofile` | Links a login to a company, with the role (owner/manager/staff) |
| `auth_user` | Django's login table (username, hashed password) |
| `core_mill` | Suppliers |
| `core_product` | Rice types (name, HSN, GST %) |
| `core_customer` | Customers |
| `core_broker` | Brokers |
| `core_purchase` | Purchase invoice header (mill, invoice no, date, total) |
| `core_purchaseitem` | Rice lines in a purchase — **this is also your stock lot** |
| `core_sale` | Truck sale invoice header (customer, transport, GST, totals) |
| `core_saleitem` | Internal breakup: which lots filled the truck, at buying cost |
| `core_payment` | Money in and out (`related_type` = `sale` or `purchase`) |
| `core_invoicesequence` | Per-company invoice number counters |
| `billing_plan` | Subscription plans you sell |
| `billing_subscription` | Each company's plan, status and expiry date |
| `billing_subscriptionpayment` | Subscription payment attempts (Razorpay or manual) |

Every business table carries a `company_id`. **Filter by it** or you will mix tenants together.

### What is in there right now

| Table | Rows |
|---|---|
| `core_company` | 3 (Demo Rice Co, test, Trial Rice Co) |
| `auth_user` / `core_userprofile` | 5 |
| `core_mill` | 7 |
| `core_product` | 2 |
| `core_purchase` / `core_purchaseitem` | 5 / 5 |
| `core_sale` / `core_saleitem` | 1 / 1 |
| `core_payment` | 1 |
| `core_customer` | 1 |
| `billing_plan` / `billing_subscription` | 3 / 3 |

---

## 4. Useful queries (paste into Query Tool)

**Everything a company owns**

```sql
SELECT c.id, c.company_name, s.status, s.end_date
FROM core_company c
LEFT JOIN billing_subscription s ON s.company_id = c.id
ORDER BY c.id;
```

**What you owe each supplier** — the same maths the Mills page shows

```sql
SELECT m.mill_name,
       m.opening_balance,
       COALESCE(SUM(DISTINCT p.total_amount), 0) AS purchased,
       COALESCE((SELECT SUM(amount) FROM core_payment
                 WHERE mill_id = m.id AND related_type = 'purchase'), 0) AS paid,
       m.opening_balance
         + COALESCE((SELECT SUM(total_amount) FROM core_purchase WHERE mill_id = m.id), 0)
         - COALESCE((SELECT SUM(amount) FROM core_payment
                     WHERE mill_id = m.id AND related_type = 'purchase'), 0) AS balance
FROM core_mill m
LEFT JOIN core_purchase p ON p.mill_id = m.id
WHERE m.company_id = 3           -- change to your company id
GROUP BY m.id, m.mill_name, m.opening_balance
ORDER BY balance DESC;
```

**Current stock in bags** (bought − sold, per rice type)

```sql
SELECT pr.rice_name,
       COALESCE(SUM(pi.bag_count), 0) AS bought_bags,
       COALESCE((SELECT SUM(si.bag_count) FROM core_saleitem si WHERE si.product_id = pr.id), 0) AS sold_bags,
       COALESCE(SUM(pi.bag_count), 0)
         - COALESCE((SELECT SUM(si.bag_count) FROM core_saleitem si WHERE si.product_id = pr.id), 0) AS in_stock
FROM core_product pr
LEFT JOIN core_purchaseitem pi ON pi.product_id = pr.id
WHERE pr.company_id = 3
GROUP BY pr.id, pr.rice_name;
```

**Sales with money still due**

```sql
SELECT s.invoice_no, s.sale_date, s.customer_name, s.total_amount,
       s.advance_received
         + COALESCE((SELECT SUM(amount) FROM core_payment
                     WHERE sale_id = s.id AND related_type = 'sale'), 0) AS received,
       s.total_amount - s.advance_received
         - COALESCE((SELECT SUM(amount) FROM core_payment
                     WHERE sale_id = s.id AND related_type = 'sale'), 0) AS due
FROM core_sale s
WHERE s.company_id = 3
ORDER BY s.sale_date DESC;
```

**Your subscription revenue**

```sql
SELECT c.company_name, p.name AS plan, sp.amount, sp.gateway, sp.status, sp.paid_at
FROM billing_subscriptionpayment sp
JOIN core_company c ON c.id = sp.company_id
LEFT JOIN billing_plan p ON p.id = sp.plan_id
ORDER BY sp.created_at DESC;
```

---

## 5. Two other ways to see the same data

**Django admin — http://127.0.0.1:8000/admin/** (login `rootadmin` / `RootPass#2026`).
Friendlier for everyday checks, and it understands relationships. It currently shows **all
companies' rows** to any staff user, so treat it as a developer tool only.

**Terminal**, no GUI at all:

```bash
docker exec -it rice-postgres psql -U postgres -d rice_trading_db
# \dt        list tables
# \d core_mill   describe a table
# \q         quit
```

---

## 6. Starting, stopping, removing

```bash
# start both (after a reboot; Docker Desktop must be open)
docker start rice-postgres rice-pgadmin

# stop them
docker stop rice-pgadmin rice-postgres

# remove pgAdmin entirely (your data is NOT affected)
docker rm -f rice-pgadmin

# recreate pgAdmin exactly as it is now
docker run -d --name rice-pgadmin --network rice-net -p 5050:80 \
  -e PGADMIN_DEFAULT_EMAIL=admin@ricebilling.com \
  -e PGADMIN_DEFAULT_PASSWORD='Admin@123' \
  -e PGADMIN_CONFIG_SERVER_MODE=False \
  -e PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED=False \
  dpage/pgadmin4:latest
```

If pgAdmin is removed you lose only its settings — never the database, which lives in the
`rice_pgdata` volume.

---

## 7. Backup and restore

```bash
# backup to a file
docker exec rice-postgres pg_dump -U postgres rice_trading_db | gzip > rice-backup-$(date +%F).sql.gz

# restore into an empty database
gunzip -c rice-backup-2026-09-27.sql.gz | docker exec -i rice-postgres psql -U postgres rice_trading_db
```

Do this before any risky experiment. See [HOSTING.md](HOSTING.md) for the automated
nightly version.

---

## 8. Security notes

These settings are fine on your laptop and **wrong for a server**:

1. `Admin@123` is a weak password, and it is written in this file and in `.env`.
2. PostgreSQL publishes port 5432 to all interfaces (`-p 5432:5432`). On a server publish it
   to localhost only: `-p 127.0.0.1:5432:5432`.
3. pgAdmin runs with no login (`SERVER_MODE=False`). Never expose port 5050 to the internet —
   anyone reaching it would get full database access.
4. If this machine is on a shared or public network, stop pgAdmin when you are not using it:
   `docker stop rice-pgadmin`.
