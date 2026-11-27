# ============ Етап 1: збірка залежностей ============
FROM python:3.13-slim AS builder

# Віртуальне середовище, яке потім скопіюємо у фінальний образ
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Спочатку лише requirements.txt — для кешування шару.
# gunicorn додається тут, тому requirements.txt правити не обов'язково.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn


# ============ Етап 2: фінальний образ ============
# Той самий базовий образ, що й у builder (без Alpine)
FROM python:3.13-slim

WORKDIR /app

# Окремий користувач без прав адміністратора.
# Каталоги для БД і резервних копій створюємо та віддаємо app ДО монтування
# named volumes — нові volumes успадкують права непривілейованого користувача.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/backups \
    && chown -R app:app /app

# Готове віртуальне середовище з етапу збірки
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/database.db

# Код застосунку (після встановлення залежностей)
COPY --chown=app:app . .

USER app

EXPOSE 5000

# У slim-образі немає curl/wget, тому перевірка через Python.
# Статус 5xx або відсутність відповіді = unhealthy.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request, urllib.error\ntry:\n    urllib.request.urlopen('http://localhost:5000/health', timeout=2)\nexcept urllib.error.HTTPError as e:\n    sys.exit(0 if e.code < 500 else 1)\nexcept Exception:\n    sys.exit(1)"]

# База даних створюється в app.py на рівні модуля (init_db), тому працює і під gunicorn.
# Production-запуск через gunicorn; логи йдуть у stdout (docker compose logs).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
