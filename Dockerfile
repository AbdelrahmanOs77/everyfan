# EveryFan backend: simulator + streaming + API. Build context = repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml .
COPY shared ./shared
COPY backend ./backend
COPY demo ./demo

# Bake the deterministic matches into the image (fast cold start), and refuse to build bad data.
RUN python -m backend.cli generate --all && python -m backend.cli validate --all

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    DATA_DIR=/app/data \
    DEMO_DIR=/app/demo \
    BUDGET_FILE=/tmp/everyfan_budget.json

RUN useradd --create-home --uid 10001 everyfan && chown -R everyfan /app
USER everyfan

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", "--ws-ping-interval", "20", "--timeout-graceful-shutdown", "10"]
