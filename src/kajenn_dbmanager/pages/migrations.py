"""Read a database structure, review a migration plan and apply it."""

import json

from genro_bag import Bag
from gramlot import endpoint

from kajenn_dbmanager.workbench_page import WorkbenchPage

STATUS = "this.SET('migrations.status', {})"
ERROR = STATUS.format('error.message')


def _text(sql):
    return '\n'.join(sql) if isinstance(sql, list) else (sql or '')


class Page(WorkbenchPage):
    title = 'Migrations'

    @endpoint
    def read_structure(self, database, **kwargs):
        """The current structure of ``database`` as indented Migration JSON."""
        return json.dumps(self.run('introspect', database=database), indent=2, sort_keys=True)

    @endpoint
    def preview_plan(self, database, structure, allow_removals=False, **kwargs):
        """The reviewed plan of moving ``database`` to ``structure`` (Migration JSON text)."""
        plan = self.run('plan', database=database, structure=json.loads(structure),
                        allow_removals=bool(allow_removals))
        result = Bag()
        result.set_item('plan_id', plan['plan_id'])
        result.set_item('sql', _text(plan['sql']) or '-- No changes')
        result.set_item('warnings', '\n'.join(str(w) for w in plan.get('warnings') or []))
        result.set_item('empty', bool(plan.get('empty')))
        return result

    @endpoint
    def apply_plan(self, database, structure, expected_plan, confirm, allow_removals=False,
                   **kwargs):
        """Apply the reviewed plan; the database name must be typed as confirmation."""
        result = self.run('apply', database=database, structure=json.loads(structure),
                          expected_plan=expected_plan, confirm_database=confirm,
                          allow_removals=bool(allow_removals))
        return f"Applied; verified={result.get('verified')}"

    def main(self, root):
        page = root.main(datapath='migrations', height='100vh', display='flex',
                         flex_direction='column', padding='12px', gap='8px', min_height=0)
        self.load_profiles(page)
        page.dataSetter('.structure', '')
        page.dataSetter('.plan.sql', '')
        page.dataFormula('.noplan', '!plan_id', plan_id='^.plan.plan_id')
        bar = page.menu(presentation='bar', aria_label='Migration commands', padding='4px 8px')
        self.database_select(bar.menuline(group=True), '^migrations.database',
                             id='migrations-database')
        bar.spacer(flex=1)
        actions = bar.menuline(group=True)
        read = actions.button('Read structure', id='migrations-read')
        read.dataRpc('read_structure', result_path='migrations.structure',
                     database='=migrations.database', _onError=ERROR,
                     _onResult="this.SET('migrations.plan.plan_id', null);this.SET('migrations.plan.sql', '');"
                               + STATUS.format("'Current structure loaded'"))
        tabs = page.tabContainer(selectedPage='^.tab', flex='1', min_height=0)
        target = tabs.contentPane(title='Target structure', pageName='target', overflow='hidden')
        target.codeMirror(value='^migrations.structure', language='json', height='100%',
                          id='migrations-structure')
        plan = tabs.contentPane(title='Migration plan', pageName='plan', overflow='auto')
        plan.codeMirror(value='^migrations.plan.sql', language='sql', readonly=True,
                        height='360px', id='migrations-sql')
        plan.pre('^migrations.plan.warnings', class_='muted')
        self.apply_bar(page)
        self.status(page, 'migrations.status')

    def apply_bar(self, page):
        bar = page.menu(presentation='bar', aria_label='Plan and apply', padding='4px 8px')
        bar.menuline(group=True).checkbox(value='^migrations.allow_removals',
                                          label='Allow removals', id='migrations-removals')
        preview = bar.menuline(group=True).button('Preview plan', id='migrations-preview')
        preview.dataRpc('preview_plan', result_path='migrations.plan',
                        database='=migrations.database', structure='=migrations.structure',
                        allow_removals='=migrations.allow_removals', _onError=ERROR,
                        _onResult="this.SET('migrations.tab', 'plan');"
                                  + STATUS.format("'Plan ' + result.getItem('plan_id')"))
        bar.spacer(flex=1)
        confirm = bar.menuline(group=True)
        confirm.textbox(value='^migrations.confirm', placeholder='Type the database name',
                        id='migrations-confirm')
        apply = confirm.button('Apply reviewed plan', id='migrations-apply',
                               disabled='^migrations.noplan')
        apply.dataRpc('apply_plan', database='=migrations.database',
                      structure='=migrations.structure',
                      expected_plan='=migrations.plan.plan_id', confirm='=migrations.confirm',
                      allow_removals='=migrations.allow_removals', _onError=ERROR,
                      _onResult="this.SET('migrations.plan.plan_id', null);"
                                "this.SET('migrations.confirm', null);" + STATUS.format('result'))
