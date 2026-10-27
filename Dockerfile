FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 app
COPY --chown=app:app . .
RUN mkdir -p /app/private /app/public-media /app/staticfiles && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "35", "--max-requests", "1000", "--max-requests-jitter", "100", "--error-logfile", "-"]
