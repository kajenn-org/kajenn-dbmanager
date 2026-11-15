"""Workbench authorization, encrypted enrollment, and the actual Gramlot protocol."""

import json

import pytest
from asqueel_migration import JsonStructureProducer
from conftest import _request
from cryptography.fernet import Fernet
from kajenn import AsgiServer, Avatar
from kajenn.config.templates import DefaultConfiguration

from kajenn_dbmanager import operations
from kajenn_dbmanager.app import DbManagerApp
from kajenn_dbmanager.query_profiles import QueryError
from kajenn_dbmanager.query_sessions import QuerySessions


class WorkbenchSite(DefaultConfiguration):
    """The service under /dbmanager and, when Gramlot is installed, the workbench under /ui."""

    def applications_section(self, cfg):
        applications = cfg.applications()
        applications.application(code='db', mount='dbmanager', app_class=DbManagerApp)
        try:
            from kajenn_dbmanager.ui_app import DbManagerUI
        except ImportError:
            return
        applications.application(code='ui', mount='ui', app_class=DbManagerUI).request(body='raw')


def kajenn_mode(server):
    """Switch the service and the workbench to kajenn access mode."""
    for code in ('db', 'ui'):
        if code in server.applications:
            server.applications[code].access_mode = 'kajenn'


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    monkeypatch.setenv('KAJENN_DBMANAGER_DB_DIR', str(tmp_path / 'db'))
    monkeypatch.setenv('KAJENN_DBMANAGER_STORAGE_KEY', Fernet.generate_key().decode())
    monkeypatch.chdir(tmp_path)
    server = AsgiServer(config=WorkbenchSite, auth={'bearer': {
        'alice': {'token': 'test-alice', 'tags': ''},
        'bob': {'token': 'test-bob', 'tags': ''},
        'admin': {'token': 'test-admin', 'tags': 'dbmanager_admin'},
    }})
    app = server.application_at('dbmanager')
    catalog = app._queries().catalog
    catalog.save('demo', {'dbname': 'demo', 'password': 'private-password'}, users=['local', 'alice'])
    structure = JsonStructureProducer({'db': 'demo', 'schemas': [{'name': 'public',
        'tables': [{'name': 'customer', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'T'}, {'name': 'name', 'dtype': 'T'}]}]}]}).get_json_struct()
    monkeypatch.setattr(operations, 'introspect', lambda _: structure)
    return server, app


def call(app, action, data=None, owner='local', admin=True):
    return app._workbench.call(action, data or {'database': 'demo'}, owner, admin)


def bearer(identity):
    return [(b'authorization', f'Bearer test-{identity}'.encode())]


def test_enrollment_preserves_inheritance_and_rejects_stale_edits(workbench):
    _, app = workbench
    with pytest.raises(QueryError, match='Complete database enrollment'):
        call(app, 'open_session')
    prepared = call(app, 'prepare')['guide']
    entry = prepared['tables']['public.customer']
    assert entry['privacy'] == 'H'
    assert entry['columns']['name'] == {}
    entry['columns']['id'] = {'privacy': None}
    entry['description'] = 'Customers'
    data = {'database': 'demo', 'tables': prepared['tables'], 'notes': 'Use invoice dates',
            'revision': prepared['revision'], 'approve': True}
    saved = call(app, 'save_guide', data)['guide']
    assert saved['status'] == 'ready'
    assert saved['tables']['public.customer']['columns']['id']['privacy'] is None
    assert saved['tables']['public.customer']['columns']['name'] == {}
    with pytest.raises(QueryError, match='changed'):
        call(app, 'save_guide', data)
    raw = (app._queries().catalog.root / '.console_demo.json').read_bytes()
    assert raw.startswith(b'#GNRE1:') and b'Use invoice dates' not in raw
    refreshed = call(app, 'prepare')['guide']
    assert refreshed['status'] == 'draft'
    assert refreshed['tables']['public.customer']['description'] == 'Customers'


def test_profile_authorization_and_no_secrets(workbench):
    _, app = workbench
    assert call(app, 'list', {}, owner='bob')['databases'] == []
    with pytest.raises(QueryError):
        call(app, 'guide', owner='bob')
    with pytest.raises(QueryError, match='dbmanager_admin'):
        call(app, 'register', {'database': 'new'}, owner='alice', admin=False)
    result = call(app, 'list', {})
    assert 'private-password' not in json.dumps(result)
    assert result['databases'][0]['enrollment'] == 'not_enrolled'


def test_registration_reuses_encryption_and_does_not_overwrite(workbench, monkeypatch):
    _, app = workbench
    monkeypatch.setattr(operations, 'check_connection', lambda _: {'connected': True})
    import kajenn_dbmanager.workbench as module
    monkeypatch.setattr(module, 'connection_from_instance', lambda _: {'dbname': 'legacy'})
    result = call(app, 'register_genropy', {'database': 'legacy', 'instance': 'invoice'}, owner='alice')
    assert result['source'] == {'kind': 'genropy', 'instance': 'invoice'}
    assert call(app, 'list', {}, owner='alice')['databases'][1]['source']['instance'] == 'invoice'
    with pytest.raises(QueryError):
        app._queries().catalog.load('legacy', 'local')
    with pytest.raises(QueryError, match='exists'):
        call(app, 'register_genropy', {'database': 'legacy', 'instance': 'invoice'}, owner='alice')


def test_rest_mcp_and_local_boundary(workbench):
    server, _ = workbench
    request = {'action': 'list', 'data': {}}
    status, body = _request(server, '/dbmanager/console_action', method='POST', payload=request)
    assert status == 200 and json.loads(body)['databases'][0]['database'] == 'demo'
    status, body = _request(server, '/dbmanager/_meta/mcp', method='POST', payload={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'console_action', 'arguments': request}})
    assert status == 200 and json.loads(body)['result']['structuredContent']['databases']
    for headers in [[(b'host', b'attacker.example')],
                    [(b'host', b'localhost:8000'), (b'origin', b'https://attacker.example')],
                    [(b'sec-fetch-site', b'cross-site')]]:
        assert _request(server, '/dbmanager/console_action', method='POST', payload=request,
                        request_headers=headers)[0] == 403
    assert _request(server, '/ui/', client='192.0.2.10')[0] == 403


def test_kajenn_identity_never_falls_back_to_local(workbench):
    server, app = workbench
    kajenn_mode(server)
    assert _request(server, '/ui/')[0] == 401
    status, body = _request(server, '/dbmanager/console_action', client='192.0.2.10',
                            method='POST', payload={'action': 'list'}, request_headers=bearer('alice'))
    assert status == 200 and json.loads(body)['identity'] == 'alice'
    assert not json.loads(body)['can_administer']
    assert _request(server, '/dbmanager/backups', client='192.0.2.10',
                    method='POST', payload={}, request_headers=bearer('alice'))[0] == 403


@pytest.mark.parametrize('mode', ['local', 'kajenn'])
@pytest.mark.parametrize('channel', ['api', 'mcp'])
def test_authenticated_identity_uses_the_transport_channel(workbench, monkeypatch, mode, channel):
    server, app = workbench
    app.access_mode = mode
    channels = []
    authenticate = server.authenticate_credential

    async def track_credential(credential, requested_channel):
        channels.append(requested_channel)
        return await authenticate(credential, requested_channel)

    monkeypatch.setattr(server, 'authenticate_credential', track_credential)
    arguments = {'action': 'list'}
    path, payload = '/dbmanager/console_action', arguments
    if channel == 'mcp':
        path = '/dbmanager/_meta/mcp'
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': 'console_action', 'arguments': arguments}}
    status, body = _request(server, path, method='POST', payload=payload,
                            request_headers=bearer('admin'))
    assert status == 200, body
    result = json.loads(body)
    if channel == 'mcp':
        result = result['result']['structuredContent']
    assert result['identity'] == 'admin' and result['can_administer']
    assert channels == [channel]


@pytest.mark.parametrize('mode', ['local', 'kajenn'])
def test_session_identity_and_header_precedence(workbench, mode):
    server, app = workbench
    app.access_mode = mode
    session = server.session_store.create(Avatar('alice'))
    cookie = [(b'cookie', f'session_id={session.id}'.encode())]
    for headers, identity, databases in [(cookie, 'alice', ['demo']),
                                         (cookie + bearer('bob'), 'bob', [])]:
        status, body = _request(server, '/dbmanager/console_action', method='POST',
                                payload={'action': 'list'}, request_headers=headers)
        assert status == 200, body
        result = json.loads(body)
        assert result['identity'] == identity
        assert [item['database'] for item in result['databases']] == databases
        assert result['can_administer'] is (mode == 'local')
    assert _request(server, '/dbmanager/console_action', method='POST',
                    payload={'action': 'list'}, request_headers=cookie + bearer('invalid'))[0] == 401
    status, body = _request(server, '/dbmanager/console_action', method='POST',
                            payload={'action': 'list'})
    if mode == 'local':
        assert status == 200 and json.loads(body)['identity'] == 'local'
    else:
        assert status == 401


@pytest.mark.parametrize('endpoint', ['console_action', 'mcp', 'ui/', 'diagrams/' + '0' * 32])
def test_kajenn_surfaces_reject_missing_and_invalid_credentials(workbench, endpoint):
    server, app = workbench
    kajenn_mode(server)
    for headers in [[], bearer('invalid')]:
        assert _request(server, '/dbmanager/' + endpoint, method='POST', payload={},
                        request_headers=headers)[0] == 401


def test_kajenn_mcp_keeps_admin_requirement(workbench):
    server, app = workbench
    kajenn_mode(server)
    assert _request(server, '/dbmanager/_meta/mcp', method='POST',
                    payload={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                    request_headers=bearer('alice'))[0] == 403


def _open_page(server, path, cookies=b''):
    """Open a workbench page; return its page id and the owner cookie the adapter set."""
    import re

    headers = [(b'cookie', cookies)] if cookies else []
    status, body, response = _request(server, path, include_headers=True, request_headers=headers)
    assert status == 200, body
    page = re.search(rb'"pageId":"([a-f0-9]+)"', body).group(1).decode()
    owner = next(line.split(b';')[0] for line in response[b'set-cookie'].splitlines()
                 if line.startswith(b'gramlot_owner='))
    return page, owner


def _render(server, page, cookies):
    payload = {'id': 'main', 'pageId': page, 'contentType': 'source', 'name': 'main', 'params': {}}
    return _request(server, '/ui/gramlot/rpc', method='POST', payload=payload,
                    request_headers=cookies)


def test_authenticated_ui_page_is_bound_to_session_identity(workbench):
    pytest.importorskip('gramlot_py_server')
    from genro_tytx import from_tytx

    server, _ = workbench
    kajenn_mode(server)
    session = server.session_store.create(Avatar('alice'))
    session_cookie = f'session_id={session.id}'.encode()
    page, owner = _open_page(server, '/ui/chat', session_cookie)
    cookies = [(b'cookie', session_cookie + b'; ' + owner)]
    status, body = _render(server, page, cookies)
    assert status == 200 and 'value' in from_tytx(body.decode())
    server.session_store.delete(session.id)
    assert _render(server, page, cookies)[0] == 401


def test_gramlot_bootstrap_and_every_page_renders(workbench):
    pytest.importorskip('gramlot_py_server')
    from genro_tytx import from_tytx

    server, _ = workbench
    status, body, headers = _request(server, '/ui/', include_headers=True)
    assert status == 200 and b'/ui/assets/gramlot.js' in body
    assert b"frame-ancestors 'self'" in headers[b'content-security-policy']
    assert b'HttpOnly' in headers[b'set-cookie']
    for name in ('index', 'home', 'databases', 'genropy', 'migrations', 'backups',
                 'enrollment', 'guide', 'chat', 'diagram', 'asqueel'):
        page, owner = _open_page(server, f'/ui/{name}')
        status, body = _render(server, page, [(b'cookie', owner)])
        assert status == 200 and 'error' not in str(from_tytx(body.decode())), (name, body)


def test_gramlot_http_protocol_binds_pages_to_browser(workbench):
    pytest.importorskip('gramlot_py_server')
    from genro_tytx import from_tytx

    server, _ = workbench
    page, owner = _open_page(server, '/ui/chat')
    status, body = _render(server, page, [(b'cookie', owner)])
    assert status == 200 and 'value' in from_tytx(body.decode())
    # Another browser cannot reach the page.
    status, body = _render(server, page, [(b'cookie', b'gramlot_owner=' + b'a' * 32)])
    assert status == 200 and 'value' not in from_tytx(body.decode()), body
    assert _request(server, '/ui/workbench.py')[0] == 404
    assert _request(server, '/ui', include_headers=True)[2][b'location'] == b'/ui/'


def test_approved_guide_enters_context_without_rows(workbench):
    _, app = workbench
    prepared = call(app, 'prepare')['guide']
    call(app, 'save_guide', {'database': 'demo', 'revision': prepared['revision'],
                           'tables': prepared['tables'], 'notes': 'Use invoice dates', 'approve': True})
    class Provider:
        model = 'test'
        def call(self, prefix):
            assert 'Use invoice dates' in prefix
            assert 'private-password' not in prefix
            return None, {'cache_creation_input_tokens': 100}
    manager = QuerySessions(catalog=app._queries().catalog, provider=Provider(),
                            introspect=operations.introspect, background=False)
    result = manager.open('demo')
    assert result['tables'] == 1
    manager.shutdown()


def test_metadata_rejects_plaintext_and_loose_permissions(workbench):
    _, app = workbench
    catalog = app._queries().catalog
    call(app, 'prepare')
    path = catalog.root / '.console_demo.json'
    path.chmod(0o644)
    with pytest.raises(QueryError):
        catalog.read_metadata('demo')
    path.chmod(0o600)
    path.write_text('{"guide": {"status": "ready"}}')
    with pytest.raises(QueryError):
        catalog.read_metadata('demo')


def test_approved_guide_is_rejected_after_structure_drift(workbench):
    _, app = workbench
    guide = call(app, 'prepare')['guide']
    call(app, 'save_guide', {'database': 'demo', 'revision': guide['revision'],
                           'tables': guide['tables'], 'notes': '', 'approve': True})
    changed = JsonStructureProducer({'db': 'demo', 'schemas': [{'name': 'public',
        'tables': [{'name': 'other', 'columns': [{'name': 'id', 'dtype': 'T'}]}]}]}).get_json_struct()
    class Provider:
        model = 'test'
        def call(self, *args):
            pytest.fail('Do not send stale guide context to the model')
    manager = QuerySessions(catalog=app._queries().catalog, provider=Provider(),
                            introspect=lambda _: changed, background=False)
    with pytest.raises(QueryError, match='structure changed'):
        manager.open('demo')



def test_workbench_diagram_is_embeddable_and_profile_authorized(workbench, monkeypatch):
    server, app = workbench
    structure = JsonStructureProducer({'db': 'demo', 'schemas': [{'name': 'public',
        'tables': [{'name': 'customer', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'T'}, {'name': 'name', 'dtype': 'T'}],
            'indexes': [{'name': 'customer_name_idx', 'columns': ['name']}]}]}]}).get_json_struct()
    monkeypatch.setattr(operations, 'introspect', lambda _: structure)
    result = call(app, 'diagram')
    assert result['tables'] == 1
    index = next(iter(result['table_details']['public.customer']['indexes'].values()))
    assert index['columns'] == {'name': None}
    assert index['index_name'] == 'customer_name_idx'
    kajenn_mode(server)
    status, body, headers = _request(server, result['url'], include_headers=True,
                                    request_headers=bearer('alice'))
    assert status == 200
    assert b"frame-ancestors 'self'" in headers[b'content-security-policy']
    assert headers[b'x-frame-options'] == b'SAMEORIGIN'
    assert _request(server, result['url'] + '.json', request_headers=bearer('alice'))[0] == 200
    assert _request(server, result['url'], request_headers=bearer('bob'))[0] == 403
    assert _request(server, result['url'] + '.json', request_headers=bearer('bob'))[0] == 403
    with pytest.raises(QueryError):
        call(app, 'diagram', owner='bob')
    app._queries().catalog.save('demo', {'dbname': 'changed'}, users=['alice'], replace=True)
    assert _request(server, result['url'], request_headers=bearer('alice'))[0] == 403


def test_legacy_diagrams_still_require_admin_in_kajenn_mode(workbench):
    server, app = workbench
    result = app._diagram_pages().create(operations.introspect({}), renderer='cytoscape')
    kajenn_mode(server)
    path = '/dbmanager/diagrams/' + result['diagram_id']
    assert _request(server, path, request_headers=bearer('alice'))[0] == 403
    assert _request(server, path, request_headers=bearer('admin'))[0] == 200


def test_page_endpoint_runs_workbench_as_request_identity(workbench):
    pytest.importorskip('gramlot_py_server')
    from genro_tytx import from_tytx

    server, _ = workbench
    kajenn_mode(server)
    session = server.session_store.create(Avatar('bob'))
    session_cookie = f'session_id={session.id}'.encode()
    page, owner = _open_page(server, '/ui/databases', session_cookie)
    payload = {'id': 'list', 'pageId': page, 'contentType': 'data', 'name': 'workbench',
               'params': {'action': 'list'}}
    status, body = _request(server, '/ui/gramlot/rpc', method='POST', payload=payload,
                            request_headers=[(b'cookie', session_cookie + b'; ' + owner)])
    answer = from_tytx(body.decode())
    assert status == 200 and 'value' in answer, answer
    # bob is not in the allowlist of the demo profile and is not an administrator.
    assert 'demo' not in str(answer['value']) and 'bob' in str(answer['value'])
