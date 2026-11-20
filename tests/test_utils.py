"""Unit тести спільних функцій API (api/utils.py, api/errors.py).

Функції перевіряються окремо від бази даних і вебсервера: вхідні дані -> результат або помилка.
Тести написано за схемою AAA (Arrange - Act - Assert).
"""
import pytest

from api.errors import ApiError
from api.utils import (check_email, check_number, check_phone, check_string, get_bool_arg,
                       get_enum_arg, get_float_arg, get_int_arg, get_json_body, normalize_phone,
                       raise_if_errors)


# ---------- check_string ----------

def test_check_string_trims_spaces():
    # Arrange
    errors = {}

    # Act
    value = check_string({'name': '  Олена  '}, 'name', errors)

    # Assert
    assert value == 'Олена'
    assert errors == {}


@pytest.mark.parametrize('data', [{}, {'name': None}])
def test_check_string_missing_required_field(data):
    errors = {}

    value = check_string(data, 'name', errors)

    assert value is None
    assert 'name' in errors


def test_check_string_missing_optional_field_is_not_error():
    errors = {}

    value = check_string({}, 'comment', errors, required=False)

    assert value is None
    assert errors == {}


@pytest.mark.parametrize('raw', ['', ' ', '   \t'])
def test_check_string_empty_or_blank_required(raw):
    errors = {}

    value = check_string({'name': raw}, 'name', errors)

    assert value is None
    assert 'name' in errors


@pytest.mark.parametrize('raw', [5, 3.14, True, ['a'], {'a': 1}])
def test_check_string_wrong_type(raw):
    errors = {}

    value = check_string({'name': raw}, 'name', errors)

    assert value is None
    assert errors['name'] == 'Має бути рядком'


@pytest.mark.parametrize('length, is_valid', [(1, True), (99, True), (100, True), (101, False)])
def test_check_string_max_length_boundary(length, is_valid):
    errors = {}

    value = check_string({'name': 'я' * length}, 'name', errors, max_len=100)

    assert (value is not None) == is_valid
    assert ('name' in errors) == (not is_valid)


# ---------- check_number ----------

@pytest.mark.parametrize('price', [0, 0.01, 95, 99.5, 1_000_000])
def test_check_number_accepts_valid(price):
    errors = {}

    value = check_number({'price': price}, 'price', errors)

    assert value == price
    assert errors == {}


@pytest.mark.parametrize('price', [-1, -0.01, '95', 'abc', True, False, float('nan'), float('inf'), [1]])
def test_check_number_rejects_invalid(price):
    errors = {}

    value = check_number({'price': price}, 'price', errors)

    assert value is None
    assert 'price' in errors


def test_check_number_missing_required():
    errors = {}

    value = check_number({}, 'price', errors)

    assert value is None
    assert errors['price'] == 'Поле обовʼязкове'


def test_check_number_missing_optional_is_not_error():
    errors = {}

    value = check_number({}, 'price', errors, required=False)

    assert value is None
    assert errors == {}


@pytest.mark.parametrize('number, is_valid', [(4, False), (5, True), (6, True)])
def test_check_number_custom_minimum_boundary(number, is_valid):
    errors = {}

    value = check_number({'n': number}, 'n', errors, minimum=5)

    assert (value is not None) == is_valid


# ---------- телефон ----------

@pytest.mark.parametrize('raw, expected', [
    ('+38 (050) 111-22-33', '+380501112233'),
    ('050 111 22 33', '0501112233'),
    ('+380501112233', '+380501112233'),
    ('(050)-111-22-33', '0501112233'),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    ('+38 (050) 111-22-33', '+380501112233'),
    ('0501112233', '0501112233'),
    ('1234567890', '1234567890'),            # межа знизу: 10 цифр
    ('+1234567890123', '+1234567890123'),    # межа зверху: 13 цифр
])
def test_check_phone_valid(raw, expected):
    errors = {}

    phone = check_phone({'phone': raw}, 'phone', errors)

    assert phone == expected
    assert errors == {}


@pytest.mark.parametrize('raw', ['123456789', '12345678901234', 'abc', '+38050ABC2233', '', '   '])
def test_check_phone_invalid(raw):
    errors = {}

    phone = check_phone({'phone': raw}, 'phone', errors)

    assert phone is None
    assert 'phone' in errors


def test_check_phone_missing_required():
    errors = {}

    assert check_phone({}, 'phone', errors) is None
    assert 'phone' in errors


# ---------- email ----------

@pytest.mark.parametrize('raw', ['olena@example.com', 'a@b.co', 'first.last+tag@mail.example.org'])
def test_check_email_valid(raw):
    errors = {}

    assert check_email({'email': raw}, 'email', errors) == raw
    assert errors == {}


@pytest.mark.parametrize('data', [{}, {'email': None}, {'email': ''}])
def test_check_email_is_optional(data):
    errors = {}

    assert check_email(data, 'email', errors) is None
    assert errors == {}


@pytest.mark.parametrize('raw', ['olena.example.com', 'olena@', '@example.com', 'olena@example', 'ol ena@example.com'])
def test_check_email_invalid(raw):
    errors = {}

    assert check_email({'email': raw}, 'email', errors) is None
    assert 'email' in errors


# ---------- raise_if_errors / ApiError ----------

def test_raise_if_errors_does_nothing_for_empty_dict():
    raise_if_errors({})   # виняток не очікується


def test_raise_if_errors_raises_400_with_details():
    errors = {'price': 'Має бути числом'}

    with pytest.raises(ApiError) as exc_info:
        raise_if_errors(errors)

    assert exc_info.value.status == 400
    assert exc_info.value.details == errors


@pytest.mark.parametrize('status', [400, 404, 405, 409, 415, 500])
def test_api_error_has_default_message(status):
    error = ApiError(status)

    assert error.status == status
    assert error.message
    assert error.details is None


def test_api_error_custom_message_and_details():
    error = ApiError(404, 'Клієнта не знайдено', {'id': '999'})

    assert error.message == 'Клієнта не знайдено'
    assert error.details == {'id': '999'}


# ---------- параметри запиту (потрібен контекст запиту Flask) ----------

def test_get_int_arg_returns_default_when_missing(app):
    with app.test_request_context('/'):
        assert get_int_arg('page', 1) == 1


def test_get_int_arg_reads_value(app):
    with app.test_request_context('/?page=7'):
        assert get_int_arg('page', 1) == 7


@pytest.mark.parametrize('query', ['page=abc', 'page=0', 'page=-3', 'page=1.5'])
def test_get_int_arg_invalid_values(app, query):
    with app.test_request_context('/?' + query):
        with pytest.raises(ApiError) as exc_info:
            get_int_arg('page', 1)
    assert exc_info.value.status == 400


@pytest.mark.parametrize('value, is_valid', [(0, False), (1, True), (100, True), (101, False)])
def test_get_int_arg_maximum_boundary(app, value, is_valid):
    with app.test_request_context('/?per_page=%d' % value):
        if is_valid:
            assert get_int_arg('per_page', 10, maximum=100) == value
        else:
            with pytest.raises(ApiError):
                get_int_arg('per_page', 10, maximum=100)


def test_get_enum_arg(app):
    with app.test_request_context('/?order=asc'):
        assert get_enum_arg('order', ('asc', 'desc'), 'desc') == 'asc'
    with app.test_request_context('/'):
        assert get_enum_arg('order', ('asc', 'desc'), 'desc') == 'desc'
    with app.test_request_context('/?order=up'):
        with pytest.raises(ApiError):
            get_enum_arg('order', ('asc', 'desc'), 'desc')


@pytest.mark.parametrize('raw, expected', [('true', 1), ('TRUE', 1), ('1', 1), ('false', 0), ('0', 0), ('', None)])
def test_get_bool_arg_valid(app, raw, expected):
    with app.test_request_context('/?available=' + raw):
        assert get_bool_arg('available') == expected


def test_get_bool_arg_missing_and_invalid(app):
    with app.test_request_context('/'):
        assert get_bool_arg('available') is None
    with app.test_request_context('/?available=maybe'):
        with pytest.raises(ApiError):
            get_bool_arg('available')


@pytest.mark.parametrize('raw, expected', [('10', 10.0), ('0', 0.0), ('99.5', 99.5), ('-5', -5.0)])
def test_get_float_arg_valid(app, raw, expected):
    with app.test_request_context('/?min_price=' + raw):
        assert get_float_arg('min_price') == expected


@pytest.mark.parametrize('raw', ['abc', 'nan', 'inf'])
def test_get_float_arg_invalid(app, raw):
    with app.test_request_context('/?min_price=' + raw):
        with pytest.raises(ApiError):
            get_float_arg('min_price')


# ---------- тіло запиту ----------

def test_get_json_body_returns_dict(app):
    with app.test_request_context('/', method='POST', json={'name': 'Чай'}):
        assert get_json_body() == {'name': 'Чай'}


def test_get_json_body_rejects_non_json_content_type(app):
    with app.test_request_context('/', method='POST', data='x', content_type='text/plain'):
        with pytest.raises(ApiError) as exc_info:
            get_json_body()
    assert exc_info.value.status == 415


def test_get_json_body_rejects_broken_json(app):
    with app.test_request_context('/', method='POST', data='{broken', content_type='application/json'):
        with pytest.raises(ApiError) as exc_info:
            get_json_body()
    assert exc_info.value.status == 400


@pytest.mark.parametrize('payload', [[1, 2], 'text', 42])
def test_get_json_body_rejects_non_object(app, payload):
    with app.test_request_context('/', method='POST', json=payload):
        with pytest.raises(ApiError) as exc_info:
            get_json_body()
    assert exc_info.value.status == 400
