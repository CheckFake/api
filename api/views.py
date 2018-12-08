import logging

from django.http import JsonResponse

from api.exceptions import APIException
from api.models import WebPage

logger = logging.getLogger(__name__)

LOG_LEVELS = {
    50: 'critical',
    40: 'error',
    30: 'warning',
    20: 'info',
    10: 'debug',
}


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

    try:
        web_page = WebPage.from_url(url=web_page_url)
        return JsonResponse({
            'status': 'success',
            'data': web_page.to_dict()
        })
    except APIException as exception:
        message = ' - '.join(filter(None, [exception.message, exception.internal_message, web_page_url]))

        logger.log(exception.level, message, extra={'request': request})

        return JsonResponse({
            'status': LOG_LEVELS.get(exception.level, 'unknown'),
            'data': {
                'message': exception.message
            }
        })


def ping_view(request):
    try:
        page = str(WebPage.objects.last())
        return JsonResponse({
            'status': 'dead'
        })
    except Exception:
        logger.critical("Error while trying to access DB when responding to healthcheck")
        return JsonResponse({
            'status': 'dead'
        })
