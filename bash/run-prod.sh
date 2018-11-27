#!/bin/sh
yes yes | pipenv run python manage.py migrate && \
pipenv run python manage.py collectstatic --noinput && \
pipenv run gunicorn fake_news_detector_api.wsgi -b 0.0.0.0:8000 -t 600 -k gthread --threads 4 --log-file -
