import datetime
import json
import random
import statistics

import tldextract
from django.db import models
from django.utils import timezone

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def global_score(self):
        exclude = ['global_score', 'compute_scores']
        fields = list(filter(lambda x: "_score" in x and x not in exclude, dir(self)))
        scores = list(map(lambda x: getattr(self, x), fields))
        return statistics.mean(scores)

    def compute_scores(self):
        self.author_score = random.randint(0, 100)
        self.scores_version = WebPage.CURRENT_SCORES_VERSION

        category = None
        domain_score = None

        open_sources_score_mapping = {
            'fake': 0,
            'satire': 0,
            'bias': 0,
            'conspiracy': 0,
            'rumor': 0,
            'state': 0,
            'junksci': 0,
            'hate': 0,
            'clickbait': 0,
            'unreliable': 0,
            'political': 40,
            'reliable': 80,
        }

        open_sources_category_mapping = {
            'fake': self.Categories.NEWS,
            'satire': self.Categories.NEWS,
            'bias': self.Categories.NEWS,
            'conspiracy': self.Categories.NEWS,
            'rumor': self.Categories.NEWS,
            'state': self.Categories.NEWS,
            'junksci': self.Categories.SCIENCE,
            'hate': self.Categories.NEWS,
            'clickbait': self.Categories.NEWS,
            'unreliable': self.Categories.NEWS,
            'political': self.Categories.POLITICS,
            'reliable': None,
        }

        with open('api/external_data/open_sources.json') as open_sources_json:
            open_sources = json.load(open_sources_json)
            tld_extract = tldextract.TLDExtract(
                cache_file='api/external_data/public_suffixes_list.dat',
                include_psl_private_domains=True
            )
            url_extraction = tld_extract(self.url)
            base_domain = f"{url_extraction.domain}.{url_extraction.suffix}".lower()
            print(base_domain)
            if base_domain in open_sources:
                open_sources_type = open_sources[base_domain]['type']
                category = open_sources_category_mapping[open_sources_type]
                domain_score = open_sources_score_mapping[open_sources_type]

        if domain_score is not None:
            self.domain_score = domain_score
        else:
            self.domain_score = random.randint(0, 100)

        if category is not None:
            self.category = category
        else:
            self.category = random.choice(self.Categories.choices())[0]

        self.save()
        return self

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

        if (existing
                and existing.scores_version == WebPage.CURRENT_SCORES_VERSION
                and existing.updated_at > timezone.now() - datetime.timedelta(days=7)):
            return existing

        elif not existing:
            existing = cls(url=url, scores_version=WebPage.CURRENT_SCORES_VERSION)

        return existing.compute_scores()

    def __str__(self):
        return self.url
