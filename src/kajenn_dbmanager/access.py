"""Request guards shared by the DB Manager service and its web workbench."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from kajenn import HTTPException, HTTPForbidden

ACCESS_MODES = {'local', 'kajenn'}


def check_access_mode(access_mode):
    if access_mode not in ACCESS_MODES:
        raise ValueError('access_mode must be local or kajenn')
    return access_mode


def check_http(scope, access_mode):
    """Refuse remote callers in local mode and cross-site or cross-origin browsers in both modes."""
    headers = dict(scope.get('headers', []))
    host = headers.get(b'host', b'').decode('latin-1')
    if access_mode == 'local':
        client = scope.get('client')
        try:
            local = client and ip_address(str(client[0]).split('%')[0]).is_loopback
        except ValueError:
            local = False
        if not local:
            raise HTTPForbidden('DB Manager is restricted to localhost')
        if host:
            hostname = urlsplit('http://' + host).hostname
            try:
                allowed_host = hostname == 'localhost' or ip_address(hostname).is_loopback
            except ValueError:
                allowed_host = False
            if not allowed_host:
                raise HTTPForbidden('Local mode requires a loopback Host')
    origin = headers.get(b'origin', b'').decode('latin-1')
    if headers.get(b'sec-fetch-site') == b'cross-site':
        raise HTTPForbidden('Cross-site requests are not allowed')
    if origin and origin != f'{scope.get("scheme", "http")}://{host}':
        raise HTTPForbidden('Cross-origin requests are not allowed')


def check_identity(avatar, access_mode):
    """In kajenn mode every request needs an authenticated identity; local mode never falls back to it."""
    if access_mode == 'kajenn' and (avatar is None or not avatar.identity):
        raise HTTPException(401, 'Kajenn authentication is required')


def caller(avatar, access_mode):
    """The owner and administrator flag of a request."""
    admin = access_mode == 'local' or (avatar is not None and 'dbmanager_admin' in avatar.tags)
    owner = avatar.identity if avatar is not None else 'local'
    return owner, admin
