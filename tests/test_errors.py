"""Integration тести обробки помилок і загальної поведінки API (api/errors.py, api/__init__.py).

Запити надсилаються через тестовий клієнт Flask; кожен тест працює з власною тимчасовою базою даних
(fixture client). Тести написано за схемою AAA (Arrange - Act - Assert).
"""
import os

import pytest

import models
from tests.helpers import assert_api_error

BIG = '1' + '0' * 30   # число, яке не вміщується в INTEGER у SQLite


# ---------- точка входу та неіснуючі адреси ----------

def test_api_index_lists_versions(client):
    response = client.get('/api')

    assert response.status_code == 200
    assert response.get_json()['versions'] == {'v1': '/api/v1', 'v2': '/api/v2'}


@pytest.mark.parametrize('url', ['/api/qwe', '/api/v1/nothing', '/api/v2/customers/abc'])
def test_unknown_api_path_returns_json_404(client, url):
    response = client.get(url)

    assert_api_error(response, 404)


def test_unknown_site_page_stays_html(client):
    response = client.get('/no-such-page')

    assert response.status_code == 404
    assert 'html' in response.content_type
    assert not response.is_json


@pytest.mark.parametrize('method, url', [
    ('post', '/api/v1/customers/1'),
    ('put', '/api/v1/products'),
    ('patch', '/api/v1/products'),
    ('delete', '/api/v1/orders'),
])
def test_wrong_method_returns_json_405(client, method, url):
    response = getattr(client, method)(url)

    assert_api_error(response, 405)


# ---------- некоректне тіло запиту ----------

@pytest.mark.parametrize('url', ['/api/v1/products', '/api/v1/customers', '/api/v1/orders'])
def test_post_not_json_returns_415(client, url):
    response = client.post(url, data='name=x', content_type='text/plain')

    assert_api_error(response, 415)


@pytest.mark.parametrize('url', ['/api/v1/products', '/api/v1/customers', '/api/v1/orders'])
def test_post_broken_json_returns_400(client, url):
    response = client.post(url, data='{broken', content_type='application/json')

    assert_api_error(response, 400)


@pytest.mark.parametrize('payload', [[1, 2, 3], 'text', 42])
def test_post_json_that_is_not_object_returns_400(client, payload):
    response = client.post('/api/v1/customers', json=payload)

    assert_api_error(response, 400)


def test_validation_error_contains_details_per_field(client):
    response = client.post('/api/v1/customers', json={})

    body = assert_api_error(response, 400, 'name')
    assert isinstance(body['details'], dict)
    assert 'phone' in body['details']


# ---------- граничні випадки: надто великі числа ----------

@pytest.mark.parametrize('url', [
    '/api/v1/products/' + BIG,
    '/api/v1/customers/' + BIG,
    '/api/v1/customers/%s/orders' % BIG,
    '/api/v1/orders/' + BIG,
    '/api/v2/products/' + BIG,
    '/api/v2/customers/' + BIG,
])
def test_huge_id_returns_400_not_500(client, url):
    response = client.get(url)

    assert_api_error(response, 400)


@pytest.mark.parametrize('url', ['/api/v2/products?page=' + BIG, '/api/v2/customers?page=' + BIG])
def test_huge_page_number_returns_400(client, url):
    response = client.get(url)

    assert_api_error(response, 400)


def test_huge_id_in_delete_returns_400(client):
    response = client.delete('/api/v1/products/' + BIG)

    assert_api_error(response, 400)


# ---------- сайт не зачеплений обробниками API ----------

@pytest.mark.parametrize('url', ['/', '/menu', '/about', '/delivery', '/feedback', '/cart'])
def test_site_pages_still_return_html(client, url):
    response = client.get(url)

    assert response.status_code == 200
    assert 'html' in response.content_type


# ---------- тестова база даних ----------

def test_tests_use_temporary_database(app):
    database = app.config['DATABASE']

    assert os.path.basename(database) == 'test.sqlite'
    assert os.path.exists(database)


def test_isolation_created_customer_exists_only_in_this_test(client):
    # Arrange
    client.post('/api/v1/customers', json={'name': 'Тест', 'phone': '+380991112233'})

    # Act
    response = client.get('/api/v1/customers')

    # Assert
    assert len(response.get_json()['customers']) == len(models.SEED_CUSTOMERS) + 1


def test_isolation_next_test_starts_with_fresh_database(client):
    response = client.get('/api/v1/customers')

    assert len(response.get_json()['customers']) == len(models.SEED_CUSTOMERS)
