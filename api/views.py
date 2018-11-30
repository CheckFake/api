import logging

from django.http import JsonResponse

from api.models import WebPage

logger = logging.getLogger(__name__)


def web_page_score_view(request):
    web_page_url = request.GET.get('url')
    logger.debug(f"Found url {web_page_url}")
    if not web_page_url:
        logger.error('No URL provided')
        return JsonResponse({
            'status': 'error',
            'data': {
                'message': 'No URL provided'
            }
        }, status=400)

    logger.info(f"Received request for following URL : {web_page_url}")
    web_page = WebPage.from_url(url=web_page_url)
    if isinstance(web_page, str):
        logger.error(f'{web_page} - {web_page_url}', extra={'request': request})
        return JsonResponse({
            'status': 'error',
            'data': {
                'message': web_page
            }
        })
    else:
        return JsonResponse({
            'status': 'success',
            'data': web_page.to_dict()
        })


def ping_view(request):
    return JsonResponse({
        'status': 'alive'
    })
