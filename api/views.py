import logging

from django.http import JsonResponse

from api.models import WebPage

logger = logging.getLogger(__name__)


def web_page_score_view(request):
    web_page_url = request.GET.get('url').lower()
    logger.debug(f"Found url {web_page_url}")
    if not web_page_url:
        logger.error('No URL provided')
        return JsonResponse({
            'status': 'error',
            'data': {
                'message': 'No URL provided'
            }
        }, status=400)

    return JsonResponse({
        'status': 'success',
        'data': WebPage.from_url(url=web_page_url).to_dict()
    })


def ping_view(request):
    return JsonResponse({
        'status': 'alive'
    })
