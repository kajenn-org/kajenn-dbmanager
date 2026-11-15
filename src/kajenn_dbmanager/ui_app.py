"""The web workbench: Gramlot pages served by the gramlot-py-server Kajenn adapter.

The adapter needs ``request(body="raw")`` in the site recipe. On top of it this
application applies the request guards of the DB Manager service, and its pages
reach that service in the same process.
"""

from pathlib import Path

from gramlot_py_server.kajenn import Application

from .access import check_access_mode, check_http, check_identity

PAGES = Path(__file__).with_name('pages')

# Gramlot pages carry inline code (actions, controllers, callbacks), compiled in the
# browser: 'unsafe-eval' is required. That code comes only from the server's pages.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'nonce-{nonce}' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'"
)


class DbManagerUI(Application):
    """Gramlot workbench of the DB Manager service mounted on the same Kajenn server."""

    def __init__(self, access_mode='local', **kwargs):
        super().__init__(PAGES, content_security_policy=CONTENT_SECURITY_POLICY,
                         page_ttl=28800, max_pages=512, **kwargs)
        self.access_mode = check_access_mode(access_mode)

    @property
    def dbmanager(self):
        """The DbManagerApp of this server; exactly one must be mounted."""
        from .app import DbManagerApp

        found = [app for app in self.server.applications.values() if isinstance(app, DbManagerApp)]
        if len(found) != 1:
            raise RuntimeError('The workbench needs exactly one DbManagerApp on its server')
        return found[0]

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http':
            check_http(scope, self.access_mode)
            await self.authenticate_scope(scope)
            check_identity(scope.get('auth'), self.access_mode)
        await super().__call__(scope, receive, send)

    async def serve_websocket(self, scope, receive, send):
        check_http(scope, self.access_mode)
        await super().serve_websocket(scope, receive, send)
