# COMPON crawler service — built for long-running deployment on Unraid.
# Playwright chromium is baked in so per-org "browser" engine works out of the box.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY crawler_service/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY crawler_service /app/crawler_service

# Data lives on the mounted volume: DB + raw corpus
ENV CRAWLER_DATA_DIR=/data \
    CRAWLER_WEB_HOST=0.0.0.0 \
    CRAWLER_WEB_PORT=8055

VOLUME ["/data"]
EXPOSE 8055

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8055/healthz',timeout=5).status==200 else 1)"

CMD ["python", "-m", "crawler_service"]
