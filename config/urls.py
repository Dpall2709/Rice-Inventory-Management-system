"""
Top level URL map.

    /admin/     Django admin (for you, the developer)
    /billing/   subscription and payment screens
    /           the rice billing app itself (core)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    path("billing/", include("billing.urls")),

    # Password reset, using Django's own screens with our templates.
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="core/auth/password_reset.html",
            email_template_name="core/auth/password_reset_email.txt",
            subject_template_name="core/auth/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="core/auth/password_reset_sent.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="core/auth/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="core/auth/password_reset_done.html"
        ),
        name="password_reset_complete",
    ),

    path("", include("core.urls")),
]

# Company logos and other uploads, served by Django only in development.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
