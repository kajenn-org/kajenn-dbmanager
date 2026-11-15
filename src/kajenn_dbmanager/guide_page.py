"""Database enrollment for AI queries: descriptions and privacy of tables and columns."""

from genro_bag import Bag
from gramlot import endpoint

from .workbench_page import WorkbenchPage

STATUS = "this.SET('guide.status', {})"
ERROR = STATUS.format('error.message')
LOADED = ("this.GET('guide.tables').replace(result.getItem('tables'));"
          "this.GET('guide.columns').replace(result.getItem('columns'));"
          "this.SET('guide.notes', result.getItem('notes'));"
          "this.SET('guide.revision', result.getItem('revision'));"
          "this.SET('guide.info', result.getItem('info'));")


def _guide_bag(guide, stale=False):
    """The editable view of a guide: notes, one row per table, one row per column."""
    answer = Bag()
    tables, columns = Bag(), Bag()
    if guide:
        for index, (table, policy) in enumerate(sorted(guide['tables'].items())):
            row = Bag()
            row.set_item('table', table)
            row.set_item('description', policy.get('description', ''))
            row.set_item('hidden', policy.get('privacy') == 'H')
            tables.set_item(f'r_{index}', row)
            for column, attrs in sorted(policy.get('columns', {}).items()):
                item = Bag()
                item.set_item('table', table)
                item.set_item('column', column)
                item.set_item('hidden', attrs.get('privacy') == 'H')
                columns.set_item(f'r_{len(columns)}', item)
    answer.set_item('tables', tables)
    answer.set_item('columns', columns)
    answer.set_item('notes', (guide or {}).get('notes', ''))
    answer.set_item('revision', (guide or {}).get('revision'))
    if not guide:
        answer.set_item('info', 'No guide yet: read the structure first.')
    else:
        answer.set_item('info', f"Status {guide['status']} · revision {guide['revision']}"
                                + (' · STALE: read the structure again' if stale else ''))
    return answer


class GuidePage(WorkbenchPage):
    title = 'Database enrollment'

    @endpoint
    def load_guide(self, database, refresh=False, **kwargs):
        """The guide of ``database``; with ``refresh`` the structure is read again first."""
        if refresh:
            return _guide_bag(self.run('prepare', database=database)['guide'])
        result = self.run('guide', database=database)
        return _guide_bag(result['guide'], result['stale'])

    @endpoint
    def save_guide(self, database, revision, notes, tables, columns, approve=False, **kwargs):
        """Save the reviewed descriptions and privacy; ``approve`` confirms enrollment."""
        submitted = {}
        for row in tables.values():
            submitted[row['table']] = {'description': row['description'] or '',
                                       'privacy': 'H' if row['hidden'] else None, 'columns': {}}
        for row in columns.values():
            submitted[row['table']]['columns'][row['column']] = (
                {'privacy': 'H'} if row['hidden'] else {})
        result = self.run('save_guide', database=database, revision=revision, notes=notes or '',
                          tables=submitted, approve=bool(approve))
        return _guide_bag(result['guide'])

    def main(self, root):
        page = root.main(datapath='guide', height='100vh', display='flex',
                         flex_direction='column', padding='8px 12px', gap='8px', min_height=0)
        self.load_profiles(page)
        page.dataSetter('.tables', Bag())
        page.dataSetter('.columns', Bag())
        bar = page.menu(presentation='bar', aria_label='Enrollment commands', padding='4px 8px')
        self.database_select(bar.menuline(group=True), '^guide.database', id='guide-database')
        actions = bar.menuline(group=True)
        for label, refresh, key in (('Load guide', False, 'load'),
                                    ('Read / refresh structure', True, 'prepare')):
            actions.button(label, id=f'guide-{key}').dataRpc(
                'load_guide', database='=guide.database', refresh=refresh,
                _onError=ERROR, _onResult=LOADED + STATUS.format("'Guide loaded'"))
        bar.spacer(flex=1)
        bar.menuline(group=True).span('^guide.info', id='guide-info')
        page.p('Only structure and approved descriptions go to the model; result rows never do. '
               'Hidden tables and columns are excluded from future result encoding.',
               class_='notice')
        page.textBoxArea(value='^.notes', lbl='Database explanations for the model', rows=3,
                         lbl_position='TL', width='100%', id='guide-notes')
        split = page.borderContainer(flex='1', min_height=0)
        left = split.contentPane(region='center', overflow='hidden')
        tables = left.frameGrid(storepath='guide.tables', rowMode='values', searchOn=True,
                                height='100%', grid_id='guide-tables')
        struct = tables.grid.struct()
        struct.column('table', name='Table', width='200px')
        struct.column('description', name='Description for the model', width='360px', edit=True)
        struct.column('hidden', name='Hidden', dtype='B', width='80px', edit=True)
        right = split.contentPane(region='right', width='38%', splitter=True, overflow='hidden')
        columns = right.frameGrid(storepath='guide.columns', rowMode='values', searchOn=True,
                                  height='100%', grid_id='guide-columns')
        struct = columns.grid.struct()
        struct.column('table', name='Table', width='160px')
        struct.column('column', name='Column', width='160px')
        struct.column('hidden', name='Hidden', dtype='B', width='80px', edit=True)
        self.save_bar(page)
        self.status(page, 'guide.status')

    def save_bar(self, page):
        bar = page.menu(presentation='bar', aria_label='Save enrollment', padding='4px 8px')
        bar.spacer(flex=1)
        actions = bar.menuline(group=True)
        for label, approve, key in (('Save draft', False, 'save'),
                                    ('Confirm enrollment', True, 'approve')):
            actions.button(label, id=f'guide-{key}').dataRpc(
                'save_guide', database='=guide.database', revision='=guide.revision',
                notes='=guide.notes', tables='=guide.tables', columns='=guide.columns',
                approve=approve, _onError=ERROR,
                _onResult=LOADED + STATUS.format("'Saved'"))
