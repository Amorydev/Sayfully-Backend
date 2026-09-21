FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
COPY . .
# collectstatic chỉ cần import settings: SECRET_KEY/DATABASE_URL giả, không chạm DB.
RUN SECRET_KEY=build-only DATABASE_URL=sqlite:///build.sqlite3 \
    python manage.py collectstatic --noinput && rm -f build.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://localhost:8000/health/ || exit 1
# gthread: lượt chat AI chờ LLM 5–20 s chỉ chiếm 1 thread thay vì cả worker;
# --timeout phải lớn hơn AI_TIMEOUT (30 s) cộng một lần thử lại model dự phòng.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "gthread", "--threads", "8", "--timeout", "90"]
