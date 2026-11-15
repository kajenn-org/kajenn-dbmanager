"""Clusters: Kubernetes contexts and their CloudNativePG clusters, external clusters,
the databases of a cluster and their registration as profiles."""

from genro_bag import Bag
from gramlot import endpoint

from kajenn_dbmanager.workbench_page import WorkbenchPage, as_bag

STATUS = "this.SET('clusters.status', {})"
ERROR = STATUS.format('error.message')
SELECT = ("const n = this.GET('clusters.tree').getNode(path);"
          "this.SET('clusters.ref', n && n.attr.cluster ? "
          "[n.attr.context, n.attr.namespace, n.attr.cluster].join('|') : null)")


def _reference(ref):
    context, namespace, cluster = ref.split('|')
    return {'context': context, 'namespace': namespace, 'cluster': cluster}


class Page(WorkbenchPage):
    title = 'Clusters'

    @endpoint
    def cluster_tree(self, **kwargs):
        """Contexts and their clusters; a context that cannot be read shows its error."""
        tree = Bag()
        for index, context in enumerate(self.run('cluster_contexts')['contexts']):
            clusters = Bag()
            try:
                listed = self.run('cluster_list', context=context['name'])['clusters']
            except Exception as error:
                clusters.set_item('error', None, {'caption': f'Unavailable: {error}'})
                listed = []
            for position, item in enumerate(listed):
                caption = item['cluster'] + (f" · {item['namespace']}" if item['namespace'] else '')
                clusters.set_item(f'k_{position}', None, {
                    'caption': f"{caption} · {item.get('phase', '')}", 'context': context['name'],
                    'namespace': item['namespace'], 'cluster': item['cluster']})
            tree.set_item(f'c_{index}', clusters, {'caption': f"{context['name']} ({context['kind']})"})
        return tree

    @endpoint
    def databases_of(self, ref, **kwargs):
        return as_bag(self.run('cluster_databases', cluster=_reference(ref))['databases'])

    @endpoint
    def register(self, ref, dbname, profile, **kwargs):
        saved = self.run('cluster_register', database=profile, cluster=_reference(ref), dbname=dbname)
        return f"Registered {saved['database']}"

    @endpoint
    def add_external(self, record, **kwargs):
        record = record.as_dict(recursive=True)
        name = record.pop('name', None)
        connection = {key: value for key, value in record.items() if value not in (None, '')}
        self.run('cluster_external', name=name, connection=connection)
        return f'Added external cluster {name}'

    def main(self, root):
        page = root.main(datapath='clusters', height='100vh', display='flex',
                         flex_direction='column', padding='8px 12px', gap='8px', min_height=0)
        page.dataSetter('.tree', Bag())
        page.dataSetter('.rows', Bag())
        page.dataRpc('cluster_tree', refresh='^.refresh', _onStart=True, _onError=ERROR,
                     _onCalling=STATUS.format("'Reading clusters…'"),
                     _onResult="this.GET('clusters.tree').replace(result);" + STATUS.format('null'))
        page.dataController(SELECT, path='^.selectedPath')
        page.dataRpc('databases_of', ref='^.ref', _if='ref', _onError=ERROR,
                     _onResult="this.GET('clusters.rows').replace(result)")
        bar = page.menu(presentation='bar', aria_label='Cluster commands', padding='4px 8px')
        bar.menuline(group=True).strong('Clusters')
        bar.spacer(flex=1)
        actions = bar.menuline(group=True)
        actions.button('Refresh', id='clusters-refresh',
                       action="this.SET('clusters.refresh', Date.now())")
        actions.button('Add external cluster…', id='clusters-external',
                       action="this.SET('clusters.externalDialog', true)")
        split = page.borderContainer(flex='1', min_height=0)
        left = split.contentPane(region='left', width='320px', splitter=True, overflow='auto',
                                 padding='8px')
        left.tree(storepath='clusters.tree', labelAttribute='caption', hideValues=True,
                  selectedPath='^clusters.selectedPath', id='clusters-tree')
        center = split.contentPane(region='center', overflow='hidden')
        grid = center.frameGrid(storepath='clusters.rows', rowMode='values', searchOn=True,
                                height='100%', grid_id='clusters-databases',
                                selected_database='^clusters.dbname')
        struct = grid.grid.struct()
        struct.column('database', name='Database', width='220px')
        struct.column('owner', name='Owner', width='160px')
        struct.column('size_bytes', name='Size (bytes)', dtype='L', width='140px', align='end')
        grid.top.menu(presentation='bar', padding='4px 8px').menuline(group=True).button(
            'Register selected…', id='clusters-register',
            action="this.SET('clusters.registerDialog', true)")
        self.status(page, 'clusters.status')
        self.register_dialog(page)
        self.external_dialog(page)

    def register_dialog(self, page):
        dialog = page.dialog(title='Register the database as a profile', open='^.registerDialog',
                             width='28rem', height='14rem', movable=True)
        frame = dialog.frame
        form = frame.center.contentPane(padding='12px').formlet(columns=1, lbl_position='L')
        form.div('^clusters.dbname', lbl='Database')
        form.textbox(value='^clusters.profile', lbl='Profile name', id='clusters-profile')
        footer = frame.bottom.menu(presentation='bar', padding='4px 8px')
        footer.spacer(flex=1)
        buttons = footer.menuline(group=True)
        buttons.button('Cancel', action="this.SET('clusters.registerDialog', false)")
        buttons.button('Register', id='clusters-register-submit').dataRpc(
            'register', ref='=clusters.ref', dbname='=clusters.dbname', profile='=clusters.profile',
            _onError=ERROR,
            _onResult="this.SET('clusters.registerDialog', false);" + STATUS.format('result'))

    def external_dialog(self, page):
        dialog = page.dialog(title='Add external cluster', open='^.externalDialog', width='30rem',
                             height='26rem', movable=True, resizable=True)
        frame = dialog.frame
        form = frame.center.contentPane(padding='12px', overflow='auto').formlet(
            datapath='clusters.external', columns=1, lbl_position='L')
        form.textbox(value='^.name', lbl='Cluster name', id='clusters-external-name')
        form.textbox(value='^.host', lbl='Host')
        form.numberTextBox(value='^.port', lbl='Port', default=5432)
        form.textbox(value='^.user', lbl='User', default='postgres')
        form.passwordbox(value='^.password', lbl='Password')
        form.filteringSelect(value='^.sslmode', lbl='SSL mode', default='prefer',
                             values='disable:disable,prefer:prefer,require:require,'
                                    'verify-full:verify-full')
        form.textbox(value='^.maintenance_db', lbl='Maintenance database', default='postgres')
        footer = frame.bottom.menu(presentation='bar', padding='4px 8px')
        footer.spacer(flex=1)
        buttons = footer.menuline(group=True)
        buttons.button('Cancel', action="this.SET('clusters.externalDialog', false)")
        buttons.button('Add', id='clusters-external-submit').dataRpc(
            'add_external', record='=clusters.external', _onError=ERROR,
            _onResult="this.SET('clusters.external.password', null);"
                      "this.SET('clusters.externalDialog', false);"
                      "this.SET('clusters.refresh', Date.now());" + STATUS.format('result'))
