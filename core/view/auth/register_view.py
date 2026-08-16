from ..base_imports import *
from ...forms import CompanyRegistrationForm
from ...services.registration_service import register_company

def register_view(request):

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":

        form = CompanyRegistrationForm(request.POST)

        if form.is_valid():

            register_company(form)

            messages.success(
                request,
                "Company registered successfully. Please login."
            )

            return redirect("login")

    else:

        form = CompanyRegistrationForm()

    return render(
        request,
        "core/register.html",
        {
            "form": form
        }
    )