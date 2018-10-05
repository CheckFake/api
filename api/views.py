from django.http import JsonResponse

from api.models import WebPage


def web_page_score_view(request):
    web_page_url = request.GET.get('url')
    if not web_page_url:
        return None

    return JsonResponse(WebPage.from_url(url=web_page_url).to_dict())
