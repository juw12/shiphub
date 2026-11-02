FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    VIBEHQ_DB=/data/vibehq.db \
    VIBEHQ_QUIET=0

# run as an unprivileged user; the database lives on a volume
RUN useradd --create-home --uid 10001 vibehq \
    && mkdir -p /data \
    && chown vibehq:vibehq /data

WORKDIR /app
COPY --chown=vibehq:vibehq server.py webpush.py stripe_client.py github_client.py backup.py ./
COPY --chown=vibehq:vibehq static ./static

USER vibehq
EXPOSE 8787
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)" || exit 1

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
