# Clusters

DB Manager reaches databases through clusters as well as through single connection
profiles. A cluster is addressed by `context`, `namespace` and `cluster`:

- **CloudNativePG clusters** are discovered through Kubernetes contexts.
- **External clusters** are PostgreSQL servers registered by hand, under the
  context `external` and an empty namespace.

Every cluster operation requires the `dbmanager_admin` tag.

## Install

```bash
python -m pip install 'kajenn-dbmanager[clusters]'
```

The `clusters` extra installs the Kubernetes Python client.

## Kubernetes contexts

Contexts come from one of two sources:

- `KAJENN_DBMANAGER_KUBE_CLUSTERS`: a JSON list, one object per context, the format
  of a Kubernetes Secret mounted as environment.
- `KAJENN_DBMANAGER_KUBECONFIG`: the path of a kubeconfig file; every context in it
  is offered.

| Field | Required | Description |
| --- | --- | --- |
| `name` | yes | Context name, used in cluster addresses |
| `server` | yes | URL of the Kubernetes API server |
| `token` | yes | Bearer token of a service account that can read CloudNativePG clusters, read their secrets and port-forward to their pods |
| `ca_data` | yes | Base64 CA certificate of the API server; the certificate is always verified |
| `namespace` | no | Namespace searched for clusters, or `*` (default) for all namespaces |
| `access` | no | `port-forward` (default) or `service` |

With `port-forward`, each operation opens a local port that forwards to the primary
pod through the Kubernetes API, and closes it at the end: the database is never
exposed. With `service`, DB Manager connects to `<cluster>-rw.<namespace>.svc`;
use it when DB Manager runs inside the same Kubernetes cluster.

Credentials are read for each operation from the first secret of the cluster that
exists: `<cluster>-superuser`, `<cluster>-admin-password`, `<cluster>-app`. They are
never stored.

## External clusters

An external cluster holds `host`, `port` (5432), `user` (`postgres`), `password`,
`sslmode` (`prefer`) and `maintenance_db` (`postgres`). It is stored in the encrypted
profile catalog, beside the profiles.

## Profiles on a cluster

A profile registered from a cluster stores only the cluster address and the database
name. Every workbench operation on it (structure, diagram, migrations, backups,
enrollment, chat) reaches the database through the cluster.

## Workbench

Open **Registration → Clusters**. The tree lists the contexts and their clusters; a
context that cannot be read shows its error. Select a cluster to list its databases
with owner and size, then **Register selected…** to create a profile.
**Add external cluster…** registers an external cluster.

## REST and MCP

| Route / MCP tool | Result |
| --- | --- |
| `cluster_contexts` | Kubernetes contexts, without credentials, and the external context |
| `cluster_list` | CloudNativePG clusters of a context, or the external clusters |
| `cluster_databases` | Databases of a cluster with owner and size |

The workbench actions `cluster_external` and `cluster_register` of `console_action`
register an external cluster and a profile on a cluster.
