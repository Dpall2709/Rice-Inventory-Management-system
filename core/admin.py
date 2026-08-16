from django.contrib import admin
from .models import Product, Mill, Purchase, PurchaseItem, Sale, SaleItem, Payment, Broker, Company, UserProfile

admin.site.register(Product)
admin.site.register(Mill)
admin.site.register(Broker)
admin.site.register(Purchase)
admin.site.register(PurchaseItem)
admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(Payment)
admin.site.register(Company)
admin.site.register(UserProfile)