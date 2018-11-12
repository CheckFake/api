FROM python:3.6-alpine

RUN apk add --no-cache postgresql-libs git libffi-dev libxml2-dev libxslt-dev jpeg-dev && \
    apk add --no-cache --virtual .build-deps gcc musl-dev postgresql-dev tzdata && \
    cp /usr/share/zoneinfo/Europe/Paris /etc/localtime && \
    echo "Europe/Paris" >  /etc/timezone

WORKDIR /app
EXPOSE 8000
VOLUME /app/staticfiles

RUN pip3 install pipenv
COPY Pipfile Pipfile.lock ./
RUN pipenv install && apk del .build-deps

COPY . ./

CMD ["sh", "bash/run-prod.sh"]

HEALTHCHECK --interval=10s --timeout=10s CMD ["pipenv", "run", "python", "healthcheck.py"]

ENV DATABASE_URL postgres://postgresql:postgresql@db:5432/fake_news_detector
ENV SECRET_KEY ''
ENV MAILGUN_ACCESS_KEY ''
ENV MAILGUN_SERVER_NAME ''
ENV DJANGO_ENV ''
ENV ADMIN_EMAIL ''
ENV SERVER_EMAIL ''