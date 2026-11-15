"""Cluster registry: addresses, Kubernetes contexts, external and CloudNativePG clusters.

Only the Kubernetes API is replaced by fakes; databases, the encrypted catalog and the
local port-forward are real.
"""

import base64
import json
import os
import socket
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from kajenn import AsgiServer
from psycopg import sql

from kajenn_dbmanager import kube
from kajenn_dbmanager.app import DbManagerApp
from kajenn_dbmanager.query_profiles import QueryError, cluster_reference, stored_connection


def test_cluster_reference_accepts_cnpg_and_external_addresses():
    assert cluster_reference({'context': 'gpkube', 'namespace': 'db', 'cluster': 'main-pg'}) == \
        {'context': 'gpkube', 'namespace': 'db', 'cluster': 'main-pg'}
    assert cluster_reference({'context': 'external', 'namespace': '', 'cluster': 'legacy'})
    for bad in [{'context': 'external', 'namespace': 'x', 'cluster': 'legacy'},
                {'context': 'gpkube', 'namespace': 'DB', 'cluster': 'main'},
                {'context': 'gpkube', 'namespace': 'db', 'cluster': 'main', 'extra': 1},
                {'context': 'gpkube', 'namespace': 'db', 'cluster': '../x'}]:
        with pytest.raises(QueryError):
            cluster_reference(bad)


def test_cluster_profile_stores_no_credentials():
    reference = {'context': 'gpkube', 'namespace': 'db', 'cluster': 'main'}
    assert stored_connection({'cluster': reference, 'dbname': 'shop'}) == \
        {'cluster': reference, 'dbname': 'shop'}
    with pytest.raises(QueryError):
        stored_connection({'cluster': reference, 'dbname': 'shop', 'password': 'x'})


def test_contexts_from_environment_and_certificate_requirement(monkeypatch):
    monkeypatch.setenv(kube.KUBE_CLUSTERS_ENV, 'not json')
    with pytest.raises(QueryError, match='JSON list'):
        kube.KubeContexts.from_environment()
    entries = [{'name': 'gpkube', 'server': 'https://k8s.example:6443', 'token': 'secret-token',
                'namespace': 'db', 'access': 'service'}]
    monkeypatch.setenv(kube.KUBE_CLUSTERS_ENV, json.dumps(entries))
    contexts = kube.KubeContexts.from_environment()
    assert contexts.describe() == [{'name': 'gpkube', 'kind': 'kubernetes', 'namespace': 'db',
                                    'access': 'service'}]
    assert 'secret-token' not in json.dumps(contexts.describe())
    with pytest.raises(QueryError, match='ca_data'):
        contexts.api('gpkube')
    with pytest.raises(QueryError, match='access'):
        kube.KubeContexts([{'name': 'x', 'access': 'direct'}])


def test_superuser_credentials_follow_the_cnpg_secret_order(monkeypatch):
    read = []

    class Secrets:
        def __init__(self, api):
            pass

        def read_namespaced_secret(self, name, namespace, **kwargs):
            read.append(name)
            if name != 'main-admin-password':
                raise kube.client.ApiException(status=404)
            encode = lambda text: base64.b64encode(text.encode()).decode()  # noqa: E731
            return type('Secret', (), {'data': {'username': encode('admin'),
                                                'password': encode('pw')}})()

    monkeypatch.setattr(kube.client, 'CoreV1Api', Secrets)
    assert kube.superuser_credentials(object(), 'db', 'main') == ('admin', 'pw')
    assert read == ['main-superuser', 'main-admin-password']


@pytest.fixture
def pg():
    if os.environ.get('GNR_TEST_PG_PASSWORD'):
        yield {'host': os.environ.get('GNR_TEST_PG_HOST', '127.0.0.1'),
               'port': int(os.environ.get('GNR_TEST_PG_PORT', '5432')),
               'user': os.environ.get('GNR_TEST_PG_USER', 'postgres'),
               'password': os.environ['GNR_TEST_PG_PASSWORD']}
    else:
        from testing.postgresql import Postgresql
        with Postgresql() as instance:
            dsn = instance.dsn()
            yield {'host': dsn['host'], 'port': int(dsn['port']), 'user': dsn['user']}


@pytest.fixture
def database(pg):
    name = 'cluster_' + uuid4().hex[:10]
    with psycopg.connect(**pg, dbname='postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with psycopg.connect(**pg, dbname=name, autocommit=True) as conn:
                conn.execute('CREATE TABLE item (id integer PRIMARY KEY, title text)')
            yield name
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('KAJENN_DBMANAGER_DB_DIR', str(tmp_path / 'db'))
    monkeypatch.setenv('KAJENN_DBMANAGER_STORAGE_KEY', Fernet.generate_key().decode())
    monkeypatch.delenv(kube.KUBE_CLUSTERS_ENV, raising=False)
    monkeypatch.delenv(kube.KUBECONFIG_ENV, raising=False)
    return AsgiServer(applications=[DbManagerApp]).application_at('')


def call(app, action, data, admin=True):
    return app.workbench.call(action, data, 'local', admin)


@pytest.mark.postgresql
def test_external_cluster_lists_databases_and_registers_a_profile(app, pg, database):
    with pytest.raises(QueryError, match='dbmanager_admin'):
        call(app, 'cluster_contexts', {}, admin=False)
    reference = call(app, 'cluster_external', {'name': 'legacy', 'connection': {
        key: pg[key] for key in ('host', 'port', 'user', 'password') if key in pg}})
    assert reference == {'context': 'external', 'namespace': '', 'cluster': 'legacy'}
    assert {'name': 'external', 'kind': 'external'} in call(app, 'cluster_contexts', {})['contexts']
    assert call(app, 'cluster_list', {'context': 'external'})['clusters'][0]['cluster'] == 'legacy'
    listed = call(app, 'cluster_databases', {'cluster': reference})['databases']
    assert database in {item['database'] for item in listed}
    saved = call(app, 'cluster_register', {'database': 'shop', 'cluster': reference,
                                           'dbname': database})
    assert saved['source'] == {'kind': 'cluster', **reference}
    structure = call(app, 'introspect', {'database': 'shop'})
    assert 'item' in json.dumps(structure)


class FakeContexts:
    """One Kubernetes context; the API client itself is never used by the patched calls."""

    def describe(self):
        return [{'name': 'lab', 'kind': 'kubernetes', 'namespace': 'db', 'access': 'port-forward'}]

    def entry(self, name):
        if name != 'lab':
            raise QueryError('Unknown Kubernetes context')
        return {'name': 'lab', 'namespace': 'db', 'access': 'port-forward'}

    def api(self, name):
        return object()

    def close(self):
        pass


@pytest.mark.postgresql
def test_cnpg_cluster_is_reached_through_a_local_forward(app, pg, database, monkeypatch):
    opened = []

    def opener(api, namespace, pod, port=5432):
        assert (namespace, pod) == ('db', 'main-1')

        def open_socket():
            opened.append(pod)
            return socket.create_connection((pg['host'], pg['port']))
        return open_socket

    monkeypatch.setattr(kube, 'cnpg_clusters', lambda api, namespace: [
        {'cluster': 'main', 'namespace': 'db', 'phase': 'Cluster in healthy state'}])
    monkeypatch.setattr(kube, 'cnpg_cluster', lambda api, namespace, name: {'primary_pod': 'main-1'})
    monkeypatch.setattr(kube, 'superuser_credentials',
                        lambda api, namespace, name: (pg['user'], pg.get('password', '')))
    monkeypatch.setattr(kube, 'pod_socket_opener', opener)
    app.clusters._contexts = FakeContexts()
    assert call(app, 'cluster_list', {'context': 'lab'})['clusters'][0]['cluster'] == 'main'
    reference = {'context': 'lab', 'namespace': 'db', 'cluster': 'main'}
    listed = call(app, 'cluster_databases', {'cluster': reference})['databases']
    assert database in {item['database'] for item in listed}
    call(app, 'cluster_register', {'database': 'cnpg_shop', 'cluster': reference, 'dbname': database})
    assert 'item' in json.dumps(call(app, 'introspect', {'database': 'cnpg_shop'}))
    assert opened and set(opened) == {'main-1'}
    # The stored profile holds the address only, never the cluster credentials.
    stored, _ = app._queries().catalog.load('cnpg_shop')
    assert stored == {'cluster': reference, 'dbname': database}
