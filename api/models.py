# coding: utf8
import datetime
import logging
import os
import re
from collections import Counter
from urllib.parse import urlparse

import requests
import spacy
import tldextract
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from goose3 import Goose
from nltk.stem.snowball import SnowballStemmer
from requests.exceptions import InvalidSchema
from unidecode import unidecode

logger = logging.getLogger(__name__)


def get_related_articles(article):
    print("get1")
    title = article.title
    print("get2")
    logger.debug("Title of the article : %s", title)
    # Construct the url for the GET request
    base_url = "https://api.cognitive.microsoft.com/bing/v7.0/news/search"
    print("get3")
    params = {
        "q": title,
        "sortBy": "date",
    }
    print("get4")
    if article.publish_datetime_utc is not None:
        print("get5")
        params['since'] = (article.publish_datetime_utc - datetime.timedelta(days=7)).timestamp()
        print("get6")
        logger.debug("Added since param")
        print("get7")
    response = requests.get(
        url=base_url,
        params=params,
        headers={
            "Ocp-Apim-Subscription-Key": os.getenv("BING_SEARCH_API_KEY"),
        },
    )
    print("get8")
    if response.status_code == 200:
        print("get9")
        return response.json()

    return {'value': []}


class WebPage(models.Model):
    CURRENT_SCORES_VERSION = 12

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
    def interesting_related_articles_count(self):
        return self.interesting_related_articles.count()

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
        print("tockens1")
        root_words = []
        print("tockens2")
        stemmer = SnowballStemmer("french")
        print("tockens3")
        for i in range(len(text)):
            print("tockens4")
            root_words.append(stemmer.stem(text[i]))
            print("tockens5")
        return root_words

    @staticmethod
    def nouns(text, nlp):
        print("nouns1")
        nouns = []
        print("nouns2")
        # stop = get_stop_words('french')
        # list_nouns = ['NN', 'NNS', 'NNP', 'NNPS']
        articleWithoutSpecialCaracters = unidecode(text)
        print("nouns3")
        document = re.sub('[^A-Za-z .\-]+', ' ', articleWithoutSpecialCaracters)
        print("nouns4")
        document = ' '.join(document.split())
        print("nouns5")
        print("nouns6")
        nlp.remove_pipe('parser')
        print("nouns7")
        nlp.remove_pipe('ner')
        print("nouns8")
        doc = nlp(document)
        print("nouns9")
        # logger.debug("Words in the document : %s", [(w.text, w.pos_) for w in doc])
        nouns += [w.text for w in doc if ((w.pos_ == "NOUN" or w.pos_ == "PROPN") and len(w.text) > 1)]
        print("nouns10")
        return nouns

    def compute_scores(self):
        logger.debug("Start compute_scores")
        print("scores1")

        # Extract the title and the text of the article
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })
        print("scores2")
        try:
            article = g.extract(url=self.url)
        except InvalidSchema:
            message = f'Invalid schema for url {self.url}'
            logger.error(message)
            self.delete()
            return message
        print("scores3")

        # article_counter = Counter(self.tokens(article.cleaned_text))

        logger.debug("Text of the article : %s", article.cleaned_text)
        print("scores4")
        if article.cleaned_text == "":
            message = f'Oups, nous n\'avons pas pu extraire le texte de l\'article'
            logger.error(message)
            self.delete()
            return message
        print("scores5")

        nlp = spacy.load('fr')
        nouns_article = self.nouns(article.cleaned_text, nlp)
        print("scores6")
        counter_nouns_article = Counter(self.tokens(nouns_article))
        print("scores7")
        logger.debug("Nouns in the article : %s", counter_nouns_article)
        print("scores8")

        related_articles = get_related_articles(article)
        print("scores9")

        if related_articles["value"] == []:
            message = f'Cet article semble isolé, nous n\'avons trouvé aucun article en lien avec lui. Faites attention!'
            logger.error(message)
            self.delete()
            return message

        print("scores10")
        logger.debug("Articles found %s", related_articles)

        self._compute_content_score(counter_nouns_article, related_articles, nlp)
        print("scores11")

        self.scores_version = WebPage.CURRENT_SCORES_VERSION
        print("scores12")
        self.save()
        print("scores13")
        return self

    def _compute_content_score(self, counter_nouns_article, related_articles, nlp):
        nb_articles = 0
        interesting_articles = 0
        scores_new_articles = []
        dict_interesting_articles = {}
        print("compute1")
        parsed_uri = urlparse(self.url)
        print("compute2")
        logger.debug("URL parsed")
        g = Goose({
            'browser_user_agent': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:64.0) Gecko/20100101 Firefox/64.0"
        })
        print("compute3")

        counter_article = 0
        for word in counter_nouns_article:
            if counter_nouns_article[word] > 1:
                counter_article += 1
        print("compute4")
        logger.debug("Weight nouns article : %s", counter_article)
        # Look for similar articles' url
        for link in related_articles['value']:
            linked_url = link['url']
            print("compute5")
            logger.debug("Found URL: %s", linked_url)

            if parsed_uri.netloc not in linked_url:
                try:
                    linked_article = g.extract(url=linked_url)
                    print("compute6")
                    logger.debug("Name of the article: %s", linked_article.title)
                    print("compute7")
                    new_nouns_article = self.nouns(linked_article.cleaned_text, nlp)
                    print("compute8")
                    new_counter_nouns_articles = Counter(self.tokens(new_nouns_article))
                    print("compute9")
                    shared_items = [k for k in counter_nouns_article if
                                    k in new_counter_nouns_articles and counter_nouns_article[k] > 1]
                    print("compute10")
                    score_article = len(shared_items) / counter_article
                    print("compute11")
                    if score_article > 0.4:
                        print("compute12")
                        scores_new_articles.append(score_article)
                        print("compute13")
                        interesting_articles += 1
                        print("compute14")
                        dict_interesting_articles[linked_url] = linked_article.title
                        print("compute15")
                    else:
                        logger.debug("Too low score : %s", score_article)
                    nb_articles += 1
                    logger.debug("Percentage for new articles : %s", scores_new_articles)
                except (ValueError, LookupError) as e:
                    logger.error("Found page that can't be processed : %s", linked_url)
                    logger.error("Error message : %s", e)
        if len(related_articles['value']) <= 4:
            if nb_articles == 0:
                content_score = 0
            else:
                content_score = (interesting_articles / nb_articles * 1000) / 10
        else:
            if len(scores_new_articles) == 0:
                content_score = 0
            elif len(scores_new_articles) == 1:
                content_score = 10
            elif len(scores_new_articles) == 2:
                content_score = 30
            elif len(scores_new_articles) == 3:
                content_score = 50
            elif len(scores_new_articles) == 4 or len(scores_new_articles) == 5:
                content_score = 70
            else:
                content_score = 85
        logger.debug("Article score : {}".format(content_score))
        # logger.debug("Interesting articles : {}".format(dict_interesting_articles))
        self.content_score = content_score
        print("compute16")
        self.total_articles = nb_articles
        print("compute17")
        self._store_interesting_related_articles(dict_interesting_articles)
        print("compute18")

    def _store_interesting_related_articles(self, dict_interesting_articles):
        InterestingRelatedArticle.objects.filter(web_page=self).delete()
        for url, title in dict_interesting_articles.items():
            InterestingRelatedArticle.objects.create(title=title, url=url, web_page=self)

    def to_dict(self):
        fields_to_serialize = [
            'url', 'global_score', 'total_articles',
            'site_score_articles_count', 'interesting_related_articles_count'
        ]
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
