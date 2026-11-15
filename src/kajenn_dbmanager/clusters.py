"""Database clusters: CloudNativePG clusters through Kubernetes contexts, and external clusters.

A cluster is addressed by ``{'context', 'namespace', 'cluster'}``; external clusters
use the context ``external`` and an empty namespace. Credentials are never stored for
CloudNativePG clusters: they are read from the cluster secret for each operation.
External clusters are kept in the encrypted catalog.
"""

from contextlib import contextmanager

from . import operations
from .query_profiles import CLUSTER_NAME, EXTERNAL, QueryError, cluster_reference

_EXTERNAL_FIELDS = {'host', 'port', 'user', 'password', 'sslmode', 'maintenance_db'}
DATABASES_SQL = (
    "SELECT datname, pg_get_userbyid(datdba) AS owner, pg_database_size(oid) AS size_bytes "
    "FROM pg_database WHERE NOT datistemplate AND datallowconn ORDER BY datname")


def external_cluster(record):
    """A validated external cluster record."""
    if not isinstance(record, dict) or set(record) - _EXTERNAL_FIELDS or not record.get('host'):
        raise QueryError('An external cluster needs host and accepts only '
                         + ', '.join(sorted(_EXTERNAL_FIELDS)))
    return {'port': 5432, 'user': 'postgres', 'sslmode': 'prefer', 'maintenance_db': 'postgres',
            **record}


def _kube():
    try:
        from . import kube
    except ImportError:
        raise QueryError('Install kajenn-dbmanager[clusters] to use Kubernetes clusters') from None
    return kube


class ClusterRegistry:
    """The clusters DB Manager can reach, and connections to their databases."""

    def __init__(self, catalog, contexts=None):
        self.catalog = catalog
        self._contexts = contexts

    @property
    def contexts(self):
        if self._contexts is None:
            self._contexts = _kube().KubeContexts.from_environment()
        return self._contexts

    def list_contexts(self):
        return [*self.contexts.describe(), {'name': EXTERNAL, 'kind': 'external'}]

    def list_clusters(self, context):
        if context == EXTERNAL:
            return [{'cluster': name, 'namespace': '', 'phase': 'external'}
                    for name in self.catalog.cluster_names()]
        entry = self.contexts.entry(context)
        return _kube().cnpg_clusters(self.contexts.api(context), entry.get('namespace', '*'))

    def save_external(self, name, record, *, replace=False):
        if not CLUSTER_NAME.fullmatch(name or ''):
            raise QueryError('Invalid external cluster name')
        self.catalog.save_cluster(name, external_cluster(record), replace=replace)
        return {'context': EXTERNAL, 'namespace': '', 'cluster': name}

    def list_databases(self, reference):
        """The databases of a cluster, read through its maintenance database."""
        reference = cluster_reference(reference)
        maintenance = 'postgres'
        if reference['context'] == EXTERNAL:
            maintenance = self.catalog.load_cluster(reference['cluster'])['maintenance_db']
        with self.connect(reference, maintenance) as connection:
            import psycopg

            with psycopg.connect(**connection) as db, db.cursor() as cursor:
                cursor.execute(DATABASES_SQL)
                return [{'database': name, 'owner': owner, 'size_bytes': size}
                        for name, owner, size in cursor.fetchall()]

    @contextmanager
    def connect(self, reference, dbname):
        """Connection parameters to ``dbname`` on a cluster, valid inside the block."""
        reference = cluster_reference(reference)
        if not isinstance(dbname, str) or not dbname:
            raise QueryError('A database name is required')
        if reference['context'] == EXTERNAL:
            record = self.catalog.load_cluster(reference['cluster'])
            yield operations.connection_params({
                key: record[key] for key in ('host', 'port', 'user', 'password', 'sslmode')
                if record.get(key) is not None} | {'dbname': dbname})
            return
        kube = _kube()
        entry = self.contexts.entry(reference['context'])
        api = self.contexts.api(reference['context'])
        namespace, name = reference['namespace'], reference['cluster']
        user, password = kube.superuser_credentials(api, namespace, name)
        params = {'user': user, 'password': password, 'dbname': dbname, 'sslmode': 'prefer'}
        if entry.get('access', 'port-forward') == 'service':
            yield operations.connection_params({**params, 'host': f'{name}-rw.{namespace}.svc',
                                                'port': 5432})
            return
        pod = kube.cnpg_cluster(api, namespace, name)['primary_pod']
        if not pod:
            raise QueryError('The cluster reports no primary instance')
        forward = kube.LocalForward(kube.pod_socket_opener(api, namespace, pod))
        try:
            yield operations.connection_params({**params, 'host': '127.0.0.1',
                                                'port': forward.port})
        finally:
            forward.close()

    def close(self):
        if self._contexts is not None:
            self._contexts.close()
