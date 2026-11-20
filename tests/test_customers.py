"""Тести лабораторної роботи 07 — Учасник 3: клієнти та відгуки.

Unit тести (без БД і вебсервера):
    validate_customer      api/v1/customers.py
    validate_feedback      routes/feedback.py
    parse_quantity         routes/cart.py

Integration тести (тестовий клієнт Flask + тимчасова БД):
    /api/v1/customers      CRUD, 400 / 404 / 409 / 415, /customers/<id>/orders
    /api/v2/customers      пагінація, пошук, сортування, неправильні параметри, картка клієнта
    POST /feedback         форма відгуку з коректними й некоректними даними

Запуск з кореня проєкту:  pytest tests/test_customers.py -v
Усі тести написано за схемою AAA (Arrange - Act - Assert).
"""
import pytest

from api.errors import ApiError
from api.v1.customers import validate_customer
from routes.cart import parse_quantity
from routes.feedback import validate_feedback


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def client(tmp_path):
    """Тестовий клієнт із власною тимчасовою БД (робочий db.sqlite не змінюється).

    У новій БД є тестові дані з models.py: клієнти №1 (Олена Коваль, +380501112233)
    і №2 (Іван Петренко, +380672223344), 8 товарів, промокоди SWEET10 і WELCOME15.
    """
    from app import app as flask_app
    import models

    flask_app.config['TESTING'] = True
    flask_app.config['DATABASE'] = str(tmp_path / 'test.sqlite')
    with flask_app.app_context():
        models.init_db()
    with flask_app.test_client() as test_client:
        yield test_client


NEW_CUSTOMER = {'name': 'Марія Шевченко', 'phone': '+380931234567', 'email': 'maria@example.com'}


def make_order(client, customer_id=1, product_id=4, quantity=2):
    """Допоміжна функція: створює замовлення через API замовлень."""
    return client.post('/api/v1/orders', json={
        'customer_id': customer_id,
        'address': 'Київ, вул. Хрещатик 1',
        'items': [{'product_id': product_id, 'quantity': quantity}],
    })


# =====================================================================
# UNIT: validate_customer (api/v1/customers.py)
# =====================================================================

def test_validate_customer_valid_data_is_cleaned():
    # Arrange: телефон із пробілами, дужками й дефісами, імʼя з пробілами по краях
    data = {'name': '  Олена Коваль ', 'phone': '+38 (050) 111-22-33', 'email': 'olena@example.com'}

    # Act
    clean = validate_customer(data)

    # Assert: імʼя обрізано, телефон приведено до єдиного формату
    assert clean == {'name': 'Олена Коваль', 'phone': '+380501112233', 'email': 'olena@example.com'}


def test_validate_customer_email_is_optional():
    # Arrange
    data = {'name': 'Іван', 'phone': '0672223344'}

    # Act
    clean = validate_customer(data)

    # Assert
    assert clean['email'] is None


def test_validate_customer_empty_email_becomes_none():
    assert validate_customer({'name': 'Іван', 'phone': '0672223344', 'email': ''})['email'] is None


def test_validate_customer_missing_required_fields_reports_each_field():
    # Act
    with pytest.raises(ApiError) as error:
        validate_customer({})

    # Assert
    assert error.value.status == 400
    assert set(error.value.details) == {'name', 'phone'}


@pytest.mark.parametrize('name', ['', '   ', 'a' * 101, 123, ['Іван']])
def test_validate_customer_rejects_bad_name(name):
    with pytest.raises(ApiError) as error:
        validate_customer({'name': name, 'phone': '+380501112233'})

    assert 'name' in error.value.details


@pytest.mark.parametrize('name', ['A', 'a' * 100])
def test_validate_customer_name_length_boundaries_are_accepted(name):
    assert validate_customer({'name': name, 'phone': '+380501112233'})['name'] == name


@pytest.mark.parametrize('phone', [
    'abc',                    # не цифри
    '12345',                  # закороткий
    '123456789',              # 9 цифр — на одну менше мінімуму
    '12345678901234',         # 14 цифр — на одну більше максимуму
    '+38050111222a',          # літера всередині
    '', 380501112233, True,   # порожній рядок і не рядки
])
def test_validate_customer_rejects_bad_phone(phone):
    with pytest.raises(ApiError) as error:
        validate_customer({'name': 'Іван', 'phone': phone})

    assert 'phone' in error.value.details


@pytest.mark.parametrize('phone', ['0501112233', '+380501112233', '+38 050 111 22 33', '1234567890123'])
def test_validate_customer_accepts_good_phone(phone):
    assert validate_customer({'name': 'Іван', 'phone': phone})['phone']


@pytest.mark.parametrize('email', ['no-at-sign', 'a@b', '@b.com', 'a b@c.com'])
def test_validate_customer_rejects_bad_email(email):
    with pytest.raises(ApiError) as error:
        validate_customer({'name': 'Іван', 'phone': '+380501112233', 'email': email})

    assert 'email' in error.value.details


def test_validate_customer_partial_checks_only_given_fields():
    # PATCH: передано лише імʼя, тому phone і email не перевіряються й не повертаються
    assert validate_customer({'name': 'Нове імʼя'}, partial=True) == {'name': 'Нове імʼя'}


def test_validate_customer_partial_empty_body_returns_empty_dict():
    assert validate_customer({}, partial=True) == {}


def test_validate_customer_partial_still_rejects_bad_value():
    with pytest.raises(ApiError) as error:
        validate_customer({'phone': 'abc'}, partial=True)

    assert list(error.value.details) == ['phone']


# =====================================================================
# UNIT: validate_feedback (routes/feedback.py)
# =====================================================================

def feedback_form(**overrides):
    form = {'name': 'Олена', 'email': 'olena@example.com', 'message': 'Дуже смачна кава!'}
    form.update(overrides)
    return form


def test_validate_feedback_valid_form_has_no_errors():
    assert validate_feedback(feedback_form()) == {}


def test_validate_feedback_empty_form_gives_three_errors():
    # Arrange
    form = {'name': '', 'email': '', 'message': ''}

    # Act
    errors = validate_feedback(form)

    # Assert
    assert set(errors) == {'name', 'email', 'message'}


def test_validate_feedback_email_without_at_sign():
    assert 'email' in validate_feedback(feedback_form(email='olena.example.com'))


@pytest.mark.parametrize('field, length, is_valid', [
    ('name', 100, True),
    ('name', 101, False),
    ('message', 2000, True),
    ('message', 2001, False),
])
def test_validate_feedback_length_boundaries(field, length, is_valid):
    # Arrange: значення рівно на межі й на одиницю більше
    form = feedback_form(**{field: 'я' * length})

    # Act
    errors = validate_feedback(form)

    # Assert
    assert (field not in errors) == is_valid


@pytest.mark.parametrize('extra, is_valid', [(0, True), (1, False)])
def test_validate_feedback_email_max_length_254(extra, is_valid):
    # Arrange: email довжиною 254 символи (дозволено) і 255 (забагато)
    email = 'a' * (254 - len('@b.com') + extra) + '@b.com'

    # Act
    errors = validate_feedback(feedback_form(email=email))

    # Assert
    assert ('email' not in errors) == is_valid


# =====================================================================
# UNIT: parse_quantity (routes/cart.py)
# =====================================================================

@pytest.mark.parametrize('value, default, expected', [
    ('3', 1, 3),        # звичайне число з форми
    (' 4 ', 1, 4),      # пробіли по краях
    ('0', 1, 0),        # нуль не замінюється значенням за замовчуванням
    ('-5', 1, -5),      # знак зберігається (обмеження робить викликаюча функція)
    (7, 1, 7),          # вже число
    (None, 1, 1),       # поля немає у формі
    ('', 1, 1),         # порожнє поле
    ('abc', 2, 2),      # не число
    ('2.5', 1, 1),      # дробове значення не є цілим
])
def test_parse_quantity(value, default, expected):
    assert parse_quantity(value, default) == expected


# =====================================================================
# INTEGRATION: /api/v1/customers
# =====================================================================

def test_v1_list_customers_returns_seed_customers(client):
    # Act
    response = client.get('/api/v1/customers')

    # Assert
    assert response.status_code == 200
    customers = response.get_json()['customers']
    assert len(customers) == 2
    assert {c['name'] for c in customers} == {'Олена Коваль', 'Іван Петренко'}
    assert all(c['orders_count'] == 0 for c in customers)


def test_v1_get_customer(client):
    response = client.get('/api/v1/customers/1')

    assert response.status_code == 200
    assert response.get_json()['phone'] == '+380501112233'


def test_v1_get_unknown_customer_returns_404_json(client):
    response = client.get('/api/v1/customers/9999')

    assert response.status_code == 404
    assert response.get_json() == {'error': 'Клієнта не знайдено', 'status': 404}


def test_v1_create_customer_returns_201_and_location(client):
    # Act
    response = client.post('/api/v1/customers', json=NEW_CUSTOMER)

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body['name'] == 'Марія Шевченко'
    assert response.headers['Location'].endswith(f"/api/v1/customers/{body['id']}")
    assert client.get(f"/api/v1/customers/{body['id']}").status_code == 200


def test_v1_create_customer_normalizes_phone(client):
    response = client.post('/api/v1/customers', json={**NEW_CUSTOMER, 'phone': '+38 (093) 123-45-67'})

    assert response.status_code == 201
    assert response.get_json()['phone'] == '+380931234567'


def test_v1_create_customer_duplicate_phone_returns_409(client):
    # Arrange: телефон Олени з тестових даних
    body = {**NEW_CUSTOMER, 'phone': '+380501112233'}

    # Act
    response = client.post('/api/v1/customers', json=body)

    # Assert
    assert response.status_code == 409
    assert len(client.get('/api/v1/customers').get_json()['customers']) == 2


def test_v1_duplicate_phone_is_detected_after_normalization(client):
    # той самий номер, записаний іншим способом
    response = client.post('/api/v1/customers', json={**NEW_CUSTOMER, 'phone': '+38 (050) 111-22-33'})

    assert response.status_code == 409


def test_v1_create_customer_validation_error_returns_400_with_details(client):
    response = client.post('/api/v1/customers', json={'name': '', 'phone': 'abc'})

    assert response.status_code == 400
    body = response.get_json()
    assert body['status'] == 400
    assert set(body['details']) == {'name', 'phone'}


def test_v1_create_customer_not_json_returns_415(client):
    response = client.post('/api/v1/customers', data='name=Іван', content_type='text/plain')

    assert response.status_code == 415


def test_v1_create_customer_broken_json_returns_400(client):
    response = client.post('/api/v1/customers', data='{"name": ', content_type='application/json')

    assert response.status_code == 400


def test_v1_put_replaces_customer(client):
    response = client.put('/api/v1/customers/2', json=NEW_CUSTOMER)

    assert response.status_code == 200
    assert response.get_json()['name'] == 'Марія Шевченко'
    assert client.get('/api/v1/customers/2').get_json()['phone'] == '+380931234567'


def test_v1_put_requires_all_required_fields(client):
    response = client.put('/api/v1/customers/2', json={'name': 'Тільки імʼя'})

    assert response.status_code == 400
    assert 'phone' in response.get_json()['details']


def test_v1_put_unknown_customer_returns_404(client):
    assert client.put('/api/v1/customers/9999', json=NEW_CUSTOMER).status_code == 404


def test_v1_put_phone_of_another_customer_returns_409(client):
    # клієнт №2 намагається взяти телефон клієнта №1
    response = client.put('/api/v1/customers/2', json={**NEW_CUSTOMER, 'phone': '+380501112233'})

    assert response.status_code == 409


def test_v1_patch_changes_only_given_fields(client):
    # Act
    response = client.patch('/api/v1/customers/1', json={'name': 'Олена Іванівна Коваль'})

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body['name'] == 'Олена Іванівна Коваль'
    assert body['phone'] == '+380501112233'
    assert body['email'] == 'olena@example.com'


def test_v1_patch_keeping_own_phone_is_not_a_conflict(client):
    response = client.patch('/api/v1/customers/1', json={'phone': '+380501112233'})

    assert response.status_code == 200


def test_v1_patch_invalid_email_returns_400(client):
    response = client.patch('/api/v1/customers/1', json={'email': 'bad'})

    assert response.status_code == 400
    assert 'email' in response.get_json()['details']


def test_v1_patch_unknown_customer_returns_404(client):
    assert client.patch('/api/v1/customers/9999', json={'name': 'X'}).status_code == 404


def test_v1_delete_customer_without_orders(client):
    # Act
    response = client.delete('/api/v1/customers/2')

    # Assert: 204 без тіла, клієнта більше немає
    assert response.status_code == 204
    assert response.data == b''
    assert client.get('/api/v1/customers/2').status_code == 404


def test_v1_delete_customer_with_orders_returns_409(client):
    # Arrange: у клієнта №1 є замовлення
    assert make_order(client, customer_id=1).status_code == 201

    # Act
    response = client.delete('/api/v1/customers/1')

    # Assert: клієнт лишився
    assert response.status_code == 409
    assert client.get('/api/v1/customers/1').status_code == 200


def test_v1_delete_unknown_customer_returns_404(client):
    assert client.delete('/api/v1/customers/9999').status_code == 404


def test_v1_method_not_allowed_returns_json_405(client):
    response = client.post('/api/v1/customers/1', json={})

    assert response.status_code == 405
    assert response.get_json()['status'] == 405


def test_v1_customer_orders_empty_list(client):
    response = client.get('/api/v1/customers/1/orders')

    assert response.status_code == 200
    assert response.get_json() == {'customer_id': 1, 'orders': []}


def test_v1_customer_orders_contains_created_order(client):
    # Arrange: 2 × чізкейк (95 грн) = 190 грн
    order_id = make_order(client, customer_id=1, product_id=4, quantity=2).get_json()['id']

    # Act
    response = client.get('/api/v1/customers/1/orders')

    # Assert
    orders = response.get_json()['orders']
    assert [o['id'] for o in orders] == [order_id]
    assert orders[0]['total'] == 190
    assert client.get('/api/v1/customers/1').get_json()['orders_count'] == 1


def test_v1_customer_orders_unknown_customer_returns_404(client):
    assert client.get('/api/v1/customers/9999/orders').status_code == 404


# =====================================================================
# INTEGRATION: /api/v2/customers
# =====================================================================

def add_customers(client, count):
    """Створює count нових клієнтів: Клієнт 01, Клієнт 02, ..."""
    for i in range(1, count + 1):
        response = client.post('/api/v1/customers', json={
            'name': f'Клієнт {i:02d}', 'phone': f'+3805000000{i:02d}'})
        assert response.status_code == 201


def test_v2_list_has_data_and_meta_envelope(client):
    response = client.get('/api/v2/customers')

    assert response.status_code == 200
    body = response.get_json()
    assert len(body['data']) == 2
    assert body['meta'] == {'page': 1, 'per_page': 10, 'total': 2, 'pages': 1}


def test_v2_pagination_splits_results_into_pages(client):
    # Arrange: 2 клієнти з тестових даних + 5 нових = 7 клієнтів
    add_customers(client, 5)

    # Act
    page1 = client.get('/api/v2/customers?per_page=3&page=1').get_json()
    page3 = client.get('/api/v2/customers?per_page=3&page=3').get_json()

    # Assert: сторінки 3 + 3 + 1
    assert page1['meta'] == {'page': 1, 'per_page': 3, 'total': 7, 'pages': 3}
    assert len(page1['data']) == 3
    assert len(page3['data']) == 1


def test_v2_page_beyond_the_end_returns_empty_data(client):
    body = client.get('/api/v2/customers?page=99').get_json()

    assert body['data'] == []
    assert body['meta']['total'] == 2


def test_v2_search_by_name(client):
    body = client.get('/api/v2/customers?q=Олена').get_json()

    assert [c['name'] for c in body['data']] == ['Олена Коваль']
    assert body['meta']['total'] == 1


@pytest.mark.parametrize('query', ['Коваль', '0501112233', 'olena@'])
def test_v2_search_by_surname_phone_or_email(client, query):
    body = client.get('/api/v2/customers', query_string={'q': query}).get_json()

    assert [c['id'] for c in body['data']] == [1]


def test_v2_search_without_matches_returns_empty_list(client):
    body = client.get('/api/v2/customers?q=немаєтакого').get_json()

    assert body['data'] == []
    assert body['meta']['total'] == 0
    assert body['meta']['pages'] == 0


def test_v2_sort_by_name_ascending_and_descending(client):
    # Act
    asc = client.get('/api/v2/customers?sort=name&order=asc').get_json()['data']
    desc = client.get('/api/v2/customers?sort=name&order=desc').get_json()['data']

    # Assert
    assert [c['name'] for c in asc] == ['Іван Петренко', 'Олена Коваль']
    assert [c['name'] for c in desc] == ['Олена Коваль', 'Іван Петренко']


def test_v2_sort_by_orders_count(client):
    # Arrange: два замовлення в клієнта №2
    make_order(client, customer_id=2)
    make_order(client, customer_id=2)

    # Act
    data = client.get('/api/v2/customers?sort=orders_count&order=desc').get_json()['data']

    # Assert
    assert data[0]['id'] == 2
    assert data[0]['orders_count'] == 2


@pytest.mark.parametrize('query', [
    'page=0', 'page=-1', 'page=abc',
    'per_page=0', 'per_page=101', 'per_page=x',
    'sort=password', 'order=sideways',
])
def test_v2_bad_query_parameter_returns_400(client, query):
    response = client.get('/api/v2/customers?' + query)

    assert response.status_code == 400
    assert response.get_json()['status'] == 400


def test_v2_per_page_upper_boundary_is_accepted(client):
    response = client.get('/api/v2/customers?per_page=100')

    assert response.status_code == 200
    assert response.get_json()['meta']['per_page'] == 100


def test_v2_search_text_is_not_executed_as_sql(client):
    # спроба SQL-ін'єкції у параметрі q має трактуватися як звичайний текст
    response = client.get('/api/v2/customers', query_string={'q': "' OR 1=1 --"})

    assert response.status_code == 200
    assert response.get_json()['data'] == []


def test_v2_customer_card_with_orders_and_total_spent(client):
    # Arrange: чізкейк 95 грн: 2 шт = 190 грн, 1 шт = 95 грн
    make_order(client, customer_id=1, quantity=2)
    make_order(client, customer_id=1, quantity=1)

    # Act
    response = client.get('/api/v2/customers/1')

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body['orders_count'] == 2
    assert len(body['orders']) == 2
    assert body['total_spent'] == 285


def test_v2_total_spent_ignores_cancelled_orders(client):
    # Arrange: два замовлення по 190 грн, одне скасовано
    make_order(client, customer_id=1, quantity=2)
    cancelled_id = make_order(client, customer_id=1, quantity=2).get_json()['id']
    client.patch(f'/api/v1/orders/{cancelled_id}/status', json={'status': 'cancelled'})

    # Act
    body = client.get('/api/v2/customers/1').get_json()

    # Assert: скасоване в orders є, але в суму витрат не входить
    assert len(body['orders']) == 2
    assert body['total_spent'] == 190


def test_v2_customer_without_orders_has_zero_total_spent(client):
    body = client.get('/api/v2/customers/2').get_json()

    assert body['orders'] == []
    assert body['total_spent'] == 0


def test_v2_unknown_customer_returns_404(client):
    assert client.get('/api/v2/customers/9999').status_code == 404


# =====================================================================
# INTEGRATION: POST /feedback (форма відгуку на сайті)
# =====================================================================

def feedback_rows(client):
    """Читає таблицю feedback із тестової БД."""
    from app import app as flask_app
    from models import query_db
    with flask_app.app_context():
        return [dict(row) for row in query_db('SELECT * FROM feedback')]


def test_feedback_page_opens(client):
    response = client.get('/feedback')

    assert response.status_code == 200


def test_feedback_valid_form_is_saved_and_redirects(client):
    # Arrange
    form = {'name': 'Олена', 'email': 'olena@example.com', 'message': 'Дуже смачний чізкейк!'}

    # Act
    response = client.post('/feedback', data=form)

    # Assert: redirect після успішного POST і запис у БД
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/feedback')
    rows = feedback_rows(client)
    assert len(rows) == 1
    assert rows[0]['name'] == 'Олена'
    assert rows[0]['message'] == 'Дуже смачний чізкейк!'


def test_feedback_success_message_is_shown_after_redirect(client):
    response = client.post('/feedback', follow_redirects=True,
                           data={'name': 'Олена', 'email': 'olena@example.com', 'message': 'Дякую'})

    assert response.status_code == 200
    assert 'Дякуємо' in response.get_data(as_text=True)


def test_feedback_whitespace_is_trimmed_before_saving(client):
    client.post('/feedback', data={'name': '  Олена  ', 'email': ' olena@example.com ', 'message': '  Привіт  '})

    row = feedback_rows(client)[0]
    assert (row['name'], row['email'], row['message']) == ('Олена', 'olena@example.com', 'Привіт')


def test_feedback_empty_form_is_not_saved(client):
    # Act
    response = client.post('/feedback', data={'name': '', 'email': '', 'message': ''})

    # Assert: форма показана знову (200, без redirect), нічого не записано
    assert response.status_code == 200
    assert 'Вкажіть' in response.get_data(as_text=True)
    assert feedback_rows(client) == []


@pytest.mark.parametrize('form', [
    {'name': 'Олена', 'email': 'без-равлика', 'message': 'Привіт'},     # email без @
    {'name': 'Олена', 'email': 'olena@example.com', 'message': '   '},  # повідомлення з пробілів
    {'name': 'я' * 101, 'email': 'olena@example.com', 'message': 'Привіт'},   # занадто довге імʼя
    {'name': 'Олена', 'email': 'olena@example.com', 'message': 'я' * 2001},   # занадто довге повідомлення
])
def test_feedback_invalid_form_is_not_saved(client, form):
    response = client.post('/feedback', data=form)

    assert response.status_code == 200
    assert feedback_rows(client) == []


def test_feedback_invalid_form_keeps_entered_values(client):
    # користувач не має втрачати введений текст через помилку в одному полі
    response = client.post('/feedback', data={'name': 'Олена', 'email': 'bad', 'message': 'Мій текст відгуку'})

    html = response.get_data(as_text=True)
    assert 'Мій текст відгуку' in html
    assert 'Email має містити символ @.' in html


def test_feedback_missing_fields_are_treated_as_empty(client):
    # у запиті взагалі немає полів: сервер не повинен впасти (500)
    response = client.post('/feedback', data={})

    assert response.status_code == 200
    assert feedback_rows(client) == []
