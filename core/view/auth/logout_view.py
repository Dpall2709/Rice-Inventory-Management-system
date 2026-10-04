
from django.utils.translation import gettext as _

from ..base_imports import *

def logout_view(request):

    logout(request)

    messages.success(request, _("Logged out successfully."))

    return redirect("login")


