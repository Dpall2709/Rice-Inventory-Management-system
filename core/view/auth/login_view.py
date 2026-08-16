from ..base_imports import *

def login_view(request):

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is None:
            messages.error(request, "Invalid username or password.")
            return render(request, "core/login.html")

        try:
            profile = UserProfile.objects.select_related("company").get(user=user)

        except UserProfile.DoesNotExist:
            messages.error(request, "Your account is not configured correctly.")
            return render(request, "core/login.html")

        if not profile.is_active:
            messages.error(request, "Your account has been deactivated.")
            return render(request, "core/login.html")

        if not profile.company.is_active:
            messages.error(request, "Your company account is inactive.")
            return render(request, "core/login.html")

        login(request, user)

        messages.success(
            request,
            f"Welcome {user.first_name or user.username}!"
        )

        return redirect("dashboard")

    return render(request, "core/login.html")
