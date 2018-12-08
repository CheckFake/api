from django.test import TestCase

from api.models import WebPage


class WebPageTestCase(TestCase):
    def setUp(self):
        self.page = WebPage.objects.create(
            url="https://example.com/article",
            content_score=50,
            base_domain="example.com",
            scores_version=WebPage.CURRENT_SCORES_VERSION,
            total_articles=5
        )

    def test_check_same_publisher_one_same(self):
        related_articles = {
            "value": [
                {'url': 'https://example.com/otherarticle'}
            ]
        }
        self.assertTrue(self.page.check_same_publisher(related_articles))

    def test_check_same_publisher_two_same(self):
        related_articles = {
            "value": [
                {'url': 'https://example.com/otherarticle'},
                {'url': 'https://example.com/otherarticle2'},
            ]
        }
        self.assertTrue(self.page.check_same_publisher(related_articles))

    def test_check_same_publisher_two_others(self):
        related_articles = {
            "value": [
                {'url': 'https://toto.com/otherarticle'},
                {'url': 'https://toto.com/otherarticle2'},
            ]
        }
        self.assertFalse(self.page.check_same_publisher(related_articles))

    def test_check_same_publisher_one_same_one_other(self):
        related_articles = {
            "value": [
                {'url': 'https://example.com/otherarticle'},
                {'url': 'https://toto.com/otherarticle2'},
            ]
        }
        self.assertFalse(self.page.check_same_publisher(related_articles))

    def test_store_interesting_related_articles(self):
        interesting_articles = {
            'https://example.com/otherarticle': ("Other article", 0.45),
            'https://toto.com/otherarticle2': ("Other article 2", 0.806),
        }
        self.page._store_interesting_related_articles(interesting_articles)
        for article in self.page.interesting_related_articles.all():
            self.assertIn(article.url, interesting_articles)
            self.assertIn(article.title, map(lambda x: x[0], interesting_articles.values()))
            self.assertIn(article.score, map(lambda x: int(x[1] * 100), interesting_articles.values()))

    def test_store_one_interesting_related_article(self):
        interesting_url = 'https://toto.com/otherarticle2'
        interesting_title = "Other article 2"
        interesting_score = 0.816
        expected_score = 81
        interesting_articles = {
            interesting_url: (interesting_title, interesting_score),
        }
        self.page._store_interesting_related_articles(interesting_articles)
        self.assertEqual(self.page.interesting_related_articles.first().url, interesting_url)
        self.assertEqual(self.page.interesting_related_articles.first().title, interesting_title)
        self.assertEqual(self.page.interesting_related_articles.first().score, expected_score)

    def test_to_dict_url(self):
        result = self.page.to_dict()
        self.assertIn('url', result)
        self.assertEqual(result['url'], self.page.url)

    def test_to_dict_global_score(self):
        result = self.page.to_dict()
        self.assertIn('global_score', result)

    def test_to_dict_total_articles(self):
        result = self.page.to_dict()
        self.assertIn('total_articles', result)
        self.assertEqual(result['total_articles'], self.page.total_articles)

    def test_to_dict_site_score_articles_count(self):
        result = self.page.to_dict()
        self.assertIn('site_score_articles_count', result)
        self.assertEqual(result['site_score_articles_count'], self.page.site_score_articles_count)

    def test_to_dict_interesting_articles_count(self):
        result = self.page.to_dict()
        self.assertIn('interesting_related_articles_count', result)
        self.assertEqual(result['interesting_related_articles_count'], self.page.interesting_related_articles_count)

    def test_to_dict_scores(self):
        result = self.page.to_dict()
        self.assertIn('scores', result)
        self.assertIn('content_score', result["scores"])
        self.assertEqual(result['scores']['content_score'], self.page.content_score)
        self.assertIn('site_score', result["scores"])
        self.assertEqual(result['scores']['site_score'], self.page.site_score)

    def test_to_dict_related_articles_selection(self):
        interesting_url = 'https://toto.com/otherarticle2'
        interesting_title = "Other article 2"
        interesting_articles = {
            interesting_url: (interesting_title, 0.816),
        }
        self.page._store_interesting_related_articles(interesting_articles)
        result = self.page.to_dict()
        self.assertIn('related_articles_selection', result)
        self.assertIsInstance(result['related_articles_selection'], list)

        first = result['related_articles_selection'][0]
        self.assertIn('title', first)
        self.assertEqual(first['title'], interesting_title)
        self.assertIn('url', first)
        self.assertEqual(first['url'], interesting_url)
        self.assertIn('publisher', first)
        self.assertIn(first['publisher'], interesting_url)
