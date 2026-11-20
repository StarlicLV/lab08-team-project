import logging
import os
import sqlite3

from flask import Flask, render_template

import models
from api import register_api
from routes import register_blueprints

# Логи йдуть у stdout (їх видно в `docker compose logs`); рівень задається змінною LOG_LEVEL
log_level = logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(
    level=log_level if isinstance(log_level, int) else logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

app = Flask(__name__)
# Шлях до бази даних береться зі змінної середовища. У контейнері файл лежить у /app/data (це volume),
# а локально за замовчуванням створюється data/database.db поруч з app.py.
app.config['DATABASE'] = os.environ.get('DATABASE_PATH', os.path.join(app.root_path, 'data', 'database.db'))
# Потрібен для session (кошик) і flash-повідомлень. У робочому середовищі задається через змінну SECRET_KEY.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# Закриваємо з’єднання з БД після кожного запиту
app.teardown_appcontext(models.close_db)

# Підключаємо маршрути з папки routes/
register_blueprints(app)

# REST API (/api/v1, /api/v2) та JSON-обробники помилок для них
register_api(app)

# Створюємо директорію для бази даних і таблиці при запуску (безпечно: використовується IF NOT EXISTS).
# Викликається на рівні модуля (а не в блоці __main__), щоб база створювалась і під gunicorn.
database_dir = os.path.dirname(app.config['DATABASE'])
if database_dir:
    os.makedirs(database_dir, exist_ok=True)
with app.app_context():
    models.init_db()
app.logger.info('База даних: %s', app.config['DATABASE'])

# Асортимент кав'ярні: категорії, позиції та ціни (грн).
# Дані зберігаємо тут, а шаблон menu.html виводить їх циклом.
MENU = [
    {
        "id": "coffee",
        "title": "Кава",
        "icon": "☕",
        "items": [
            {"name": "Еспресо", "desc": "Класичний шот зі свіжообсмажених зерен.", "price": 55},
            {"name": "Американо", "desc": "Еспресо з гарячою водою, м'який і легкий.", "price": 60},
            {"name": "Капучино", "desc": "Еспресо з молоком і щільною молочною пінкою.", "price": 75},
            {"name": "Флет-вайт", "desc": "Подвійний еспресо з оксамитовим молоком.", "price": 85},
            {"name": "Фільтр-кава", "desc": "Альтернативне заварювання, яскравий смак зерна.", "price": 80},
        ],
    },
    {
        "id": "desserts",
        "title": "Десерти",
        "icon": "🍰",
        "items": [
            {"name": "Чізкейк", "desc": "Вершковий крем на пісочній основі з ягідним соусом.", "price": 120},
            {"name": "Шоколадний брауні", "desc": "Щільний, з горіхами та темним шоколадом.", "price": 95},
            {"name": "Панна-кота", "desc": "Вершкова, з ваніллю та соусом із сезонних ягід.", "price": 100},
            {"name": "Еклер", "desc": "Заварне тісто з ніжним кремом і глазур'ю.", "price": 70},
            {"name": "Яблучний штрудель", "desc": "Тонке тісто, яблука з корицею, кулька морозива.", "price": 110},
        ],
    },
    {
        "id": "bakery",
        "title": "Випічка",
        "icon": "🥐",
        "items": [
            {"name": "Мигдалевий круасан", "desc": "Хрусткий зовні, з кремом франжипан усередині.", "price": 85},
            {"name": "Круасан з маслом", "desc": "Класичний французький круасан, смачний теплим.", "price": 65},
            {"name": "Булочка з корицею", "desc": "М'яка, з пряною начинкою та вершковою глазур'ю.", "price": 60},
        ],
    },
    {
        "id": "other",
        "title": "Чай та інші напої",
        "icon": "🍵",
        "items": [
            {"name": "Чай (чорний / зелений)", "desc": "Листовий чай, чайничок на двох.", "price": 70},
            {"name": "Какао", "desc": "Густе, на молоці, зі зефірками.", "price": 80},
            {"name": "Лимонад дня", "desc": "Свіжі цитруси та м'ята, подаємо з льодом.", "price": 90},
        ],
    },
]


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/delivery')
def delivery():
    return render_template('delivery.html')


@app.route('/menu')
def menu():
    return render_template('menu.html', categories=MENU)


@app.route('/api-demo')
def api_demo():
    # Демонстраційна сторінка лабораторної 6: працює з REST API через fetch (JavaScript)
    return render_template('api-demo.html')


@app.route('/health')
def health():
    # Перевірка працездатності для Docker health check: застосунок відповідає і база даних доступна
    try:
        models.get_db().execute('SELECT 1')
        return {'status': 'healthy', 'database': 'connected'}, 200
    except sqlite3.Error as error:
        app.logger.error('Health check не пройдено: %s', error)
        return {'status': 'unhealthy', 'error': str(error)}, 500


if __name__ == '__main__':
    # host='0.0.0.0': приймати з'єднання ззовні контейнера (інакше сторінка в браузері не відкриється).
    # debug вмикається лише змінною FLASK_DEBUG=1 (автоперезапуск і детальні помилки, тільки для розробки).
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')
