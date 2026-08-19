How to run
1. git clone https://github.com/Dpall2709/Rice_billing_app.git
2. cd Rice_billing_app
3. python -m venv venv
4. .\venv\Scripts\activate
5. pip install -r requirements.txt
6. Create .env file
7. copy .env.example .env
8. python manage.py makemigrations
9. python manage.py migrate
10 . python manage.py runserver
http://127.0.0.1:8000/


python manage.py shell
from django.db import connection
print(connection.settings_dict["HOST"])
print(connection.settings_dict["NAME"])


🌾 Rice Billing App (Django + Supabase PostgreSQL)

Rice Billing App is a Django-based billing and ledger management system for rice trading business.

It manages:

✅ Mills/Suppliers
✅ Products
✅ Purchases (invoice + items)
✅ Mill reports (ledger + payments + PDF export)
✅ Sales (truck invoices + internal breakup)
✅ Brokers
✅ Payments (Purchase/Sale)

✅ Tech Stack

Python 3.13+

Django 6.0.1

PostgreSQL (Supabase)

HTML + CSS + JS

ReportLab (PDF Export)

📂 Folder Structure

Rice_billing_app/
│
├── config/           # Django project settings
├── core/             # Main app
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── templates/
│   └── static/
│
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
