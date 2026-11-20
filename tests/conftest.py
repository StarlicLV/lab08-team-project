"""Спільні fixtures для pytest (підключаються автоматично).

Кожен тест, який «замовляє» fixture app або client, працює з ВЛАСНОЮ порожньою тимчасовою базою
даних у директорії tmp_path. Робоча база db.sqlite під час тестів не змінюється.
"""
import pytest

import models
from app import app as flask_app


@pytest.fixture
def app(tmp_path):
    """Застосунок, підключений до тимчасової БД (таблиці та тестові дані створює models.init_db)."""
    original_database = flask_app.config['DATABASE']
    flask_app.config.update(TESTING=True, DATABASE=str(tmp_path / 'test.sqlite'))
    with flask_app.app_context():
        models.init_db()
    yield flask_app
    flask_app.config['DATABASE'] = original_database


@pytest.fixture
def client(app):
    """Тестовий клієнт Flask: надсилає запити без запуску справжнього сервера."""
    return app.test_client()
