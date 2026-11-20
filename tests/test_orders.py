"""Тести учасника 2: валідація та API замовлень (схема AAA)."""
import pytest

from api.errors import ApiError
from api.v1.orders import is_int, validate_order
from routes.orders import normalize_phone, validate_checkout
from tests.helpers import assert_api_error, create_order


def valid_payload(**overrides):
    data = {
        'customer_id': 1,
        'address': 'Луцьк, вул. Лесі Українки 1',
        'items': [{'product_id': 4, 'quantity': 2}],
    }
    data.update(overrides)
    return data


def test_is_int_accepts_integer():
    # Arrange
    value = 3
    # Act
    result = is_int(value)
    # Assert
    assert result is True


@pytest.mark.parametrize('value', [True, False, 1.0, '1', None, [], {}])
def test_is_int_rejects_non_integer_and_bool(value):
    # Arrange
    # Act
    result = is_int(value)
    # Assert
    assert result is False


def test_validate_order_merges_duplicate_product_lines():
    # Arrange
    data = valid_payload(items=[
        {'product_id': 4, 'quantity': 2}, {'product_id': 4, 'quantity': 3},
    ])
    # Act
    customer_id, address, comment, promo_code, items = validate_order(data)
    # Assert
    assert (customer_id, address, comment, promo_code) == (1, 'Луцьк, вул. Лесі Українки 1', '', None)
    assert items == {4: 5}


@pytest.mark.parametrize('items', [[], None, 'not-a-list'])
def test_validate_order_rejects_empty_or_wrong_items(items):
    # Arrange
    data = valid_payload(items=items)
    # Act / Assert
    with pytest.raises(ApiError) as error:
        validate_order(data)
    assert error.value.status == 400
    assert 'items' in error.value.details


@pytest.mark.parametrize('quantity', [0, -1, 2**63, True, '2'])
def test_validate_order_rejects_invalid_quantity(quantity):
    # Arrange
    data = valid_payload(items=[{'product_id': 4, 'quantity': quantity}])
    # Act / Assert
    with pytest.raises(ApiError) as error:
        validate_order(data)
    assert error.value.status == 400
    assert 'items[0].quantity' in error.value.details


@pytest.mark.parametrize('product_id', ['4', 4.5, True, 0, -2])
def test_validate_order_rejects_non_integer_product_id(product_id):
    # Arrange
    data = valid_payload(items=[{'product_id': product_id, 'quantity': 1}])
    # Act / Assert
    with pytest.raises(ApiError) as error:
        validate_order(data)
    assert error.value.status == 400
    assert 'items[0].product_id' in error.value.details


def test_validate_order_accepts_quantity_one_and_large_integer():
    # Arrange
    data = valid_payload(items=[{'product_id': 4, 'quantity': 1},
                                {'product_id': 5, 'quantity': 10**9}])
    # Act
    result = validate_order(data)
    # Assert
    assert result[-1] == {4: 1, 5: 10**9}


@pytest.mark.parametrize(('raw', 'expected'), [
    ('+38 (050) 111-22-33', '+380501112233'),
    (' 067-222-33-44 ', '0672223344'),
])
def test_normalize_phone(raw, expected):
    # Arrange / Act
    result = normalize_phone(raw)
    # Assert
    assert result == expected


def test_validate_checkout_validates_without_database(monkeypatch):
    # Arrange
    monkeypatch.setattr('routes.orders.find_active_promo', lambda _code: None)
    form = {'name': 'Максим', 'phone': '+38 (050) 111-22-33', 'email': 'm@example.com',
            'address': 'Луцьк', 'comment': '', 'promo_code': ''}
    # Act
    errors, phone, promo = validate_checkout(form)
    # Assert
    assert errors == {}
    assert phone == '+380501112233'
    assert promo is None


def test_validate_checkout_reports_invalid_fields_without_database(monkeypatch):
    # Arrange
    monkeypatch.setattr('routes.orders.find_active_promo', lambda _code: None)
    form = {'name': '', 'phone': 'abc', 'email': 'bad-email', 'address': '',
            'comment': '', 'promo_code': 'MISSING'}
    # Act
    errors, phone, promo = validate_checkout(form)
    # Assert
    assert set(errors) == {'name', 'phone', 'email', 'address', 'promo_code'}
    assert phone == 'abc'
    assert promo is None


def test_api_create_order_with_sweet10_has_discount(client):
    # Arrange
    # Act
    response = create_order(client, promo_code='sweet10')
    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body['promo_code'] == 'SWEET10'
    assert body['discount'] == 19
    assert body['total'] == 171


def test_api_create_order_rejects_invalid_promo(client):
    # Arrange / Act
    response = create_order(client, promo_code='NOT-A-PROMO')
    # Assert
    assert_api_error(response, 400, 'promo_code')


@pytest.mark.parametrize('overrides,field', [
    ({'customer_id': 9999}, 'customer_id'),
    ({'items': [{'product_id': 9999, 'quantity': 1}]}, 'product_id'),
])
def test_api_create_order_rejects_unknown_or_unavailable_entities(client, overrides, field):
    # Arrange
    payload = valid_payload(**overrides)
    # Act
    response = client.post('/api/v1/orders', json=payload)
    # Assert
    assert_api_error(response, 404)


def test_api_create_order_rejects_unavailable_product(app, client):
    # Arrange
    with app.app_context():
        from models import get_db
        db = get_db()
        db.execute('UPDATE products SET is_available = 0 WHERE id = 1')
        db.commit()
    # Act
    response = client.post('/api/v1/orders', json=valid_payload(
        items=[{'product_id': 1, 'quantity': 1}]))
    # Assert
    assert_api_error(response, 400, 'items')


def test_api_order_with_multiple_lines_and_status_filter(client):
    # Arrange
    response = create_order(client, items=[
        {'product_id': 4, 'quantity': 1}, {'product_id': 5, 'quantity': 2},
    ])
    assert response.status_code == 201
    order_id = response.get_json()['id']
    # Act
    changed = client.patch(f'/api/v1/orders/{order_id}/status', json={'status': 'preparing'})
    filtered = client.get('/api/v1/orders?status=preparing').get_json()
    # Assert
    assert changed.status_code == 200
    assert len(changed.get_json()['items']) == 2
    assert filtered['count'] == 1
    assert filtered['orders'][0]['id'] == order_id


def test_api_patch_order_rejects_invalid_status(client):
    # Arrange
    order = create_order(client).get_json()
    # Act
    response = client.patch(f"/api/v1/orders/{order['id']}/status", json={'status': 'nonsense'})
    # Assert
    assert_api_error(response, 400, 'status')
