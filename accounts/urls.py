from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("signup/verify/", views.signup_verify, name="verify"),
    path("signup/resend/", views.signup_resend, name="resend"),
    path("signup/edit/", views.signup_edit, name="signup_edit"),
    path("check/", views.check_availability, name="check"),
    path("login/", views.login_view, name="login"),
    path("business/", views.business_profile, name="business_profile"),
]
