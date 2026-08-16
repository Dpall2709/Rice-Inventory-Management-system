from .models import UserProfile


class CompanyMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        request.company = None
        request.user_profile = None

        if request.user.is_authenticated:

            try:
                profile = UserProfile.objects.select_related(
                    "company"
                ).get(user=request.user)

                request.user_profile = profile
                request.company = profile.company

            except UserProfile.DoesNotExist:
                pass

        response = self.get_response(request)

        return response