"""Local encrypted connection catalog, using Kajenn's storage encryption."""

import hashlib
import json
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from genro_storage import StorageManager
from genro_toolbox.smartasync import set_sync

from .operations import connection_params


class QueryError(ValueError):
    """Public diagnostics must be constant strings, never provider/driver errors."""


def read_secret(reference):
    """Read an explicit 1Password reference without exposing subprocess diagnostics."""
    if not isinstance(reference, str) or not reference.startswith('op://'):
        raise QueryError('Expected a 1Password secret reference')
    try:
        result = subprocess.run(['op', 'read', reference], capture_output=True,
                                text=True, timeout=60, check=True)
        return result.stdout.strip()
    except Exception:
        raise QueryError('Cannot read the configured secret from 1Password') from None


def storage_key(reference_file=None):
    """Obtain key material separately from encrypted records, without creating it."""
    key = os.environ.get('KAJENN_DBMANAGER_STORAGE_KEY')
    reference = os.environ.get('KAJENN_DBMANAGER_STORAGE_KEY_REF')
    if not key and not reference and reference_file and reference_file.is_file():
        reference = reference_file.read_text().strip()
    if not key and reference and reference.startswith('op://'):
        key = read_secret(reference)
    if not key:
        raise QueryError('Configure KAJENN_DBMANAGER_STORAGE_KEY_REF or KAJENN_DBMANAGER_STORAGE_KEY')
    return key


EXTERNAL = 'external'
CLUSTER_NAME = re.compile(r'[a-z0-9]([a-z0-9._-]{0,251}[a-z0-9])?')


def cluster_reference(value):
    """A validated cluster address: ``context``, ``namespace`` and ``cluster``."""
    if not isinstance(value, dict) or set(value) != {'context', 'namespace', 'cluster'}:
        raise QueryError('A cluster is addressed by context, namespace and cluster')
    context, namespace, cluster = value['context'], value['namespace'], value['cluster']
    if not all(isinstance(item, str) for item in (context, namespace, cluster)):
        raise QueryError('Cluster address parts must be text')
    if not CLUSTER_NAME.fullmatch(cluster) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@-]{0,252}', context):
        raise QueryError('Invalid cluster address')
    if context == EXTERNAL:
        if namespace:
            raise QueryError('External clusters have no namespace')
    elif not CLUSTER_NAME.fullmatch(namespace):
        raise QueryError('Invalid cluster namespace')
    return {'context': context, 'namespace': namespace, 'cluster': cluster}


def stored_connection(connection):
    """A profile connection: PostgreSQL parameters, or a database on a registered cluster."""
    if isinstance(connection, dict) and 'cluster' in connection:
        if set(connection) != {'cluster', 'dbname'} or not isinstance(connection['dbname'], str) \
                or not connection['dbname']:
            raise QueryError('A cluster profile holds only the cluster and the dbname')
        return {'cluster': cluster_reference(connection['cluster']), 'dbname': connection['dbname']}
    return connection_params(connection)


class ConnectionCatalog:
    """One encrypted JSON document per logical database; no secret export API.

    External clusters are kept beside the profiles, encrypted the same way. A profile
    on a cluster stores no credentials: ``connect`` reaches it through ``clusters``.
    """

    def __init__(self, root=None, key=None, clusters=None):
        self.root = Path(root or os.environ.get(
            'KAJENN_DBMANAGER_DB_DIR', '~/.kajen-dbmanager/db')).expanduser().absolute()
        self._key = key
        self._manager = None
        self.clusters = clusters

    @contextmanager
    def connect(self, connection):
        """PostgreSQL parameters of a stored connection, valid inside the block."""
        if 'cluster' not in connection:
            yield connection
            return
        if self.clusters is None:
            raise QueryError('Cluster profiles need the DB Manager service')
        with self.clusters.connect(connection['cluster'], connection['dbname']) as params:
            yield params

    @property
    def key_reference_path(self):
        return self.root.parent / 'storage-key-reference'

    def _path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
            raise QueryError('Invalid database profile name')
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise QueryError('Database catalog directories must not be symbolic links')
        path = self.root / f'{name}.json'
        if path.is_symlink():
            raise QueryError('Database profiles must not be symbolic links')
        return path

    def _storage(self):
        set_sync()
        if self._manager is not None:
            return self._manager
        manager = StorageManager()
        try:
            manager.configure([{'name': 'db', 'protocol': 'local',
                                'base_path': str(self.root)}],
                              storage_key=self._key or storage_key(self.key_reference_path))
        except QueryError:
            raise
        except Exception:
            raise QueryError('Cannot configure encrypted database storage') from None
        self._manager = manager
        return manager

    def save(self, name, connection, *, users=None, replace=False):
        path = self._path(name)
        connection = stored_connection(connection)
        users = ['local'] if users is None else users
        if not users or any(not isinstance(u, str) or not u for u in users):
            raise QueryError('At least one allowed identity is required')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        if path.exists() and not replace:
            raise QueryError('Database profile exists; use --replace explicitly')
        record = {'version': 1, 'name': name, 'connection': connection, 'users': users}
        temporary = f'.{uuid4().hex}.json'
        staging = self.root / temporary
        try:
            # Create with restrictive permissions before storage writes ciphertext.
            fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self._storage().node(f'db:{temporary}').write_text(
                json.dumps(record), encrypted=True)
            staging.chmod(0o600)
            if replace:
                os.replace(staging, path)
            else:
                os.link(staging, path)  # Atomic create: never overwrite another writer.
        finally:
            staging.unlink(missing_ok=True)
        return {'database': name, 'encrypted': True}

    def load(self, name, owner='local'):
        path = self._path(name)
        try:
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or self.root.stat().st_mode & 0o077):
                raise QueryError('Database catalog requires directory mode 700 and file mode 600')
            raw = path.read_bytes()
            if not raw.startswith(StorageManager.ENVELOPE_PREFIX):
                raise QueryError('Unencrypted database profiles are not accepted')
            record = json.loads(self._storage().node(f'db:{name}.json').read_text())
            if record.get('version') != 1 or record.get('name') != name:
                raise QueryError('Invalid encrypted database profile')
            if owner not in record.get('users', []):
                raise QueryError('Database profile is unavailable to this identity')
            return stored_connection(record['connection']), hashlib.sha256(raw).hexdigest()
        except QueryError:
            raise
        except Exception:
            raise QueryError('Cannot read database profile; check name, key and permissions') from None

    def list(self, owner='local'):
        if not self.root.exists():
            return []
        result = []
        for path in sorted(self.root.glob('*.json')):
            if path.name.startswith('.'):
                continue
            try:
                self.load(path.stem, owner)
            except QueryError:
                continue
            result.append({'database': path.stem})
        return result

    def _cluster_path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}', name):
            raise QueryError('Invalid external cluster name')
        path = self.root / f'.cluster_{name}.json'
        if path.is_symlink():
            raise QueryError('External clusters must not be symbolic links')
        return path

    def save_cluster(self, name, record, *, replace=False):
        """Store an external cluster encrypted; existing clusters need ``replace``."""
        path = self._cluster_path(name)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        if path.exists() and not replace:
            raise QueryError('External cluster exists; replace it explicitly')
        staging = self.root / f'.{uuid4().hex}.json'
        try:
            fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self._storage().node(f'db:{staging.name}').write_text(
                json.dumps({'version': 1, 'name': name, 'cluster': record}), encrypted=True)
            if replace:
                os.replace(staging, path)
            else:
                os.link(staging, path)
        finally:
            staging.unlink(missing_ok=True)

    def load_cluster(self, name):
        path = self._cluster_path(name)
        try:
            raw = path.read_bytes()
            if not raw.startswith(StorageManager.ENVELOPE_PREFIX) or path.stat().st_mode & 0o077:
                raise QueryError('External clusters must be encrypted and private')
            record = json.loads(self._storage().node(f'db:{path.name}').read_text())
            if record.get('version') != 1 or record.get('name') != name:
                raise QueryError('Invalid external cluster record')
            return record['cluster']
        except QueryError:
            raise
        except Exception:
            raise QueryError('Cannot read the external cluster') from None

    def cluster_names(self):
        if not self.root.exists():
            return []
        return sorted(path.name.removeprefix('.cluster_').removesuffix('.json')
                      for path in self.root.glob('.cluster_*.json'))

    def read_metadata(self, name, owner='local'):
        """Read encrypted workbench metadata only after checking profile access."""
        self.load(name, owner)
        path = self.root / f'.console_{name}.json'
        if path.is_symlink():
            raise QueryError('Invalid metadata file')
        if not path.exists():
            return {}
        try:
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or not path.read_bytes().startswith(StorageManager.ENVELOPE_PREFIX)):
                raise QueryError('Metadata must be encrypted and private')
            return json.loads(self._storage().node(f'db:{path.name}').read_text())
        except Exception:
            raise QueryError('Cannot read database metadata') from None

    def write_metadata(self, name, metadata, owner='local'):
        """Atomically persist metadata under the same encryption as the profile."""
        self.load(name, owner)
        path = self.root / f'.console_{name}.json'
        if path.is_symlink():
            raise QueryError('Invalid metadata file')
        staging = self.root / f'.{uuid4().hex}.json'
        try:
            fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self._storage().node(f'db:{staging.name}').write_text(
                json.dumps(metadata), encrypted=True)
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)
