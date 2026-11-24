# Лабораторна робота 08 — звіт перевірки чекліста

Цей файл описує стан перевірки актуального Git-клону. Він не замінює фактичний запуск Docker: не заповнюйте результати контейнерних кроків припущеннями.

## Виконані перевірки в цьому середовищі

| Перевірка | Результат |
|---|---|
| Повний набір pytest | **633 passed, 18 subtests passed** |
| Синтаксис `compose.yaml` і `compose.dev.yaml` як YAML | обидва файли розібрані успішно; production містить `web`, `nginx`, `backup`, dev — `web` |
| Конфігурація backup-сервісу | запускає `python scripts/backup.py`, залежить від healthy `web`, монтує SQLite volume без `:ro`, зберігає копії в `./backups` |
| Flask через test client на тимчасовій SQLite-БД | `/health`, `/`, `/menu`, `/cart`, `/api/v1/products`, `/api-demo` → 200; порожній `/checkout` → 302; POST товару → 201, наступний GET → 200 |
| Backup і відновлення на хості | створено копію, змінено БД, відновлено зі знімка; початковий запис повернувся, `PRAGMA integrity_check` → `ok` |
| Розділення залежностей | pytest/pytest-cov винесені з runtime `requirements.txt` у dev-залежності; це прибирає інструменти тестування з Docker runtime-образу |
| Docker Compose runtime | не перевірено: Docker Desktop/CLI та WSL 2 не встановлені на цьому ПК |

Статична перевірка YAML не замінює `docker compose config`. Розмір образу, стани контейнерів, HTTP-відповіді через Nginx, restart policy, Docker-volume persistence і bind mount у dev позначаються як **не перевірено**. Скріншоти Docker-команд не створювались.

## Запуск чекліста після налаштування Docker Desktop

У PowerShell із кореня репозиторію:

```powershell
docker --version
docker compose version
docker run --rm hello-world
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Вставте згенерований ключ у `.env` замість `change-this-to-random-string`. Потім:

```powershell
docker compose config
docker compose -f compose.dev.yaml config
docker compose build
docker images flask_app:latest
docker compose up -d
docker compose ps
```

Зафіксуйте розмір `flask_app:latest` з виводу `docker images`. Перевірте через браузер `http://localhost/`, `/menu`, `/cart`, `/checkout`, `/api/v1/products`, `/api-demo` та `/health`. Health endpoint має повертати HTTP 200 і JSON зі статусом `healthy`.

## Дані, health, restart та логи

1. Створіть тестовий запис через сайт, наприклад відгук або замовлення.
2. Виконайте `docker compose down`, потім `docker compose up -d`; перевірте, що запис лишився.
3. Лише для демонстрації видалення даних виконайте `docker compose down -v`, потім `docker compose up -d`; перевірте, що база створилась заново. `down -v` видаляє volume з базою.
4. Перевірте перехід `starting` → `healthy` командою `docker compose ps`. Деталі: `docker inspect --format '{{json .State.Health}}' flask_app`.
5. Перевірте restart policy: `docker kill flask_app`, за кілька секунд — `docker compose ps` та `docker compose logs -f web`. Контейнер має відновитися.
6. Перевірте, що `docker compose logs -f web` показує запити й логи застосунку.

## Backup та відновлення

1. Перевірте перший файл у `backups/` і логи `docker compose logs --tail=50 backup`.
2. Для перевірки відновлення створіть резервну копію, змініть тестовий запис, зупиніть `web` і `backup`, підставте файл копії замість `<файл-копії>` у команду з README, запустіть сервіси та перевірте повернення даних.
3. Перевірте SQLite-копію через `PRAGMA integrity_check`; очікуване значення — `ok`.

Скрипт створює копію через SQLite Backup API та атомарне перейменування, а не через `cp`. Сервіс підключає volume БД без `:ro`; з'єднання джерела SQLite відкриває в режимі читання.

## Development і чистий клон

1. Запустіть `docker compose -f compose.dev.yaml up --build`; відкрийте `http://localhost:5000`.
2. Змініть текст сторінки у робочому коді й переконайтесь, що dev-сайт показує зміну без повторної збірки.
3. Для чистої перевірки виконайте `docker compose down -v`, клонуйте репозиторій у нову порожню папку, створіть `.env` із `.env.example`, задайте новий `SECRET_KEY`, виконайте `docker compose up --build -d` та відкрийте сайт.
4. Повторіть кроки persistence, health і backup на чистому клоні.

Збережіть фактичний вивід команд і скриншоти в `docs/img/`, а таблицю результатів оновіть після виконання. Для діагностики щонайменше п'ятьох реальних проблем є розділ `Troubleshooting` у `README.md`; записуйте тільки ті помилки, які справді траплялись.
