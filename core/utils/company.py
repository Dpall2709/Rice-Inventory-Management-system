from core.models import UserProfile


def get_company(request):
    """
    Return logged-in user's company.
    """
    return UserProfile.objects.get(
        user=request.user
    ).company