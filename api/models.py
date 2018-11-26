# coding: utf8
import datetime
import logging
import os
import re
from collections import Counter
from urllib.parse import urlparse
from unidecode import unidecode

import requests
import tldextract
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from goose3 import Goose
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import RegexpTokenizer
from requests.exceptions import InvalidSchema
from stop_words import get_stop_words
import spacy



logger = logging.getLogger(__name__)


def get_related_articles(article):
    title = article.title
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
        return response.json()

    return {'value': []}


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
        final_score = (100 - self.site_score) / 100 * self.site_score + self.site_score * self.content_score / 100
        return int(final_score * 10) / 10

    @staticmethod
    def tokens(text):
        root_words = []
        stemmer = SnowballStemmer("french")
        for i in range(len(text)):
            root_words.append(stemmer.stem(text[i]))
        return root_words

    @staticmethod
    def nouns(text):
        nouns = []
        #stop = get_stop_words('french')
        #list_nouns = ['NN', 'NNS', 'NNP', 'NNPS']
        articleWithoutSpecialCaracters = unidecode(text)
        document = re.sub('[^A-Za-z .\-]+', ' ', articleWithoutSpecialCaracters)
        document = ' '.join(document.split())
        nlp = spacy.load('fr')
        doc = nlp(document)
        #logger.debug("Words in the document : %s", [(w.text, w.pos_) for w in doc])
        nouns += [w.text for w in doc if ((w.pos_ == "NOUN" or w.pos_ == "PROPN") and len(w.text) > 1)]
        return nouns

    def compute_scores(self):
        logger.debug("Start compute_scores")

        # Extract the title and the text of the article
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })
        try:
            article = g.extract(url=self.url)
        except InvalidSchema:
            message = f'Invalid schema for url {self.url}'
            logger.error(message)
            self.delete()
            return message

        #article_counter = Counter(self.tokens(article.cleaned_text))

        nouns_article = self.nouns(article.cleaned_text)
        counter_nouns_article = Counter(self.tokens(nouns_article))
        logger.debug("Nouns in the article : %s", counter_nouns_article)

        related_articles = get_related_articles(article)
        logger.debug("Articles found %s", related_articles)

        self._compute_content_score(counter_nouns_article, related_articles)

        self.scores_version = WebPage.CURRENT_SCORES_VERSION
        self.save()
        return self

    def _compute_content_score(self, counter_nouns_article, related_articles):
        nb_articles = 0
        nb_interesting_articles = 0
        dict_interesting_articles = {}
        parsed_uri = urlparse(self.url)
        logger.debug("URL parsed")
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })

        counter_total_weight_nouns = 0
        for word in counter_nouns_article:
            if counter_nouns_article[word] > 1:
                counter_total_weight_nouns += counter_nouns_article[word]
        counter_new_weight_nouns = 0
        logger.debug("Weight nouns article : %s", counter_total_weight_nouns)
        # Look for similar articles' url
        for link in related_articles['value']:
            linked_url = link['url']
            logger.debug("Found URL: %s", linked_url)

            if parsed_uri.netloc not in linked_url:
                try:
                    linked_article = g.extract(url=linked_url)
                    logger.debug("Name of the article: %s", linked_article.title)
                    new_nouns_article = self.nouns(linked_article.cleaned_text)
                    new_counter_nouns_articles = Counter(self.tokens(new_nouns_article))
                    shared_items = [(k, counter_nouns_article[k]) for k in counter_nouns_article if k in new_counter_nouns_articles and counter_nouns_article[k] > 1]
                    #if len(shared_items) > 20:
                    #    logger.debug("Shared nouns : %s", shared_items)
                    #    nb_interesting_articles += 1
                    #    dict_interesting_articles[linked_url] = linked_article.title
                    #else:
                    #    logger.debug("Shared nouns but not enough: %s", shared_items)
                    #nb_articles += 1
                    for word, counter in shared_items:
                        counter_new_weight_nouns += counter
                    logger.debug("Value of the counter : %s", counter_new_weight_nouns)
                    nb_articles += 1
                    dict_interesting_articles[linked_url] = linked_article.title
                except (ValueError, LookupError) as e:
                    logger.error("Found page that can't be processed : %s", linked_url)
                    logger.error("Error message : %s", e)
        #TODO: pas de résultat --> résultat null
        if nb_articles == 0:
            content_score = 0
        else:
            content_score = int(counter_new_weight_nouns / (counter_total_weight_nouns * nb_articles) * 1000) / 10
        logger.debug("Article score : {}".format(content_score))
        #logger.debug("Interesting articles : {}".format(dict_interesting_articles))
        self.content_score = content_score
        self.total_articles = nb_articles
        self._store_interesting_related_articles(dict_interesting_articles)

    def _store_interesting_related_articles(self, dict_interesting_articles):
        InterestingRelatedArticle.objects.filter(web_page=self).delete()
        for url, title in dict_interesting_articles.items():
            InterestingRelatedArticle.objects.create(title=title, url=url, web_page=self)

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
