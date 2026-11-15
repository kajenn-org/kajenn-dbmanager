import asyncio
import json
import threading

import pytest
from kajenn import AsgiServer

from kajenn_dbmanager.app import DbManagerApp, DbManagerWorker


class _LiveServer:
    """One server inside its real lifespan, on an event loop of its own thread.

    Kajenn answers 503 until the lifespan startup has enabled every application,
    and the lifespan stays open until shutdown: requests run on the same loop.
    """

    def __init__(self, server):
        self.server = server
        self.sent = []
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.run(self.startup())

    def run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=60)

    async def startup(self):
        self.inbox = asyncio.Queue()

        async def send(message):
            self.sent.append(message)

        self.task = asyncio.ensure_future(self.server({'type': 'lifespan'}, self.inbox.get, send))
        await self.inbox.put({'type': 'lifespan.startup'})
        async with asyncio.timeout(10):
            while not any(m['type'].startswith('lifespan.startup.') for m in self.sent):
                await asyncio.sleep(0.005)
            failed = [m for m in self.sent if m['type'] == 'lifespan.startup.failed']
            if failed:
                raise RuntimeError(failed[0].get('message', 'lifespan startup failed'))
            while not all(self.server.is_enabled(code) for code in self.server.applications):
                await asyncio.sleep(0.005)

    async def shutdown(self):
        await self.inbox.put({'type': 'lifespan.shutdown'})
        await self.task

    def close(self):
        try:
            self.run(self.shutdown())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
            self.loop.close()


_LIVE = {}


def live(server):
    """The started lifespan of ``server``, started on first use in the test."""
    if id(server) not in _LIVE:
        _LIVE[id(server)] = _LiveServer(server)
    return _LIVE[id(server)]


@pytest.fixture(autouse=True)
def _stop_live_servers():
    yield
    servers = list(_LIVE.values())
    _LIVE.clear()
    for server in servers:
        server.close()


def _request(
    server,
    path,
    *,
    method='GET',
    client='127.0.0.1',
    query=b'',
    payload=None,
    include_headers=False,
    auth=None,
    request_headers=None,
):
    """Drive one HTTP request through the real ASGI stack."""
    body = json.dumps(payload).encode() if payload is not None else b''
    headers = [(b'content-type', b'application/json')] if payload is not None else []
    headers.extend(request_headers or [])

    async def run():
        scope = {
            'type': 'http',
            'method': method,
            'path': path,
            'query_string': query,
            'headers': headers,
            'client': (client, 12345),
        }
        if auth is not None:
            scope['auth'] = auth
        sent = []

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            sent.append(message)

        await server(scope, receive, send)
        status = next(
            message['status']
            for message in sent
            if message['type'] == 'http.response.start'
        )
        response_body = b''.join(
            message.get('body', b'')
            for message in sent
            if message['type'] == 'http.response.body'
        )
        if include_headers:
            raw_headers = next(message['headers'] for message in sent
                               if message['type'] == 'http.response.start')
            response_headers = dict(raw_headers)
            cookies = [value for name, value in raw_headers if name == b'set-cookie']
            if cookies:
                response_headers[b'set-cookie'] = b'\n'.join(cookies)
            return status, response_body, response_headers
        return status, response_body

    return live(server).run(run())



@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAJENN_DBMANAGER_BACKUP_DIR", str(tmp_path / "backups"))
    return AsgiServer(applications=[DbManagerApp, DbManagerWorker])
