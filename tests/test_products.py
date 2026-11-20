"""Тести лабораторної роботи 07 — Учасник 1: товари.

Unit тести (без БД і вебсервера):
    validate_product      api/v1/products.py   (повна та часткова валідація, межі значень)
    product_to_dict       api/v1/products.py   (перетворення рядка БД у JSON-словник)
    _validate_product     routes/shop.py       (валідація HTML-форми адмінки)

Integration тести (тестовий клієнт Flask + тимчасова БД):
    /api/v1/products      список із фільтрами, GET, POST, PUT, PATCH, DELETE, 400 / 404 / 409 / 415
    /api/v2/products      пагінація, сортування, min_price / max_price, некоректні параметри
    /admin/products       додавання, редагування, перемикання й видалення товару через форми
    /menu                 меню з пошуком і фільтром за категорією

Важливо: validate_product НЕ повертає список помилок. Для коректних даних вона повертає
очищений словник, а для некоректних — кидає ApiError(400) з полем details (поле -> повідомлення).

Запуск з кореня проєкту:  pytest tests/test_products.py -v
Усі тести написано за схемою AAA (Arrange - Act - Assert).
"""
import pytest
from werkzeug.datastructures import MultiDict

from api.errors import ApiError
from api.v1.products import validate_product, product_to_dict
from routes.shop import _validate_product
from tests.helpers import assert_api_error, create_order

V1 = '/api/v1/products'
V2 = '/api/v2/products'
MISSING_ID = 999999
CHEESECAKE_ID = 4        # у тестовій БД: Чізкейк, 95 грн
SEEDED_COUNT = 8         # models.init_db() створює 8 товарів


# =====================================================================
# Fixtures і допоміжні функції
# =====================================================================

@pytest.fixture
def client(tmp_path):
    """Тестовий клієнт із власною тимчасовою БД (робочий db.sqlite не змінюється)."""
    from app import app as flask_app
    import models

    original_database = flask_app.config['DATABASE']
    flask_app.config['TESTING'] = True
    flask_app.config['DATABASE'] = str(tmp_path / 'test.sqlite')
    with flask_app.app_context():
        models.init_db()
    with flask_app.test_client() as test_client:
        yield test_client
    flask_app.config['DATABASE'] = original_database


def valid_data(**overrides):
    """Коректне тіло запиту для створення товару; поля можна змінити через overrides."""
    data = {
        'name': 'Тірамісу',
        'price': 120,
        'category': 'Десерти',
        'description': 'Класичний десерт',
        'is_available': True,
    }
    data.update(overrides)
    return data


def create_product(client, **overrides):
    """Створює товар через API й повертає його JSON."""
    response = client.post(V1, json=valid_data(**overrides))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()


def validation_details(data, partial=False):
    """Викликає validate_product для некоректних даних і повертає details з ApiError."""
    with pytest.raises(ApiError) as error:
        validate_product(data, partial=partial)
    assert error.value.status == 400
    return error.value.details


def form(**overrides):
    """Коректна форма адмінки (MultiDict, як request.form)."""
    data = {'name': 'Чай', 'description': 'Зелений', 'category': 'Напої',
            'price': '50', 'is_available': 'on'}
    data.update(overrides)
    return MultiDict(data)


class Row(dict):
    """Імітація рядка БД (sqlite3.Row): dict(row) працює так само."""


# =====================================================================
# UNIT: validate_product(data, partial=False)
# =====================================================================

def test_validate_product_valid_returns_clean_dict():
    # Arrange
    data = valid_data()
    # Act
    clean = validate_product(data)
    # Assert
    assert clean == {'name': 'Тірамісу', 'category': 'Десерти', 'price': 120.0,
                     'description': 'Класичний десерт', 'is_available': 1}


def test_validate_product_strips_whitespace():
    # Arrange
    data = valid_data(name='  Чай  ', category='\tНапої\n', description='  опис ')
    # Act
    clean = validate_product(data)
    # Assert
    assert clean['name'] == 'Чай'
    assert clean['category'] == 'Напої'
    assert clean['description'] == 'опис'


def test_validate_product_defaults_for_optional_fields():
    # Arrange: без description та is_available
    data = {'name': 'Чай', 'category': 'Напої', 'price': 10}
    # Act
    clean = validate_product(data)
    # Assert
    assert clean['description'] == ''
    assert clean['is_available'] == 1


def test_validate_product_price_is_converted_to_float():
    # Arrange
    data = valid_data(price=70)
    # Act
    clean = validate_product(data)
    # Assert
    assert isinstance(clean['price'], float)
    assert clean['price'] == 70.0


def test_validate_product_empty_data_reports_all_required_fields():
    # Arrange
    data = {}
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {'name', 'category', 'price'}


@pytest.mark.parametrize('field', ['name', 'category', 'price'])
def test_validate_product_required_field_missing(field):
    # Arrange
    data = valid_data()
    del data[field]
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {field}


@pytest.mark.parametrize('field', ['name', 'category'])
@pytest.mark.parametrize('value', ['', ' ', '   ', '\t\n'])
def test_validate_product_blank_string_is_error(field, value):
    # Arrange
    data = valid_data(**{field: value})
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {field}


@pytest.mark.parametrize('field', ['name', 'category'])
@pytest.mark.parametrize('value', [123, 1.5, True, [], {}])
def test_validate_product_string_field_must_be_string(field, value):
    # Arrange
    data = valid_data(**{field: value})
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {field}


@pytest.mark.parametrize('field', ['name', 'category'])
@pytest.mark.parametrize('length, is_valid', [(1, True), (99, True), (100, True), (101, False), (5000, False)])
def test_validate_product_name_category_length_boundaries(field, length, is_valid):
    # Arrange
    data = valid_data(**{field: 'а' * length})
    # Act
    if is_valid:
        result = validate_product(data)
    else:
        result = validation_details(data)
    # Assert
    if is_valid:
        assert len(result[field]) == length
    else:
        assert set(result) == {field}


@pytest.mark.parametrize('length, is_valid', [(0, True), (1, True), (1000, True), (1001, False)])
def test_validate_product_description_length_boundaries(length, is_valid):
    # Arrange
    data = valid_data(description='а' * length)
    # Act
    if is_valid:
        result = validate_product(data)
    else:
        result = validation_details(data)
    # Assert
    if is_valid:
        assert len(result['description']) == length
    else:
        assert set(result) == {'description'}


def test_validate_product_description_none_becomes_empty_string():
    # Arrange
    data = valid_data(description=None)
    # Act
    clean = validate_product(data)
    # Assert
    assert clean['description'] == ''


@pytest.mark.parametrize('price', [0, 0.0, 0.01, 9.99, 70, 99999.99, 10 ** 9, 1e300])
def test_validate_product_price_valid_values(price):
    # Arrange
    data = valid_data(price=price)
    # Act
    clean = validate_product(data)
    # Assert
    assert clean['price'] == float(price)


@pytest.mark.parametrize('price', [-0.01, -1, -1000, float('-inf'), float('inf'), float('nan')])
def test_validate_product_price_out_of_range(price):
    # Arrange
    data = valid_data(price=price)
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {'price'}


@pytest.mark.parametrize('price', ['70', 'abc', '', True, False, [], {}, None])
def test_validate_product_price_must_be_number(price):
    # Arrange
    data = valid_data(price=price)
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {'price'}


@pytest.mark.parametrize('value, expected', [(True, 1), (False, 0), (1, 1), (0, 0)])
def test_validate_product_is_available_accepts_bool_and_0_1(value, expected):
    # Arrange
    data = valid_data(is_available=value)
    # Act
    clean = validate_product(data)
    # Assert
    assert clean['is_available'] == expected


@pytest.mark.parametrize('value', ['true', 'false', 'yes', '1', 2, -1, 0.5, None, [], {}])
def test_validate_product_is_available_invalid(value):
    # Arrange
    data = valid_data(is_available=value)
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {'is_available'}


def test_validate_product_reports_several_errors_at_once():
    # Arrange
    data = valid_data(name='', price=-1, is_available='yes')
    # Act
    details = validation_details(data)
    # Assert
    assert set(details) == {'name', 'price', 'is_available'}


def test_validate_product_error_has_status_400_and_message():
    # Arrange
    data = {}
    # Act
    with pytest.raises(ApiError) as error:
        validate_product(data)
    # Assert
    assert error.value.status == 400
    assert error.value.message


# ---------- partial=True (PATCH) ----------

@pytest.mark.parametrize('data, expected', [
    ({'price': 10}, {'price': 10.0}),
    ({'name': ' Нова '}, {'name': 'Нова'}),
    ({'category': 'Інше'}, {'category': 'Інше'}),
    ({'is_available': False}, {'is_available': 0}),
    ({'description': 'Опис'}, {'description': 'Опис'}),
])
def test_validate_product_partial_returns_only_given_fields(data, expected):
    # Arrange: у data лише одне поле
    # Act
    clean = validate_product(data, partial=True)
    # Assert
    assert clean == expected


def test_validate_product_partial_empty_body_returns_empty_dict():
    # Arrange
    data = {}
    # Act
    clean = validate_product(data, partial=True)
    # Assert: порожній результат; помилку 400 «немає полів» формує endpoint PATCH
    assert clean == {}


@pytest.mark.parametrize('data, field', [
    ({'price': -5}, 'price'),
    ({'price': 'abc'}, 'price'),
    ({'name': ''}, 'name'),
    ({'category': '   '}, 'category'),
    ({'name': 'а' * 101}, 'name'),
    ({'is_available': 'yes'}, 'is_available'),
])
def test_validate_product_partial_still_checks_given_fields(data, field):
    # Arrange: дані передані, але некоректні
    # Act
    details = validation_details(data, partial=True)
    # Assert
    assert set(details) == {field}


def test_validate_product_partial_does_not_require_other_fields():
    # Arrange
    data = {'price': 1}
    # Act
    clean = validate_product(data, partial=True)
    # Assert
    assert 'name' not in clean
    assert 'category' not in clean


def test_validate_product_full_mode_requires_all_required_fields():
    # Arrange: те саме тіло, що в partial-тесті вище
    data = {'price': 1}
    # Act
    details = validation_details(data, partial=False)
    # Assert
    assert set(details) == {'name', 'category'}


# =====================================================================
# UNIT: product_to_dict(row)
# =====================================================================

def test_product_to_dict_converts_types():
    # Arrange
    row = Row(id=1, name='Тірамісу', price=120, category='Десерти',
              description='Опис', is_available=1)
    # Act
    result = product_to_dict(row)
    # Assert
    assert result == {'id': 1, 'name': 'Тірамісу', 'price': 120.0, 'category': 'Десерти',
                      'description': 'Опис', 'is_available': True}
    assert isinstance(result['price'], float)
    assert result['is_available'] is True


@pytest.mark.parametrize('raw, expected', [(1, True), (0, False)])
def test_product_to_dict_is_available_becomes_bool(raw, expected):
    # Arrange
    row = Row(id=1, price=10, is_available=raw)
    # Act
    result = product_to_dict(row)
    # Assert
    assert result['is_available'] is expected


def test_product_to_dict_does_not_modify_source_row():
    # Arrange
    row = Row(id=1, price=10, is_available=1)
    # Act
    product_to_dict(row)
    # Assert
    assert row == {'id': 1, 'price': 10, 'is_available': 1}


# =====================================================================
# UNIT: _validate_product(form) з routes/shop.py
# Повертає (дані, список_помилок), де дані = (name, description, price, category, is_available)
# =====================================================================

def test_shop_validate_valid_form():
    # Arrange
    data = form()
    # Act
    result, errors = _validate_product(data)
    # Assert
    assert errors == []
    assert result == ('Чай', 'Зелений', 50.0, 'Напої', 1)


def test_shop_validate_strips_whitespace():
    # Arrange
    data = form(name='  Чай  ', category='  Напої ', description='  x ')
    # Act
    (name, description, _price, category, _avail), errors = _validate_product(data)
    # Assert
    assert errors == []
    assert (name, description, category) == ('Чай', 'x', 'Напої')


@pytest.mark.parametrize('raw, expected', [('12.5', 12.5), ('12,5', 12.5), ('0', 0.0), ('0,01', 0.01),
                                           (' 7 ', 7.0), ('99999999', 99999999.0)])
def test_shop_validate_price_accepts_numbers_and_comma(raw, expected):
    # Arrange
    data = form(price=raw)
    # Act
    (_n, _d, price, _c, _a), errors = _validate_product(data)
    # Assert
    assert errors == []
    assert price == expected


@pytest.mark.parametrize('raw', ['-1', '-0.01', 'abc', '', '  ', '12abc', 'nan', 'inf', '-inf'])
def test_shop_validate_price_invalid(raw):
    # Arrange
    data = form(price=raw)
    # Act
    _result, errors = _validate_product(data)
    # Assert
    assert errors == ['Ціна має бути числом не менше нуля.']


@pytest.mark.parametrize('name', ['', '   ', '\t'])
def test_shop_validate_empty_name(name):
    # Arrange
    data = form(name=name)
    # Act
    _result, errors = _validate_product(data)
    # Assert
    assert errors == ['Назва не може бути порожньою.']


def test_shop_validate_collects_all_errors():
    # Arrange
    data = form(name='', price='abc')
    # Act
    _result, errors = _validate_product(data)
    # Assert
    assert len(errors) == 2


def test_shop_validate_empty_form():
    # Arrange
    data = MultiDict()
    # Act
    _result, errors = _validate_product(data)
    # Assert
    assert len(errors) == 2


@pytest.mark.parametrize('checkbox, expected', [({'is_available': 'on'}, 1), ({}, 0)])
def test_shop_validate_checkbox_is_available(checkbox, expected):
    # Arrange: чекбокс або передається, або відсутній у формі
    data = MultiDict({'name': 'Чай', 'price': '10', **checkbox})
    # Act
    (_n, _d, _p, _c, is_available), errors = _validate_product(data)
    # Assert
    assert errors == []
    assert is_available == expected


# =====================================================================
# INTEGRATION v1: читання та фільтри
# =====================================================================

def test_v1_list_returns_seeded_products(client):
    # Arrange: тестова БД містить 8 товарів
    # Act
    response = client.get(V1)
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert body['count'] == SEEDED_COUNT
    assert len(body['products']) == SEEDED_COUNT


def test_v1_list_item_has_expected_fields(client):
    # Arrange
    # Act
    item = client.get(V1).get_json()['products'][0]
    # Assert
    assert set(item) == {'id', 'name', 'description', 'price', 'category', 'is_available'}


def test_v1_list_is_ordered_by_id(client):
    # Arrange
    # Act
    ids = [p['id'] for p in client.get(V1).get_json()['products']]
    # Assert
    assert ids == sorted(ids)


def test_v1_get_seeded_product_cheesecake(client):
    # Arrange
    # Act
    response = client.get(f'{V1}/{CHEESECAKE_ID}')
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert 'Чізкейк' in body['name']
    assert body['price'] == 95


def test_v1_categories_endpoint(client):
    # Arrange
    create_product(client, category='УнікальнаКатегорія')
    # Act
    response = client.get(f'{V1}/categories')
    categories = response.get_json()['categories']
    # Assert
    assert response.status_code == 200
    assert 'УнікальнаКатегорія' in categories
    assert len(categories) == len(set(categories))
    assert categories == sorted(categories)


def test_v1_filter_by_category(client):
    # Arrange
    create_product(client, name='Фільтр-товар', category='УнікальнаКатегорія')
    # Act
    response = client.get(f'{V1}?category=УнікальнаКатегорія')
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert [p['name'] for p in body['products']] == ['Фільтр-товар']
    assert body['count'] == 1


def test_v1_filter_by_unknown_category_is_empty(client):
    # Arrange
    category = 'КатегоріїНеІснує'
    # Act
    response = client.get(f'{V1}?category={category}')
    # Assert
    assert response.status_code == 200
    assert response.get_json() == {'count': 0, 'products': []}


def test_v1_search_by_q(client):
    # Arrange
    create_product(client, name='Зюзябліксир')
    # Act
    response = client.get(f'{V1}?q=Зюзяблік')
    # Assert
    assert response.status_code == 200
    assert [p['name'] for p in response.get_json()['products']] == ['Зюзябліксир']


def test_v1_search_no_match_is_empty(client):
    # Arrange
    query = 'НіЧогоТакого'
    # Act
    response = client.get(f'{V1}?q={query}')
    # Assert
    assert response.status_code == 200
    assert response.get_json()['count'] == 0


def test_v1_search_is_safe_against_sql_injection(client):
    # Arrange: класичний рядок ін'єкції, параметри передаються через ?
    payload = "' OR '1'='1"
    # Act
    response = client.get(V1, query_string={'q': payload})
    # Assert
    assert response.status_code == 200
    assert response.get_json()['count'] == 0


def test_v1_filter_by_available_true(client):
    # Arrange
    hidden = create_product(client, name='Недоступний-товар', is_available=False)
    # Act
    response = client.get(f'{V1}?available=true')
    products = response.get_json()['products']
    # Assert
    assert response.status_code == 200
    assert products
    assert all(p['is_available'] is True for p in products)
    assert hidden['id'] not in [p['id'] for p in products]


def test_v1_filter_by_available_false(client):
    # Arrange
    hidden = create_product(client, name='Недоступний-товар', is_available=False)
    # Act
    response = client.get(f'{V1}?available=false')
    products = response.get_json()['products']
    # Assert
    assert response.status_code == 200
    assert [p['id'] for p in products] == [hidden['id']]


def test_v1_filter_combination_category_and_q(client):
    # Arrange
    create_product(client, name='Альфа', category='Група')
    create_product(client, name='Бета', category='Група')
    create_product(client, name='Альфа-інша', category='ІншаГрупа')
    # Act
    response = client.get(f'{V1}?category=Група&q=Альфа')
    # Assert
    assert [p['name'] for p in response.get_json()['products']] == ['Альфа']


@pytest.mark.parametrize('value', ['maybe', 'yes', '2', 'abc'])
def test_v1_filter_invalid_available_returns_400(client, value):
    # Arrange
    url = f'{V1}?available={value}'
    # Act
    response = client.get(url)
    # Assert
    assert_api_error(response, 400)


# =====================================================================
# INTEGRATION v1: POST
# =====================================================================

def test_v1_post_creates_product(client):
    # Arrange
    payload = valid_data()
    # Act
    response = client.post(V1, json=payload)
    body = response.get_json()
    # Assert
    assert response.status_code == 201
    assert body['name'] == 'Тірамісу'
    assert body['price'] == 120
    assert body['is_available'] is True
    assert 'id' in body


def test_v1_post_sets_location_header(client):
    # Arrange
    payload = valid_data()
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.headers['Location'].endswith(f"{V1}/{response.get_json()['id']}")


def test_v1_post_then_get_by_id(client):
    # Arrange
    created = create_product(client, name='Кава', price=80)
    # Act
    response = client.get(f"{V1}/{created['id']}")
    # Assert
    assert response.status_code == 200
    assert response.get_json() == created


def test_v1_post_increases_list_count(client):
    # Arrange
    before = client.get(V1).get_json()['count']
    # Act
    create_product(client)
    after = client.get(V1).get_json()['count']
    # Assert
    assert after == before + 1


def test_v1_post_minimal_payload_uses_defaults(client):
    # Arrange
    payload = {'name': 'Мінімум', 'category': 'Різне', 'price': 1}
    # Act
    response = client.post(V1, json=payload)
    body = response.get_json()
    # Assert
    assert response.status_code == 201
    assert body['description'] == ''
    assert body['is_available'] is True


def test_v1_post_ignores_unknown_and_id_fields(client):
    # Arrange: клієнт намагається задати id і зайве поле
    payload = valid_data(id=777, hacker='x')
    # Act
    response = client.post(V1, json=payload)
    body = response.get_json()
    # Assert
    assert response.status_code == 201
    assert body['id'] != 777
    assert 'hacker' not in body


def test_v1_post_strips_whitespace_in_name(client):
    # Arrange
    payload = valid_data(name='  Чай  ')
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.get_json()['name'] == 'Чай'


def test_v1_post_price_zero_is_allowed(client):
    # Arrange
    payload = valid_data(price=0)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.status_code == 201
    assert response.get_json()['price'] == 0


def test_v1_post_very_large_price_is_allowed(client):
    # Arrange
    payload = valid_data(price=10 ** 9)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.status_code == 201
    assert response.get_json()['price'] == 10 ** 9


def test_v1_post_unicode_and_emoji_name(client):
    # Arrange
    payload = valid_data(name='Кава ☕ «Лате»')
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.status_code == 201
    assert response.get_json()['name'] == 'Кава ☕ «Лате»'


def test_v1_post_sql_injection_in_name_is_stored_as_text(client):
    # Arrange
    evil = "x'); DROP TABLE products;--"
    # Act
    response = client.post(V1, json=valid_data(name=evil))
    count_after = client.get(V1).get_json()['count']
    # Assert: таблиця ціла, рядок збережено як звичайний текст
    assert response.status_code == 201
    assert response.get_json()['name'] == evil
    assert count_after == SEEDED_COUNT + 1


def test_v1_post_empty_body_returns_400(client):
    # Arrange
    payload = {}
    # Act
    response = client.post(V1, json=payload)
    # Assert
    body = assert_api_error(response, 400)
    assert set(body['details']) == {'name', 'category', 'price'}


@pytest.mark.parametrize('price', ['70', 'abc', None, True, -0.01, -1])
def test_v1_post_invalid_price_returns_400(client, price):
    # Arrange
    payload = valid_data(price=price)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert_api_error(response, 400, field='price')


@pytest.mark.parametrize('field', ['name', 'category', 'price'])
def test_v1_post_missing_required_field_returns_400(client, field):
    # Arrange
    payload = valid_data()
    del payload[field]
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert_api_error(response, 400, field=field)


def test_v1_post_error_contains_details_for_every_bad_field(client):
    # Arrange
    payload = valid_data(name='', price=-1)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    body = assert_api_error(response, 400)
    assert {'name', 'price'} <= set(body['details'])


@pytest.mark.parametrize('length, expected', [(100, 201), (101, 400)])
def test_v1_post_name_length_boundary(client, length, expected):
    # Arrange
    payload = valid_data(name='а' * length)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.status_code == expected


@pytest.mark.parametrize('length, expected', [(1000, 201), (1001, 400)])
def test_v1_post_description_length_boundary(client, length, expected):
    # Arrange
    payload = valid_data(description='а' * length)
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert response.status_code == expected


def test_v1_post_invalid_is_available_returns_400(client):
    # Arrange
    payload = valid_data(is_available='yes')
    # Act
    response = client.post(V1, json=payload)
    # Assert
    assert_api_error(response, 400, field='is_available')


def test_v1_post_failed_validation_does_not_create_product(client):
    # Arrange
    before = client.get(V1).get_json()['count']
    # Act
    client.post(V1, json=valid_data(price=-1))
    after = client.get(V1).get_json()['count']
    # Assert
    assert after == before


def test_v1_post_without_json_content_type_returns_415(client):
    # Arrange: тіло є, але Content-Type не JSON
    # Act
    response = client.post(V1, data='name=Чай', content_type='text/plain')
    # Assert
    assert_api_error(response, 415)


def test_v1_post_broken_json_returns_400(client):
    # Arrange
    broken = '{"name": "Чай", '
    # Act
    response = client.post(V1, data=broken, content_type='application/json')
    # Assert
    assert_api_error(response, 400)


@pytest.mark.parametrize('body', ['[]', '"text"', '42', 'null'])
def test_v1_post_json_not_an_object_returns_400(client, body):
    # Arrange
    # Act
    response = client.post(V1, data=body, content_type='application/json')
    # Assert
    assert_api_error(response, 400)


# =====================================================================
# INTEGRATION v1: PUT
# =====================================================================

def test_v1_put_replaces_product(client):
    # Arrange
    created = create_product(client)
    new_data = valid_data(name='Нова назва', price=200, category='Інше', description='Новий опис')
    # Act
    response = client.put(f"{V1}/{created['id']}", json=new_data)
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert body['id'] == created['id']
    assert (body['name'], body['price'], body['category'], body['description']) == \
        ('Нова назва', 200, 'Інше', 'Новий опис')


def test_v1_put_missing_optional_fields_resets_them(client):
    # Arrange: PUT — повна заміна, тож відсутні description/is_available скидаються
    created = create_product(client, description='Старий опис', is_available=False)
    payload = {'name': 'Нова', 'category': 'Інше', 'price': 5}
    # Act
    body = client.put(f"{V1}/{created['id']}", json=payload).get_json()
    # Assert
    assert body['description'] == ''
    assert body['is_available'] is True


def test_v1_put_is_persisted(client):
    # Arrange
    created = create_product(client)
    # Act
    client.put(f"{V1}/{created['id']}", json=valid_data(name='Збережено'))
    response = client.get(f"{V1}/{created['id']}")
    # Assert
    assert response.get_json()['name'] == 'Збережено'


def test_v1_put_invalid_returns_400_and_keeps_old_data(client):
    # Arrange
    created = create_product(client, name='Старе')
    # Act
    response = client.put(f"{V1}/{created['id']}", json=valid_data(price=-5))
    after = client.get(f"{V1}/{created['id']}").get_json()
    # Assert
    assert_api_error(response, 400, field='price')
    assert after['name'] == 'Старе'


def test_v1_put_missing_required_field_returns_400(client):
    # Arrange
    created = create_product(client)
    # Act
    response = client.put(f"{V1}/{created['id']}", json={'price': 10})
    # Assert
    body = assert_api_error(response, 400)
    assert {'name', 'category'} <= set(body['details'])


def test_v1_put_unknown_returns_404(client):
    # Arrange
    payload = valid_data()
    # Act
    response = client.put(f'{V1}/{MISSING_ID}', json=payload)
    # Assert
    assert_api_error(response, 404)


# =====================================================================
# INTEGRATION v1: PATCH
# =====================================================================

def test_v1_patch_updates_only_given_field(client):
    # Arrange
    created = create_product(client, name='Старе', price=100)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json={'price': 150})
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert body['price'] == 150
    assert body['name'] == 'Старе'
    assert body['category'] == created['category']


def test_v1_patch_toggle_availability(client):
    # Arrange
    created = create_product(client, is_available=True)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json={'is_available': False})
    # Assert
    assert response.status_code == 200
    assert response.get_json()['is_available'] is False


def test_v1_patch_multiple_fields(client):
    # Arrange
    created = create_product(client)
    # Act
    body = client.patch(f"{V1}/{created['id']}", json={'name': 'А', 'price': 1}).get_json()
    # Assert
    assert (body['name'], body['price']) == ('А', 1)


def test_v1_patch_price_zero_is_allowed(client):
    # Arrange
    created = create_product(client, price=100)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json={'price': 0})
    # Assert
    assert response.status_code == 200
    assert response.get_json()['price'] == 0


def test_v1_patch_empty_body_returns_400(client):
    # Arrange
    created = create_product(client)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json={})
    # Assert
    assert_api_error(response, 400)


def test_v1_patch_unknown_fields_only_returns_400(client):
    # Arrange: жодного допустимого поля
    created = create_product(client)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json={'colour': 'red'})
    # Assert
    assert_api_error(response, 400)


@pytest.mark.parametrize('payload, field', [
    ({'price': -1}, 'price'),
    ({'price': 'abc'}, 'price'),
    ({'name': ''}, 'name'),
    ({'is_available': 'yes'}, 'is_available'),
])
def test_v1_patch_invalid_value_returns_400(client, payload, field):
    # Arrange
    created = create_product(client)
    # Act
    response = client.patch(f"{V1}/{created['id']}", json=payload)
    # Assert
    assert_api_error(response, 400, field=field)


def test_v1_patch_unknown_returns_404(client):
    # Arrange
    payload = {'price': 10}
    # Act
    response = client.patch(f'{V1}/{MISSING_ID}', json=payload)
    # Assert
    assert_api_error(response, 404)


def test_v1_patch_without_json_returns_415(client):
    # Arrange
    created = create_product(client)
    # Act
    response = client.patch(f"{V1}/{created['id']}", data='price=1', content_type='text/plain')
    # Assert
    assert_api_error(response, 415)


# =====================================================================
# INTEGRATION v1: DELETE, 404, 405, 409
# =====================================================================

def test_v1_delete_removes_product(client):
    # Arrange
    created = create_product(client)
    # Act
    response = client.delete(f"{V1}/{created['id']}")
    after = client.get(f"{V1}/{created['id']}")
    # Assert
    assert response.status_code == 204
    assert response.data == b''
    assert after.status_code == 404


def test_v1_delete_decreases_list_count(client):
    # Arrange
    created = create_product(client)
    before = client.get(V1).get_json()['count']
    # Act
    client.delete(f"{V1}/{created['id']}")
    after = client.get(V1).get_json()['count']
    # Assert
    assert after == before - 1


def test_v1_delete_twice_second_returns_404(client):
    # Arrange
    created = create_product(client)
    client.delete(f"{V1}/{created['id']}")
    # Act
    response = client.delete(f"{V1}/{created['id']}")
    # Assert
    assert_api_error(response, 404)


def test_v1_delete_unknown_returns_404(client):
    # Arrange
    product_id = MISSING_ID
    # Act
    response = client.delete(f'{V1}/{product_id}')
    # Assert
    assert_api_error(response, 404)


@pytest.mark.parametrize('product_id', [MISSING_ID, 0, 10 ** 12])
def test_v1_get_unknown_returns_404(client, product_id):
    # Arrange
    url = f'{V1}/{product_id}'
    # Act
    response = client.get(url)
    # Assert
    body = assert_api_error(response, 404)
    assert 'Товар' in body['error']


@pytest.mark.parametrize('bad_id', ['abc', '1.5', '-1'])
def test_v1_non_integer_id_returns_404(client, bad_id):
    # Arrange: маршрут <int:product_id> не збігається з цими адресами
    url = f'{V1}/{bad_id}'
    # Act
    response = client.get(url)
    # Assert
    assert_api_error(response, 404)


def test_v1_unsupported_method_returns_405(client):
    # Arrange: на колекції немає DELETE
    # Act
    response = client.delete(V1)
    # Assert
    assert_api_error(response, 405)


def test_v1_delete_product_in_order_returns_409(client):
    # Arrange: замовлення з чізкейком (id 4), клієнт №1
    assert create_order(client).status_code == 201
    # Act
    response = client.delete(f'{V1}/{CHEESECAKE_ID}')
    # Assert
    body = assert_api_error(response, 409)
    assert 'hint' in body['details']


def test_v1_delete_409_keeps_product(client):
    # Arrange
    create_order(client)
    # Act
    client.delete(f'{V1}/{CHEESECAKE_ID}')
    after = client.get(f'{V1}/{CHEESECAKE_ID}')
    # Assert
    assert after.status_code == 200


def test_v1_product_in_order_can_be_disabled_instead_of_deleted(client):
    # Arrange
    create_order(client)
    # Act: порада з відповіді 409 — вимкнути товар через PATCH
    response = client.patch(f'{V1}/{CHEESECAKE_ID}', json={'is_available': False})
    # Assert
    assert response.status_code == 200
    assert response.get_json()['is_available'] is False


# =====================================================================
# INTEGRATION v2
# =====================================================================

def test_v2_list_has_data_and_meta(client):
    # Arrange
    # Act
    response = client.get(V2)
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert set(body) == {'data', 'meta'}
    assert body['meta']['total'] == SEEDED_COUNT
    assert len(body['data']) == SEEDED_COUNT


def test_v2_default_meta_values(client):
    # Arrange
    # Act
    meta = client.get(V2).get_json()['meta']
    # Assert
    assert meta == {'page': 1, 'per_page': 10, 'total': SEEDED_COUNT, 'pages': 1}


def test_v2_get_single_product_wrapped_in_data(client):
    # Arrange
    # Act
    response = client.get(f'{V2}/{CHEESECAKE_ID}')
    body = response.get_json()
    # Assert
    assert response.status_code == 200
    assert body['data']['id'] == CHEESECAKE_ID
    assert body['data']['price'] == 95


def test_v2_get_unknown_returns_404(client):
    # Arrange
    product_id = MISSING_ID
    # Act
    response = client.get(f'{V2}/{product_id}')
    # Assert
    assert_api_error(response, 404)


def test_v2_pagination_limits_items(client):
    # Arrange
    per_page = 3
    # Act
    body = client.get(f'{V2}?page=1&per_page={per_page}').get_json()
    # Assert
    assert len(body['data']) == per_page
    assert body['meta'] == {'page': 1, 'per_page': 3, 'total': SEEDED_COUNT, 'pages': 3}


def test_v2_pagination_second_page_differs(client):
    # Arrange
    query = 'per_page=3'
    # Act
    first = client.get(f'{V2}?page=1&{query}').get_json()['data']
    second = client.get(f'{V2}?page=2&{query}').get_json()['data']
    # Assert
    assert {p['id'] for p in first}.isdisjoint({p['id'] for p in second})


def test_v2_pagination_last_page_has_remainder(client):
    # Arrange: 8 товарів по 3 -> остання (3-тя) сторінка має 2
    # Act
    body = client.get(f'{V2}?page=3&per_page=3').get_json()
    # Assert
    assert len(body['data']) == SEEDED_COUNT - 6


def test_v2_pagination_page_beyond_last_is_empty(client):
    # Arrange
    # Act
    response = client.get(f'{V2}?page=99&per_page=3')
    # Assert
    assert response.status_code == 200
    assert response.get_json()['data'] == []


def test_v2_pagination_pages_cover_all_products_once(client):
    # Arrange
    ids = []
    # Act
    for page in (1, 2, 3):
        ids += [p['id'] for p in client.get(f'{V2}?page={page}&per_page=3').get_json()['data']]
    # Assert
    assert len(ids) == SEEDED_COUNT
    assert len(set(ids)) == SEEDED_COUNT


@pytest.mark.parametrize('per_page, expected_status', [(1, 200), (100, 200), (101, 400), (0, 400)])
def test_v2_per_page_boundaries(client, per_page, expected_status):
    # Arrange
    url = f'{V2}?per_page={per_page}'
    # Act
    response = client.get(url)
    # Assert
    assert response.status_code == expected_status


def test_v2_sort_by_price_ascending(client):
    # Arrange
    # Act
    prices = [p['price'] for p in client.get(f'{V2}?sort=price').get_json()['data']]
    # Assert
    assert prices == sorted(prices)


def test_v2_sort_by_price_descending(client):
    # Arrange
    # Act
    prices = [p['price'] for p in client.get(f'{V2}?sort=-price').get_json()['data']]
    # Assert
    assert prices == sorted(prices, reverse=True)


@pytest.mark.parametrize('field', ['id', 'name', 'price', 'category'])
def test_v2_sort_allowed_fields(client, field):
    # Arrange
    url = f'{V2}?sort={field}'
    # Act
    response = client.get(url)
    # Assert
    assert response.status_code == 200


@pytest.mark.parametrize('sort', ['description', 'unknown', '-unknown', 'price;DROP TABLE products'])
def test_v2_sort_not_in_whitelist_returns_400(client, sort):
    # Arrange: білий список полів захищає від SQL-ін'єкції через ORDER BY
    # Act
    response = client.get(V2, query_string={'sort': sort})
    still_there = client.get(V1).get_json()['count']
    # Assert
    assert_api_error(response, 400)
    assert still_there == SEEDED_COUNT


def test_v2_min_price_filter_includes_cheesecake(client):
    # Arrange: Чізкейк коштує 95
    # Act
    data = client.get(f'{V2}?min_price=90').get_json()['data']
    # Assert
    assert data
    assert all(p['price'] >= 90 for p in data)
    assert CHEESECAKE_ID in [p['id'] for p in data]


def test_v2_max_price_filter(client):
    # Arrange
    limit = 95
    # Act
    data = client.get(f'{V2}?max_price={limit}').get_json()['data']
    # Assert
    assert data
    assert all(p['price'] <= limit for p in data)


def test_v2_price_range_boundaries_are_inclusive(client):
    # Arrange: діапазон рівно по ціні Чізкейка
    # Act
    data = client.get(f'{V2}?min_price=95&max_price=95').get_json()['data']
    # Assert
    assert CHEESECAKE_ID in [p['id'] for p in data]
    assert all(p['price'] == 95 for p in data)


def test_v2_price_range_min_greater_than_max_is_empty(client):
    # Arrange
    # Act
    response = client.get(f'{V2}?min_price=500&max_price=10')
    # Assert
    assert response.status_code == 200
    assert response.get_json()['meta']['total'] == 0


def test_v2_filters_combine_with_pagination_meta(client):
    # Arrange
    # Act
    body = client.get(f'{V2}?min_price=0&per_page=2').get_json()
    # Assert: total рахує всі підходящі товари, а не лише сторінку
    assert len(body['data']) == 2
    assert body['meta']['total'] == SEEDED_COUNT


def test_v2_filter_by_category_and_search(client):
    # Arrange
    create_product(client, name='Особливий', category='ТестКат')
    # Act
    data = client.get(f'{V2}?category=ТестКат&q=Особ').get_json()['data']
    # Assert
    assert [p['name'] for p in data] == ['Особливий']


def test_v2_filter_available(client):
    # Arrange
    hidden = create_product(client, name='Прихований', is_available=False)
    # Act
    data = client.get(f'{V2}?available=false').get_json()['data']
    # Assert
    assert [p['id'] for p in data] == [hidden['id']]


@pytest.mark.parametrize('query', [
    'page=abc',
    'page=0',
    'page=-1',
    'page=1.5',
    'per_page=abc',
    'per_page=-5',
    'min_price=abc',
    'max_price=abc',
    'min_price=nan',
    'max_price=inf',
    'available=maybe',
])
def test_v2_invalid_params_return_400(client, query):
    # Arrange
    url = f'{V2}?{query}'
    # Act
    response = client.get(url)
    # Assert
    assert_api_error(response, 400)


def test_v2_v1_and_v2_return_same_product_data(client):
    # Arrange
    # Act
    v1 = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()
    v2 = client.get(f'{V2}/{CHEESECAKE_ID}').get_json()['data']
    # Assert
    assert v1 == v2


# =====================================================================
# INTEGRATION: адмінка товарів (HTML-форми, routes/shop.py)
# =====================================================================

def _product_by_name(client, name):
    products = client.get(V1).get_json()['products']
    return next((p for p in products if p['name'] == name), None)


def test_admin_page_opens_and_lists_products(client):
    # Arrange
    # Act
    response = client.get('/admin/products')
    # Assert
    assert response.status_code == 200
    assert 'Чізкейк' in response.get_data(as_text=True)


def test_admin_add_product_redirects_and_saves(client):
    # Arrange
    data = {'name': 'Адмін-товар', 'description': 'D', 'category': 'Різне',
            'price': '12,5', 'is_available': 'on'}
    # Act
    response = client.post('/admin/products/add', data=data)
    saved = _product_by_name(client, 'Адмін-товар')
    # Assert
    assert response.status_code == 302
    assert saved['price'] == 12.5
    assert saved['is_available'] is True


def test_admin_add_without_checkbox_creates_unavailable_product(client):
    # Arrange
    data = {'name': 'Вимкнений', 'price': '10', 'category': 'Різне'}
    # Act
    client.post('/admin/products/add', data=data)
    # Assert
    assert _product_by_name(client, 'Вимкнений')['is_available'] is False


@pytest.mark.parametrize('data', [
    {'name': '', 'price': '10', 'category': 'К'},
    {'name': 'Х', 'price': 'abc', 'category': 'К'},
    {'name': 'Х', 'price': '-1', 'category': 'К'},
    {},
])
def test_admin_add_invalid_does_not_save(client, data):
    # Arrange
    before = client.get(V1).get_json()['count']
    # Act
    response = client.post('/admin/products/add', data=data)
    after = client.get(V1).get_json()['count']
    # Assert: форма показується знову (200), товар не створено
    assert response.status_code == 200
    assert after == before


def test_admin_edit_product_updates_it(client):
    # Arrange
    data = {'name': 'Оновлений', 'description': '', 'category': 'Десерти', 'price': '99',
            'is_available': 'on'}
    # Act
    response = client.post(f'/admin/products/{CHEESECAKE_ID}/edit', data=data)
    updated = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()
    # Assert
    assert response.status_code == 302
    assert (updated['name'], updated['price']) == ('Оновлений', 99)


def test_admin_edit_invalid_keeps_old_data(client):
    # Arrange
    before = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()
    # Act
    response = client.post(f'/admin/products/{CHEESECAKE_ID}/edit',
                           data={'name': '', 'price': '-5', 'category': 'К'})
    after = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()
    # Assert
    assert response.status_code == 200
    assert after == before


def test_admin_edit_form_opens_for_existing_product(client):
    # Arrange
    # Act
    response = client.get(f'/admin/products/{CHEESECAKE_ID}/edit')
    # Assert
    assert response.status_code == 200


def test_admin_edit_unknown_product_redirects(client):
    # Arrange
    # Act
    response = client.get(f'/admin/products/{MISSING_ID}/edit')
    # Assert
    assert response.status_code == 302


def test_admin_toggle_flips_availability_twice(client):
    # Arrange
    start = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()['is_available']
    # Act
    client.post(f'/admin/products/{CHEESECAKE_ID}/toggle')
    middle = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()['is_available']
    client.post(f'/admin/products/{CHEESECAKE_ID}/toggle')
    end = client.get(f'{V1}/{CHEESECAKE_ID}').get_json()['is_available']
    # Assert
    assert middle is (not start)
    assert end is start


def test_admin_delete_removes_product(client):
    # Arrange
    created = create_product(client)
    # Act
    response = client.post(f"/admin/products/{created['id']}/delete")
    # Assert
    assert response.status_code == 302
    assert client.get(f"{V1}/{created['id']}").status_code == 404


def test_admin_delete_product_in_order_is_blocked(client):
    # Arrange
    create_order(client)
    # Act
    response = client.post(f'/admin/products/{CHEESECAKE_ID}/delete')
    # Assert: ON DELETE RESTRICT — товар лишається, користувач отримує повідомлення
    assert response.status_code == 302
    assert client.get(f'{V1}/{CHEESECAKE_ID}').status_code == 200


def test_admin_delete_requires_post(client):
    # Arrange
    # Act
    response = client.get(f'/admin/products/{CHEESECAKE_ID}/delete')
    # Assert
    assert response.status_code == 405


# =====================================================================
# INTEGRATION: меню (routes/shop.py)
# =====================================================================

def test_menu_shows_available_products(client):
    # Arrange
    # Act
    response = client.get('/menu')
    # Assert
    assert response.status_code == 200
    assert 'Чізкейк' in response.get_data(as_text=True)


def test_menu_hides_unavailable_products(client):
    # Arrange
    create_product(client, name='Прихований-у-меню', is_available=False)
    # Act
    html = client.get('/menu').get_data(as_text=True)
    # Assert
    assert 'Прихований-у-меню' not in html


def test_menu_search_finds_product(client):
    # Arrange
    create_product(client, name='Унікум-для-меню')
    # Act
    html = client.get('/menu?q=Унікум').get_data(as_text=True)
    # Assert
    assert 'Унікум-для-меню' in html
    assert 'Чізкейк' not in html


def test_menu_search_nothing_found_message(client):
    # Arrange
    query = 'НіЧогоТакого'
    # Act
    response = client.get(f'/menu?q={query}')
    # Assert
    assert response.status_code == 200
    assert 'Нічого не знайдено' in response.get_data(as_text=True)


def test_menu_filter_by_category(client):
    # Arrange
    create_product(client, name='Тільки-тут', category='ОкремаКатегорія')
    # Act
    html = client.get('/menu?category=ОкремаКатегорія').get_data(as_text=True)
    # Assert
    assert 'Тільки-тут' in html
    assert 'Чізкейк' not in html
