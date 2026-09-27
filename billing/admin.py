from django.contrib import admin

from .models import Plan, Subscription, SubscriptionPayment


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "billing_period", "duration_days", "is_active")
    list_filter = ("is_active", "billing_period")
    prepopulated_fields = {"code": ("name",)}


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("company", "plan", "status", "start_date", "end_date", "days_left")
    list_filter = ("status", "plan")
    search_fields = ("company__company_name",)
    autocomplete_fields = ()

    @admin.display(description="Days left")
    def days_left(self, obj):
        return obj.days_left


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("company", "plan", "amount", "gateway", "status", "created_at", "paid_at")
    list_filter = ("status", "gateway")
    search_fields = ("company__company_name", "razorpay_order_id", "razorpay_payment_id")
    readonly_fields = ("created_at",)
