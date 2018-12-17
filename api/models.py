# coding: utf8
import datetime
import logging
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from statistics import mean
from typing import List, Union
from urllib.parse import urlparse

import goose3
import requests
import spacy
import tldextract
from django.conf import settings
from django.db import models
from django.db.models import Avg, QuerySet
from django.utils import timezone
from goose3 import Goose
from nltk.stem.snowball import SnowballStemmer
from requests.exceptions import InvalidSchema, RequestException
from unidecode import unidecode

from api.exceptions import APIException

logger = logging.getLogger(__name__)

if settings.LOAD_NLP:
    logger.debug("loading NLP")
    nlp = spacy.load('fr')
    nlp.remove_pipe('parser')
    nlp.remove_pipe('ner')
    logger.debug("Finished loading NLP")


def get_related_articles(article, delay) -> dict:
    title = article.title
    logger.debug("Title of the article : %s", title)
    # Construct the url for the GET request
    base_url = "https://api.cognitive.microsoft.com/bing/v7.0/news/search"
    params = {
        "q": title,
        "sortBy": "date",
    }
    if article.publish_datetime_utc is not None:
        params['since'] = (article.publish_datetime_utc - datetime.timedelta(days=delay)).timestamp()
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


def extract_base_domain(url, tld_extract=None):
    if tld_extract is None:
        tld_extract = tldextract.TLDExtract(
            cache_file='api/external_data/public_suffixes_list.dat',
            include_psl_private_domains=True
        )
    url_extraction = tld_extract(url)
    return f"{url_extraction.domain}.{url_extraction.suffix}".lower()


class BaseDomain(models.Model):
    base_domain = models.CharField(max_length=250)

    @property
    def isolated_articles_count(self):
        return self.isolated_articles.count()

    @property
    def total_articles_count(self):
        return self.isolated_articles_count + self.web_pages.count()

    @property
    def isolated_articles_ratio(self):
        return self.isolated_articles_count / self.total_articles_count

    def __str__(self):
        return self.base_domain


class WebPage(models.Model):
    CURRENT_SCORES_VERSION = 14

    url = models.URLField(unique=True, max_length=500)
    content_score = models.PositiveIntegerField(blank=True, null=True)
    base_domain = models.ForeignKey(BaseDomain, on_delete=models.PROTECT, related_name='web_pages')
    scores_version = models.PositiveIntegerField()
    total_articles = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def _site_score_queryset(self) -> Union[QuerySet, List['WebPage']]:
        return (WebPage.objects
                .filter(scores_version=WebPage.CURRENT_SCORES_VERSION)
                .filter(base_domain=self.base_domain))

    @property
    def site_score_articles_count(self) -> int:
        return self._site_score_queryset().count()

    @property
    def interesting_related_articles_count(self) -> int:
        return self.interesting_related_articles.count()

    @property
    def site_score(self) -> float:
        raw_site_score = (self._site_score_queryset()
                          .aggregate(site_score=Avg('content_score'))
                          )['site_score']
        return int(raw_site_score * 10) / 10

    @property
    def isolated_articles_score(self):
        return int((1 - self.base_domain.isolated_articles_ratio) * 1000) / 10

    @property
    def global_score(self) -> float:
        # allows to focus on the content if the site is "serious" and to focus on the site otherwise
        final_score = (100 - self.site_score) / 100 * self.site_score + self.site_score * self.content_score / 100
        return int(final_score * 10) / 10

    @staticmethod
    def tokens(text) -> List[str]:
        root_words = []
        stemmer = SnowballStemmer("french")
        for i in range(len(text)):
            root_words.append(stemmer.stem(text[i]))
        return root_words

    @staticmethod
    def nouns(text) -> List[str]:
        nouns = []
        articleWithoutSpecialCaracters = unidecode(text)
        document = re.sub('[^A-Za-z .\-]+', ' ', articleWithoutSpecialCaracters)
        document = ' '.join(document.split())
        doc = nlp(document)
        nouns += [w.text for w in doc if ((w.pos_ == "NOUN" or w.pos_ == "PROPN") and len(w.text) > 1)]
        return nouns

    def compute_scores(self) -> 'WebPage':
        logger.debug("Start compute_scores")
        # Extract the title and the text of the article
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })
        try:
            article = g.extract(url=self.url)
        except InvalidSchema:
            self.delete()
            raise APIException.warning("Adresse invalide")
        except RequestException:
            self.delete()
            raise APIException.warning("Le site n'est pas joignable")

        # article_counter = Counter(self.tokens(article.cleaned_text))

        logger.debug("Text of the article : %s", article.cleaned_text)
        if article.cleaned_text == "":
            self.delete()
            raise APIException.warning("Oups, nous n'avons pas pu extraire le texte de l'article.")

        nouns_article = self.nouns(article.cleaned_text)
        counter_nouns_article = Counter(self.tokens(nouns_article))
        logger.debug("Nouns in the article : %s", counter_nouns_article)

        related_articles = get_related_articles(article, 7)

        only_same_publisher = self.check_same_publisher(related_articles)

        if not related_articles["value"] or only_same_publisher is True:
            logger.debug("No article found, try with a period of 30 days before publishing.")
            related_articles = get_related_articles(article, 30)

            only_same_publisher = self.check_same_publisher(related_articles)
            if not related_articles["value"] or only_same_publisher is True:
                isolated, created = IsolatedArticle.objects.get_or_create(url=self.url, base_domain=self.base_domain)
                self.delete()
                raise APIException.info("Cet article semble isolé, nous n'avons trouvé aucun article en lien avec lui. "
                                        "Faites attention!")

        logger.debug("Articles found %s", related_articles)

        counter_article = 0
        for word in counter_nouns_article:
            if counter_nouns_article[word] > 1:
                counter_article += 1
        logger.debug("Number of interesting nouns : %s", counter_article)

        if counter_article > 2:
            self._compute_content_score(counter_nouns_article, related_articles, counter_article, article)
        else:
            self.delete()
            raise APIException.warning("Notre méthode de calcul n'a pas pu fournir de résultat sur cet article.")

        self.scores_version = WebPage.CURRENT_SCORES_VERSION
        self.save()
        logger.info(f"Finished computing scores for article {self.url}")
        return self

    def check_same_publisher(self, related_articles: dict) -> bool:
        if not related_articles["value"]:
            return False

        only_same_publisher = True
        for article in related_articles["value"]:
            linked_url = article['url']
            parsed_uri = urlparse(self.url)
            if parsed_uri.netloc not in linked_url:
                only_same_publisher &= False

        return only_same_publisher

    def _compute_content_score(self, counter_nouns_article: Counter, related_articles: dict,
                               counter_article: int, article: goose3.article.Article) -> None:
        nb_articles = 0
        interesting_articles = 0
        scores_new_articles = []
        dict_interesting_articles = {}
        parsed_uri = urlparse(self.url)
        logger.debug("URL parsed")
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })
        blocked_counter = 0
        too_similar_counter = 0

        # Look for similar articles' url
        for link in related_articles['value']:
            linked_url = link['url']
            logger.debug("Found URL: %s", linked_url)

            if parsed_uri.netloc not in linked_url:
                try:
                    linked_article = g.extract(url=linked_url)
                    logger.debug("Name of the article: %s", linked_article.title)

                    if "You have been blocked" in linked_article.title:
                        logger.debug("Article 'You have been blocked' not considered")
                        blocked_counter += 1
                    elif SequenceMatcher(None, article.cleaned_text, linked_article.cleaned_text).ratio() > 0.3:
                        logger.debug("Article with content too similar not considered")
                        too_similar_counter += 1
                    else:
                        new_nouns_article = self.nouns(linked_article.cleaned_text)
                        new_counter_nouns_articles = Counter(self.tokens(new_nouns_article))
                        shared_items = [k for k in counter_nouns_article if
                                        k in new_counter_nouns_articles and counter_nouns_article[k] > 1]
                        score_article = len(shared_items) / counter_article
                        if score_article > 0.4:
                            scores_new_articles.append(score_article)
                            interesting_articles += 1
                            dict_interesting_articles[linked_url] = (linked_article.title, score_article)
                        else:
                            logger.debug("Too low score : %s", score_article)
                        nb_articles += 1
                        logger.debug("Percentage for new articles : %s", scores_new_articles)
                except (ValueError, LookupError, RequestException) as e:
                    logger.error("Found page that can't be processed : %s", linked_url)
                    logger.error("Error message : %s", e)

        # Calcul du score de l'article
        if nb_articles == 0:
            self.delete()
            message = ("Nous n'avons trouvé que des articles trop similaires au vôtre. "
                       "Il se peut qu'ils proviennent tous de la même source.")
            if blocked_counter > too_similar_counter:
                message = "Nous avons trouvé en majorité des articles dont nous n'avons pas pu extraire le contenu."
            raise APIException.info(message)
        elif interesting_articles == 0:
            content_score = 0
        else:
            content_score = ((int(interesting_articles / nb_articles * 1000) / 10)
                             + min(100.0, (int((mean(scores_new_articles) * 1.5) * 1000) / 10))) / 2

        logger.debug("Article score : {}".format(content_score))
        self.content_score = content_score
        self.total_articles = nb_articles
        self._store_interesting_related_articles(dict_interesting_articles)

    def _store_interesting_related_articles(self, dict_interesting_articles: dict) -> None:
        InterestingRelatedArticle.objects.filter(web_page=self).delete()
        tld_extract = tldextract.TLDExtract(
            cache_file='api/external_data/public_suffixes_list.dat',
            include_psl_private_domains=True
        )
        for url, (title, score) in dict_interesting_articles.items():
            score = int(score * 100)
            base_domain, created = BaseDomain.objects.get_or_create(base_domain=extract_base_domain(url, tld_extract))
            InterestingRelatedArticle.objects.create(
                title=title, url=url, score=score,
                web_page=self, base_domain=base_domain
            )

    def to_dict(self) -> dict:
        fields_to_serialize = [
            'url', 'global_score', 'total_articles',
            'site_score_articles_count', 'interesting_related_articles_count'
        ]
        self_serialized = {field: getattr(self, field) for field in fields_to_serialize}

        scores = ['content_score', 'site_score', 'isolated_articles_score']
        self_serialized['scores'] = {field: getattr(self, field) for field in scores}

        self_serialized['related_articles_selection'] = []
        tld_extract = tldextract.TLDExtract(
            cache_file='api/external_data/public_suffixes_list.dat',
            include_psl_private_domains=True
        )
        for article in self.interesting_related_articles.order_by('-score')[:3]:
            base_domain = extract_base_domain(article.url, tld_extract)
            self_serialized['related_articles_selection'].append({
                'title': article.title,
                'url': article.url,
                'publisher': base_domain,
            })

        return self_serialized

    @classmethod
    def from_url(cls, url: str) -> 'WebPage':
        existing = cls.objects.filter(url=url).first()

        if existing and existing.content_score is None:
            raise APIException.info('Cet article est en cours de traitement. Merci de réessayer dans quelques minutes.')

        if (existing
                and existing.scores_version == WebPage.CURRENT_SCORES_VERSION
                and existing.updated_at > timezone.now() - datetime.timedelta(days=7)):
            logger.info(f"Returning existing object for url {url}")
            return existing

        elif not existing:
            base_domain = extract_base_domain(url)
            logger.debug(f"Base domain found {base_domain}")
            domain, created = BaseDomain.objects.get_or_create(base_domain=base_domain)
            existing = cls.objects.create(
                url=url,
                scores_version=WebPage.CURRENT_SCORES_VERSION,
                base_domain=domain,
                total_articles=0
            )

        try:
            return existing.compute_scores()
        except APIException as e:
            raise e
        except Exception as e:
            existing.delete()
            raise APIException.error("Erreur lors du calcul du score.", internal_message=str(e))

    def __str__(self):
        return self.url


class InterestingRelatedArticle(models.Model):
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=500)
    score = models.PositiveIntegerField()
    web_page = models.ForeignKey(WebPage, on_delete=models.CASCADE, related_name='interesting_related_articles')
    base_domain = models.ForeignKey(BaseDomain, on_delete=models.PROTECT, related_name='interesting_related_articles')


class IsolatedArticle(models.Model):
    url = models.URLField(max_length=500, unique=True)
    base_domain = models.ForeignKey(BaseDomain, on_delete=models.PROTECT, related_name='isolated_articles')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
