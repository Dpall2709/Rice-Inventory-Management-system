"""
Sign-up now lives in the accounts app: details -> 6-digit email code ->
account created. /register/ (URL name 'register') renders the same view.
"""

from accounts.views import signup as register_view  # noqa: F401
