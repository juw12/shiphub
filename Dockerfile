# shiphub: one small container. Works on Fly.io, Render, Railway or any Docker host.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    SHIPHUB_DATA_DIR=/data \
    SHIPHUB_DEMO=0 \
    TRUST_PROXY=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY static ./static

RUN useradd --create-home --uid 10001 shiphub \
    && mkdir -p /data \
    && chown shiphub:shiphub /data
USER shiphub

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=4)"

CMD ["python", "server.py", "--no-browser"]
