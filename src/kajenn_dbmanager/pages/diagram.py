"""Interactive diagram of a database, with keys, indexes and constraints per table."""

from genro_bag import Bag
from gramlot import endpoint

from kajenn_dbmanager.workbench_page import WorkbenchPage, as_bag

STATUS = "this.SET('diagram.status', {})"


class Page(WorkbenchPage):
    title = 'Database diagram'

    @endpoint
    def draw(self, database, **kwargs):
        """Publish a fresh diagram snapshot of ``database``; return its URL and table details."""
        result = self.run('diagram', database=database)
        answer = Bag()
        answer.set_item('url', result['url'])
        answer.set_item('computed_at', result['computed_at'])
        answer.set_item('details', as_bag(result['table_details']))
        return answer

    def main(self, root):
        page = root.main(datapath='diagram', height='100vh', display='flex',
                         flex_direction='column', min_height=0)
        self.load_profiles(page)
        page.dataSetter('.details', Bag())
        bar = page.menu(presentation='bar', aria_label='Diagram commands', padding='4px 8px')
        self.database_select(bar.menuline(group=True), '^diagram.database', id='diagram-database')
        draw = bar.menuline(group=True).button('Draw / refresh', id='diagram-draw')
        draw.dataRpc('draw', database='=diagram.database',
                     _onCalling=STATUS.format("'Reading the structure…'"),
                     _onError=STATUS.format('error.message'),
                     _onResult="this.SET('diagram.url', result.getItem('url'));"
                               "this.GET('diagram.details').replace(result.getItem('details'));"
                               + STATUS.format("'Computed at ' + result.getItem('computed_at')"))
        bar.spacer(flex=1)
        bar.menuline(group=True).a('Full page ↗', href='^diagram.url', target='_blank',
                                   rel='noopener', id='diagram-full')
        frame = page.borderContainer(flex='1', min_height=0)
        center = frame.contentPane(region='center', overflow='hidden')
        center.iframe(src='^diagram.url', title='Database tables and relationships',
                      width='100%', height='100%', border=0, id='diagram-frame')
        side = frame.contentPane(region='right', width='320px', splitter=True, overflow='auto',
                                 padding='8px')
        side.strong('Keys, indexes and constraints')
        side.tree(storepath='diagram.details', id='diagram-details')
        self.status(page, 'diagram.status')
