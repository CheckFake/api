import random
import statistics

from django.db import models

from api.utils import ChoiceEnum


class WebPage(models.Model):
    CURRENT_SCORES_VERSION = 2

    class Categories(ChoiceEnum):
        SCIENCE = 'science'
        POLITICS = 'politics'
        NEWS = 'news'
        UNKNOWN = 'unknown'

    url = models.URLField(unique=True)
    domain_score = models.PositiveIntegerField(blank=True, null=True)
    author_score = models.PositiveIntegerField(blank=True, null=True)
    category = models.CharField(max_length=20, choices=Categories.choices(), null=True)
    scores_version = models.PositiveIntegerField()

    @property
    def global_score(self):
        exclude = ['global_score', 'compute_scores']
        fields = list(filter(lambda x: "_score" in x and x not in exclude, dir(self)))
        scores = list(map(lambda x: getattr(self, x), fields))
        return statistics.mean(scores)

    def compute_scores(self):
        self.domain_score = random.randint(0, 100)
        self.author_score = random.randint(0, 100)
        self.scores_version = WebPage.CURRENT_SCORES_VERSION
        self.category = random.choice(self.Categories.choices())[0]
        self.save()

    def to_dict(self):
        fields_to_serialize = ['url', 'global_score']
        self_serialized = {field: getattr(self, field) for field in fields_to_serialize}
        self_serialized['category'] = self.get_category_display()
        scores = ['domain_score', 'author_score']
        self_serialized['scores'] = {field: getattr(self, field) for field in scores}

        return self_serialized

    @classmethod
    def from_url(cls, url):
        existing = cls.objects.filter(url=url).first()

        if existing and existing.scores_version == WebPage.CURRENT_SCORES_VERSION:
            return existing
        elif not existing:
            existing = cls.objects.create(url=url, scores_version=WebPage.CURRENT_SCORES_VERSION)

        existing.compute_scores()
        return existing

    def __str__(self):
        return self.url
