
from ..base_imports import *

def logout_view(request):

    logout(request)

    messages.success(request, "Logged out successfully.")

    return redirect("login")


