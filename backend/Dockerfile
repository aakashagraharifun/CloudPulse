# CloudPulse API / worker image. The same image runs uvicorn, the Celery worker
# and Celery beat; docker-compose.yml chooses the command.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code changes do not invalidate the pip layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Never run the application as root inside the container.
RUN useradd --create-home --uid 10001 cloudpulse
USER cloudpulse

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
