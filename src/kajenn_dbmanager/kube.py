"""Kubernetes access for CloudNativePG clusters: contexts, API clients and port-forwards.

Only this module imports the ``kubernetes`` client, installed by the ``clusters`` extra.
"""

import base64
import json
import os
import socket
import tempfile
from pathlib import Path
from threading import Lock, Thread

from kubernetes import client, config
from kubernetes.stream import portforward

from .query_profiles import QueryError

KUBE_CLUSTERS_ENV = 'KAJENN_DBMANAGER_KUBE_CLUSTERS'
KUBECONFIG_ENV = 'KAJENN_DBMANAGER_KUBECONFIG'
ACCESS_MODES = ('port-forward', 'service')
CNPG_GROUP, CNPG_VERSION, CNPG_PLURAL = 'postgresql.cnpg.io', 'v1', 'clusters'
# The secrets CloudNativePG creates, tried in order (Jarvis reads the same ones).
SECRET_SUFFIXES = ('-superuser', '-admin-password', '-app')
API_TIMEOUT = (5, 30)


class KubeContexts:
    """The Kubernetes contexts DB Manager may use, and one API client per context.

    Contexts come from a JSON list in ``KAJENN_DBMANAGER_KUBE_CLUSTERS`` (``name``,
    ``server``, ``token``, ``ca_data``, ``namespace``, ``access``), the format of a
    Kubernetes Secret mounted as environment, or from the contexts of the kubeconfig
    file named by ``KAJENN_DBMANAGER_KUBECONFIG``.
    """

    def __init__(self, entries=(), kubeconfig=None):
        self._entries = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
                raise QueryError(f'{KUBE_CLUSTERS_ENV} entries need a name')
            if entry.get('access', 'port-forward') not in ACCESS_MODES:
                raise QueryError('Kubernetes context access must be port-forward or service')
            self._entries[entry['name']] = dict(entry)
        self._kubeconfig = kubeconfig
        if kubeconfig:
            contexts, _ = config.list_kube_config_contexts(config_file=kubeconfig)
            for context in contexts:
                self._entries.setdefault(context['name'], {
                    'name': context['name'], 'kubeconfig': True,
                    'namespace': context.get('context', {}).get('namespace') or '*'})
        self._clients = {}
        self._ca_files = []
        self._lock = Lock()

    @classmethod
    def from_environment(cls):
        raw = os.environ.get(KUBE_CLUSTERS_ENV)
        try:
            entries = json.loads(raw) if raw else []
        except ValueError:
            raise QueryError(f'{KUBE_CLUSTERS_ENV} must be a JSON list') from None
        if not isinstance(entries, list):
            raise QueryError(f'{KUBE_CLUSTERS_ENV} must be a JSON list')
        kubeconfig = os.environ.get(KUBECONFIG_ENV)
        if kubeconfig and not Path(kubeconfig).is_file():
            raise QueryError(f'{KUBECONFIG_ENV} names no file')
        return cls(entries, kubeconfig)

    def describe(self):
        """The contexts without their credentials."""
        return [{'name': name, 'kind': 'kubernetes', 'namespace': entry.get('namespace', '*'),
                 'access': entry.get('access', 'port-forward')}
                for name, entry in sorted(self._entries.items())]

    def entry(self, name):
        if name not in self._entries:
            raise QueryError('Unknown Kubernetes context')
        return self._entries[name]

    def api(self, name):
        """The API client of context ``name``, built once."""
        entry = self.entry(name)
        with self._lock:
            if name not in self._clients:
                self._clients[name] = self._build(entry)
            return self._clients[name]

    def _build(self, entry):
        if entry.get('kubeconfig'):
            return config.new_client_from_config(config_file=self._kubeconfig, context=entry['name'])
        if not entry.get('server') or not entry.get('token'):
            raise QueryError('A Kubernetes context needs server and token')
        configuration = client.Configuration()
        configuration.host = entry['server']
        configuration.api_key = {'authorization': entry['token']}
        configuration.api_key_prefix = {'authorization': 'Bearer'}
        if entry.get('ca_data'):
            handle, path = tempfile.mkstemp(suffix='.crt')
            with os.fdopen(handle, 'wb') as file:
                file.write(base64.b64decode(entry['ca_data']))
            self._ca_files.append(path)
            configuration.ssl_ca_cert = path
        else:
            raise QueryError('A Kubernetes context needs ca_data: the API certificate is always verified')
        return client.ApiClient(configuration)

    def close(self):
        with self._lock:
            for api in self._clients.values():
                api.close()
            self._clients.clear()
            for path in self._ca_files:
                Path(path).unlink(missing_ok=True)
            self._ca_files.clear()


def cnpg_clusters(api, namespace='*'):
    """The CloudNativePG clusters visible to ``api``, in ``namespace`` or in all of them."""
    custom = client.CustomObjectsApi(api)
    if namespace == '*':
        result = custom.list_cluster_custom_object(CNPG_GROUP, CNPG_VERSION, CNPG_PLURAL,
                                                   _request_timeout=API_TIMEOUT)
    else:
        result = custom.list_namespaced_custom_object(CNPG_GROUP, CNPG_VERSION, namespace,
                                                      CNPG_PLURAL, _request_timeout=API_TIMEOUT)
    return [parse_cluster(item) for item in result.get('items', [])]


def cnpg_cluster(api, namespace, name):
    item = client.CustomObjectsApi(api).get_namespaced_custom_object(
        CNPG_GROUP, CNPG_VERSION, namespace, CNPG_PLURAL, name, _request_timeout=API_TIMEOUT)
    return parse_cluster(item)


def parse_cluster(item):
    meta, spec, status = item.get('metadata', {}), item.get('spec', {}), item.get('status', {})
    version = status.get('postgresVersion') or 0
    return {'cluster': meta.get('name'), 'namespace': meta.get('namespace'),
            'instances': spec.get('instances', 1), 'ready_instances': status.get('readyInstances', 0),
            'phase': status.get('phase', 'Unknown'), 'primary_pod': status.get('currentPrimary') or '',
            'postgres_version': version // 10000 if version else None,
            'storage_size': spec.get('storage', {}).get('size', '')}


def superuser_credentials(api, namespace, cluster):
    """User and password from the first CloudNativePG secret of the cluster that exists."""
    core = client.CoreV1Api(api)
    for suffix in SECRET_SUFFIXES:
        try:
            secret = core.read_namespaced_secret(f'{cluster}{suffix}', namespace,
                                                 _request_timeout=API_TIMEOUT)
        except client.ApiException as error:
            if error.status == 404:
                continue
            raise QueryError('Cannot read the cluster credentials secret') from None
        data = secret.data or {}
        user = base64.b64decode(data.get('username', '')).decode() or 'postgres'
        return user, base64.b64decode(data.get('password', '')).decode()
    raise QueryError('No credentials secret found for the cluster')


def pod_socket_opener(api, namespace, pod, port=5432):
    """A callable that opens one socket to ``pod:port`` through the Kubernetes API."""
    core = client.CoreV1Api(api)

    def open_socket():
        forward = portforward(core.connect_get_namespaced_pod_portforward, pod, namespace,
                              ports=str(port))
        remote = forward.socket(port)
        remote.setblocking(True)
        return remote

    return open_socket


class LocalForward:
    """A loopback TCP port that forwards each accepted connection to a remote socket.

    ``open_remote`` opens the remote side of one connection: a Kubernetes port-forward
    socket in production. The port lives until ``close``.
    """

    def __init__(self, open_remote):
        self._open_remote = open_remote
        self._listener = socket.create_server(('127.0.0.1', 0))
        self.port = self._listener.getsockname()[1]
        self._sockets = []
        self._closed = False
        self._lock = Lock()
        Thread(target=self._accept, daemon=True, name='dbmanager-forward').start()

    def _accept(self):
        while True:
            try:
                local, _ = self._listener.accept()
            except OSError:
                return
            try:
                remote = self._open_remote()
            except Exception:
                local.close()
                continue
            with self._lock:
                if self._closed:
                    local.close()
                    remote.close()
                    return
                self._sockets.extend((local, remote))
            Thread(target=self._pump, args=(local, remote), daemon=True).start()
            Thread(target=self._pump, args=(remote, local), daemon=True).start()

    @staticmethod
    def _pump(source, target):
        try:
            while data := source.recv(65536):
                target.sendall(data)
        except OSError:
            pass
        finally:
            try:
                target.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def close(self):
        with self._lock:
            self._closed = True
            sockets, self._sockets = self._sockets, []
        self._listener.close()
        for item in sockets:
            try:
                item.close()
            except OSError:
                pass
