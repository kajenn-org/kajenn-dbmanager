"""Base of the workbench pages built with Gramlot widgets.

Every page reaches the DB Manager service through one endpoint, ``workbench``,
which runs a ``Workbench`` action as the identity of the request.
"""

from genro_bag import Bag
from gramlot import Page, endpoint

from .access import caller

NAVIGATION = (
    ('start', 'Start here', (('home', 'Getting started'),)),
    ('registration', 'Registration', (('databases', 'Databases'),
                                      ('genropy', 'Genropy legacy instances'),
                                      ('asqueel', 'Asqueel configurations'))),
    ('operations', 'Operations', (('diagram', 'Database diagram'), ('migrations', 'Migrations'),
                                  ('backups', 'Backup & restore'))),
    ('queries', 'AI Queries', (('enrollment', 'Database enrollment'), ('guide', 'Database Guide'),
                               ('chat', 'Chat'))),
)


def navigation():
    """The navigation tree of the shell: one folder per group, one leaf per page."""
    root = Bag()
    for key, title, pages in NAVIGATION:
        group = Bag()
        for page, label in pages:
            group.set_item(page, None, {'title': label, 'url': page})
        root.set_item(key, group, {'title': title})
    return root


def _row(item):
    """A grid row (``rowMode='values'``): scalar fields, nested mappings flattened one level as ``key_sub``."""
    attributes = {}
    for key, value in item.items():
        if isinstance(value, dict):
            for sub, inner in value.items():
                if not isinstance(inner, (dict, list)):
                    attributes[f'{key}_{sub}'] = inner
        elif not isinstance(value, list):
            attributes[key] = value
    row = Bag()
    for key, value in attributes.items():
        row.set_item(key, value)
    return row


def as_bag(value):
    """Convert a Workbench answer to Gramlot Data: mappings become Bags, lists of mappings grid rows."""
    if isinstance(value, dict):
        bag = Bag()
        for key, item in value.items():
            bag.set_item(str(key), as_bag(item))
        return bag
    if isinstance(value, list):
        bag = Bag()
        for index, item in enumerate(value):
            if isinstance(item, dict):
                bag.set_item(f'r_{index}', _row(item))
            else:
                bag.set_item(f'r_{index}', as_bag(item))
        return bag
    return value


class WorkbenchPage(Page):
    title = 'DB Manager'
    css = ('/workbench.css',)

    @property
    def dbmanager(self):
        # The Kajenn adapter hands every page its hosting application as database
        # access; Gramlot exposes no public name for it.
        return self._database_access.dbmanager

    def run(self, action, **data):
        """Run one Workbench action as the identity of this request; return its plain result."""
        app = self.dbmanager
        owner, admin = caller(self.request_identity, app.access_mode)
        return app.workbench.call(action, data, owner, admin)

    @endpoint
    def workbench(self, action, data=None, **kwargs):
        """Run one Workbench action as the identity of this request.

        The action arguments come from ``data`` (a Bag or mapping) and from every
        ``data_<key>`` keyword; other keywords (triggers such as ``refresh``) are ignored.
        """
        app = self.dbmanager
        owner, admin = caller(self.request_identity, app.access_mode)
        data = data.as_dict(recursive=True) if isinstance(data, Bag) else dict(data or {})
        data.update({key.removeprefix('data_'): value for key, value in kwargs.items()
                     if key.startswith('data_')})
        return as_bag(app.workbench.call(action, data, owner, admin))

    @endpoint
    def profile_names(self, **kwargs):
        """The caller's profile names as filteringSelect values: ``name:name,...``."""
        app = self.dbmanager
        owner, admin = caller(self.request_identity, app.access_mode)
        names = [item['database'] for item in app.workbench.call('list', {}, owner, admin)['databases']]
        return ','.join(f'{name}:{name}' for name in names)

    def load_profiles(self, page, values='profileValues'):
        """Load the caller's profile names once into ``values``, for ``database_select``."""
        page.dataRpc('profile_names', result_path=values, _onStart=True)

    def database_select(self, parent, value, *, lbl='Database', values='profileValues', **attributes):
        """A select of the caller's profiles, loaded by ``load_profiles``."""
        return parent.filteringSelect(value=value, values=f'^{values}', lbl=lbl,
                                      placeholder='Select a database', **attributes)

    def status(self, parent, path='.status'):
        """The line where actions report their outcome."""
        return parent.div(f'^{path}', role='status', aria_live='polite', class_='workbench-status')
