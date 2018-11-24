import datetime
import logging
import os
import re
import statistics
from collections import Counter
from urllib.parse import urlparse

import requests
import tldextract
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from goose3 import Goose
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import RegexpTokenizer
from requests.exceptions import InvalidSchema

logger = logging.getLogger(__name__)


class WebPage(models.Model):
    CURRENT_SCORES_VERSION = 11

    url = models.URLField(unique=True, max_length=500)
    content_score = models.PositiveIntegerField(blank=True, null=True)
    base_domain = models.CharField(max_length=250)
    scores_version = models.PositiveIntegerField()
    total_articles = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def _site_score_queryset(self):
        return (WebPage.objects
                .filter(base_domain=self.base_domain)
                .filter(scores_version=WebPage.CURRENT_SCORES_VERSION))

    @property
    def site_score_articles_count(self):
        return self._site_score_queryset().count()

    @property
    def site_score(self):
        raw_site_score = (self._site_score_queryset()
                          .aggregate(site_score=Avg('content_score'))
                          )['site_score']
        return int(raw_site_score * 10) / 10

    @property
    def global_score(self):
        # allows to focus on the content if the site is "serious" and to focus on the site otherwise
        final_score = (100-self.site_score]) / 100 * self.site_score + self.site_score * self.content_score / 100
        return int(final_score * 10) / 10

    @staticmethod
    def tokens(text):
        tokenizer = RegexpTokenizer(r'\w+')
        tokens = tokenizer.tokenize(text)
        non_punct = re.compile('.*[A-Za-z0-9].*')
        filtered = [w for w in tokens if (non_punct.match(w) and len(w) > 2)]
        stemmer = SnowballStemmer("french")
        for i in range(len(filtered)):
            filtered[i] = stemmer.stem(filtered[i])
        return filtered

    def compute_scores(self):
        logger.debug("Start compute_scores")
        original_url = self.url
        parsed_uri = urlparse(original_url)
        logger.debug("URL parsed")

        # Extract the title and the text of the article
        g = Goose({'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"})
        try:
            article = g.extract(url=original_url)
        except InvalidSchema:
            message = f'Invalid schema for url {self.url}'
            logger.error(message)
            self.delete()
            return message

        title = article.title

        logger.debug("Write counter:")
        article_counter = Counter(self.tokens(article.cleaned_text))
        logger.debug("Tokens for article to review : %s", Counter(self.tokens(article.cleaned_text)))
        logger.debug("Text of the article to review : %s", article.cleaned_text)

        # Construct the url for the GET request
        base_url = "https://api.cognitive.microsoft.com/bing/v7.0/news/search"
        params = {
            "q": title,
            "sortBy": "date",
        }

        if article.publish_datetime_utc is not None:
            params['since'] = (article.publish_datetime_utc - datetime.timedelta(days=7)).timestamp()
            logger.debug("Added since param")

        response = requests.get(
            url=base_url,
            params=params,
            headers={
                "Ocp-Apim-Subscription-Key": os.getenv("BING_SEARCH_API_KEY"),
            },
        )

        if response.status_code == 200:
            data = response.json()
        else:
            data = {'value': []}

        nb_articles = 0
        nb_interesting_articles = 0
        dict_interesting_articles = {}

        # Look for similar articles' url
        for link in data['value']:
            linked_url = link['url']
            logger.debug("Found URL: %s", linked_url)

            if parsed_uri.netloc not in linked_url:
                logger.debug("Parsing article: %s", linked_url)
                try:
                    linked_article = g.extract(url=linked_url)
                    logger.debug("Name of the article: %s", linked_article.title)
                    logger.debug("Pubication date: %s", linked_article.publish_datetime_utc)
                    logger.debug(Counter(self.tokens(linked_article.cleaned_text)))
                    new_article_counter = Counter(self.tokens(linked_article.cleaned_text))
                    shared_items = {k for k in article_counter if k in new_article_counter}
                    logger.debug("Length of same words : %s", len(shared_items))
                    if len(shared_items) > 20:
                        nb_interesting_articles += 1
                        dict_interesting_articles[linked_url] = linked_article.title
                    nb_articles += 1
                except (ValueError, LookupError) as e:
                    logger.error("Found page that can't be processed : %s", linked_url)
                    logger.error("Error message : %s", e)

        if nb_articles == 0:
            content_score = 0
        else:
            content_score = int(nb_interesting_articles / nb_articles * 1000) / 10

        logger.debug("Article score : {}".format(content_score))
        logger.debug("Interesting articles : {}".format(dict_interesting_articles))

        InterestingRelatedArticle.objects.filter(web_page=self).delete()
        for url, title in dict_interesting_articles.items():
            InterestingRelatedArticle.objects.create(title=title, url=url, web_page=self)

        self.content_score = content_score
        self.total_articles = nb_articles

        self.scores_version = WebPage.CURRENT_SCORES_VERSION
        self.save()
        return self

    def to_dict(self):
        fields_to_serialize = ['url', 'global_score', 'total_articles', 'site_score_articles_count']
        self_serialized = {field: getattr(self, field) for field in fields_to_serialize}

        scores = ['content_score', 'site_score']
        self_serialized['scores'] = {field: getattr(self, field) for field in scores}

        self_serialized['related_articles_selection'] = []
        tld_extract = tldextract.TLDExtract(
            cache_file='api/external_data/public_suffixes_list.dat',
            include_psl_private_domains=True
        )
        for article in self.interesting_related_articles.order_by('?')[:3]:
            url_extraction = tld_extract(article.url)
            base_domain = f"{url_extraction.domain}.{url_extraction.suffix}".lower()
            self_serialized['related_articles_selection'].append({
                'title': article.title,
                'url': article.url,
                'publisher': base_domain,
            })

        return self_serialized

    @classmethod
    def from_url(cls, url):
        existing = cls.objects.filter(url=url).first()

        if (existing
                and existing.scores_version == WebPage.CURRENT_SCORES_VERSION
                and existing.updated_at > timezone.now() - datetime.timedelta(days=7)):
            return existing

        elif not existing:
            tld_extract = tldextract.TLDExtract(
                cache_file='api/external_data/public_suffixes_list.dat',
                include_psl_private_domains=True
            )
            url_extraction = tld_extract(url)
            base_domain = f"{url_extraction.domain}.{url_extraction.suffix}".lower()
            logger.debug(f"Base domain found {base_domain}")
            existing = cls.objects.create(
                url=url,
                scores_version=WebPage.CURRENT_SCORES_VERSION,
                base_domain=base_domain,
                total_articles=0
            )

        return existing.compute_scores()

    def __str__(self):
        return self.url


class InterestingRelatedArticle(models.Model):
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=500)
    web_page = models.ForeignKey(WebPage, on_delete=models.CASCADE, related_name='interesting_related_articles')
