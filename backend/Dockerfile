# FastAPI backend. Built and started by deployment/compose.yaml (profile "app").
# Camera packages (ultralytics, opencv) are left out: the backend disables camera routes without them,
# and a container on Windows cannot open the laptop webcam anyway.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/backend

COPY requirements.txt .
RUN grep -viE '^(ultralytics|opencv-python|pytest|pytest-asyncio)([=<>~ ]|$)' requirements.txt > runtime.txt \
    && pip install -r runtime.txt

COPY app ./app
COPY iot_core ./iot_core
COPY tools ./tools
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --system --uid 10001 iot && mkdir -p data && chown iot data
USER iot

EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
