import datetime
import random
import statistics

import tldextract
from django.db import models
from django.db.models import Avg
from django.utils import timezone

from api.utils import ChoiceEnum

import urllib.request
from urllib.request import urlopen, Request
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import requests
import re
from goose3 import Goose


class WebPage(models.Model):
    CURRENT_SCORES_VERSION = 3

    class Categories(ChoiceEnum):
        SCIENCE = 'science'
        POLITICS = 'politics'
        NEWS = 'news'
        UNKNOWN = 'unknown'

    url = models.URLField(unique=True)
    content_score = models.PositiveIntegerField(blank=True, null=True)
    base_domain = models.CharField(max_length=250)
    scores_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def site_score(self):
        return (WebPage.objects.filter(base_domain=self.base_domain).aggregate(site_score=Avg('content_score')))['site_score']

    @property
    def global_score(self):
        exclude = ['global_score', 'compute_scores']
        fields = list(filter(lambda x: "_score" in x and x not in exclude, dir(self)))
        scores = list(map(lambda x: getattr(self, x), fields))
        return statistics.mean(scores)

    def compute_scores(self):

        # Ask the URL of the news
        originalURL = self.url
        parsed_uri = urlparse(originalURL)

        # Extract the title and the text of the article
        g = Goose()
        article = g.extract(url=originalURL)
        #print("Title : {}".format(article.title))
        #print("Text : {}".format(article.cleaned_text))
        #print("Date : {}".format(article.publish_datetime_utc))

        title = article.title

        # Construct the url for the GET request
        title = title.replace(" ", "-")
        urlRequest = "https://www.google.fr/search?q=" + str(title) + "&tbs=cdr%3A1%2Ccd_min" + (article.publish_datetime_utc.date - datetime.timedelta(days=7))  + "%2Ccd_max" + (article.publish_datetime_utc.date + datetime.timedelta(days=7)) 
        #print("URL : {}".format(urlRequest))

        # GET request
        page = requests.get(urlRequest)
        soup = BeautifulSoup(page.content, "lxml")
        for link in soup.find_all("a",href=re.compile("(?<=/url)(\?|\&)q=(htt.*://.*)")):
            linkedURL = parse_qs(urlparse(link['href']).query)['q'][0]

            if "webcache" not in linkedURL and parsed_uri.netloc not in linkedURL:
                article = g.extract(url=linkedURL)
                print(article.title)
                article.cleaned_text
                print(linkedURL)
                print()

        #TODO
        self.content_score = random.randint(0, 100)

        self.scores_version = WebPage.CURRENT_SCORES_VERSION

        tld_extract = tldextract.TLDExtract(
            cache_file='api/external_data/public_suffixes_list.dat',
            include_psl_private_domains=True
        )
        url_extraction = tld_extract(self.url)
        base_domain = f"{url_extraction.domain}.{url_extraction.suffix}".lower()
        print(base_domain)
        self.base_domain = base_domain

        self.save()
        return self

    def to_dict(self):
        fields_to_serialize = ['url', 'global_score']
        self_serialized = {field: getattr(self, field) for field in fields_to_serialize}
        scores = ['content_score', 'site_score']
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
