from django.contrib import admin

from .models import AccountSecurity, EmailOTP, PendingSignup


@admin.register(PendingSignup)
class PendingSignupAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "company_name", "created_at", "expires_at", "completed_at")
    search_fields = ("username", "email", "company_name", "mobile")
    exclude = ("password_hash", "token")


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "purpose", "created_at", "expires_at", "attempts", "closed_at")
    search_fields = ("email",)
    exclude = ("code_hash",)


@admin.register(AccountSecurity)
class AccountSecurityAdmin(admin.ModelAdmin):
    list_display = ("user", "email_verified", "email_verified_at")
    search_fields = ("user__username", "user__email")
