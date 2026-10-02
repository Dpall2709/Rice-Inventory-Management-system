"""
Login now lives in the accounts app (username, email or mobile; throttling;
"keep me signed in"). This name is kept so `view.login_view` keeps working.
"""

from accounts.views import login_view  # noqa: F401
