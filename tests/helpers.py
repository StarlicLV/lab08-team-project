"""Допоміжні функції для тестів (звичайні функції, не fixtures).

Використання в тестах:  from tests.helpers import assert_api_error, create_order
"""


def assert_api_error(response, status, field=None):
    """Перевіряє, що API повернув помилку у стандартному JSON-форматі {"error", "status", "details"}."""
    assert response.status_code == status
    assert response.is_json
    body = response.get_json()
    assert body['status'] == status
    assert isinstance(body['error'], str) and body['error']
    if field is not None:
        assert field in body.get('details', {})
    return body


def create_order(client, **overrides):
    """Створює замовлення через API (клієнт №1, 2 чізкейки). Поля можна змінити через overrides."""
    body = {
        'customer_id': 1,
        'address': 'Луцьк, вул. Лесі Українки 1',
        'items': [{'product_id': 4, 'quantity': 2}],
    }
    body.update(overrides)
    return client.post('/api/v1/orders', json=body)
