from django.core.management.base import BaseCommand

from api.models import WebPage


class Command(BaseCommand):
    help = 'Deletes pages with old content score'

    def handle(self, *args, **options):
        res = WebPage.objects.filter(scores_version__lt=WebPage.CURRENT_SCORES_VERSION - 1).delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted pages with old content score {res}'))
