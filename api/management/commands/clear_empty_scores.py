from django.core.management.base import BaseCommand

from api.models import WebPage


class Command(BaseCommand):
    help = 'Deletes pages with empty content score'

    def handle(self, *args, **options):
        res = WebPage.objects.filter(content_score=None).delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted pages with empty content score {res}'))
