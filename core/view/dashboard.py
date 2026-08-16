from .base_imports import *

@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')