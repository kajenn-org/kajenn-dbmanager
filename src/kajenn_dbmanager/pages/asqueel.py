"""Registered Asqueel configurations: configuration and object trees, comparison and migration."""

from genro_bag import Bag
from gramlot import endpoint

from kajenn_dbmanager.workbench_page import WorkbenchPage, as_bag

STATUS = "this.SET('asqueel.status', {})"
ERROR = STATUS.format('error.message')


def node_tree(node):
    """An inspection node as a tree Bag: caption ``name · type``, attributes and children below."""
    children = Bag()
    if node.get('attributes'):
        attributes = Bag()
        for key, value in node['attributes'].items():
            attributes.set_item(f'a_{len(attributes)}', str(value), {'caption': key})
        children.set_item('attributes', attributes, {'caption': 'attributes'})
    for child in node.get('children') or []:
        value, attributes = node_tree(child)
        children.set_item(f'n_{len(children)}', value, attributes)
    if 'value' in node and not node.get('children'):
        children.set_item('value', str(node['value']), {'caption': 'value'})
    return children, {'caption': f"{node['name']} · {node['type']}"}


def tree_bag(node):
    root = Bag()
    value, attributes = node_tree(node)
    root.set_item('root', value, attributes)
    return root


class Page(WorkbenchPage):
    title = 'Asqueel configurations'

    def asqueel(self, action, **data):
        return self.run(f'asqueel_{action}', **data)

    @endpoint
    def configurations(self, **kwargs):
        names = self.asqueel('list')['configurations']
        return ','.join(f'{name}:{name}' for name in names)

    @endpoint
    def inspect(self, configuration, **kwargs):
        result = self.asqueel('inspect', configuration=configuration)
        answer = Bag()
        answer.set_item('backend', result['backend'])
        answer.set_item('config', tree_bag(result['configuration_tree']))
        answer.set_item('objects', tree_bag(result['object_tree']))
        return answer

    @endpoint
    def compare(self, configuration, **kwargs):
        result = self.asqueel('compare', configuration=configuration)
        answer = Bag()
        answer.set_item('desired', as_bag(result['desired']))
        answer.set_item('current', as_bag(result['current']))
        return answer

    @endpoint
    def preview(self, configuration, allow_removals=False, **kwargs):
        plan = self.asqueel('plan', configuration=configuration,
                            allow_removals=bool(allow_removals))['plan']
        sql = plan['sql']
        answer = Bag()
        answer.set_item('plan_id', plan['plan_id'])
        answer.set_item('sql', ('\n'.join(sql) if isinstance(sql, list) else sql) or '-- No changes')
        return answer

    @endpoint
    def apply(self, configuration, expected_plan, confirm, allow_removals=False, **kwargs):
        result = self.asqueel('apply', configuration=configuration, expected_plan=expected_plan,
                              confirm_configuration=confirm, allow_removals=bool(allow_removals))
        return f"Applied; verified={result['result'].get('verified')}"

    def main(self, root):
        page = root.main(datapath='asqueel', height='100vh', display='flex',
                         flex_direction='column', padding='8px 12px', gap='8px', min_height=0)
        page.dataRpc('configurations', result_path='asqueel.names', _onStart=True, _onError=ERROR)
        for path in ('config', 'objects', 'desired', 'current'):
            page.dataSetter(f'.{path}', Bag())
        page.dataSetter('.sql', '')
        page.dataFormula('.noplan', '!plan_id', plan_id='^.plan_id')
        bar = page.menu(presentation='bar', aria_label='Configuration', padding='4px 8px')
        bar.menuline(group=True).filteringSelect(
            value='^asqueel.configuration', values='^asqueel.names', lbl='Configuration',
            placeholder='Select a configuration', id='asqueel-configuration')
        load = bar.menuline(group=True).button('Load configuration', id='asqueel-load')
        load.dataRpc('inspect', configuration='=asqueel.configuration', _onError=ERROR,
                     _onResult="this.GET('asqueel.config').replace(result.getItem('config'));"
                               "this.GET('asqueel.objects').replace(result.getItem('objects'));"
                               + STATUS.format("'Loaded · backend ' + result.getItem('backend')"))
        tabs = page.tabContainer(flex='1', min_height=0)
        self.pair(tabs.contentPane(title='Configuration & objects', overflow='hidden'),
                  ('config', 'Configuration Bag'), ('objects', 'Constructed objects'))
        self.migration(tabs.contentPane(title='Migration', overflow='hidden'))
        self.status(page, 'asqueel.status')

    def pair(self, pane, left, right):
        split = pane.borderContainer(height='100%')
        for region, (path, title) in (('center', left), ('right', right)):
            side = split.contentPane(region=region, overflow='auto', padding='8px',
                                     **({'width': '50%', 'splitter': True} if region == 'right' else {}))
            side.strong(title)
            side.tree(storepath=f'asqueel.{path}', labelAttribute='caption',
                      id=f'asqueel-tree-{path}')

    def migration(self, pane):
        frame = pane.div(height='100%', display='flex', flex_direction='column', gap='6px')
        bar = frame.menu(presentation='bar', aria_label='Migration commands', padding='4px 8px')
        compare = bar.menuline(group=True).button('Read / refresh comparison', id='asqueel-compare')
        compare.dataRpc('compare', configuration='=asqueel.configuration', _onError=ERROR,
                        _onResult="this.GET('asqueel.desired').replace(result.getItem('desired'));"
                                  "this.GET('asqueel.current').replace(result.getItem('current'));"
                                  + STATUS.format("'Comparison loaded'"))
        bar.menuline(group=True).checkbox(value='^asqueel.allow_removals',
                                          label='Allow supported removals')
        preview = bar.menuline(group=True).button('Preview plan', id='asqueel-preview')
        preview.dataRpc('preview', configuration='=asqueel.configuration',
                        allow_removals='=asqueel.allow_removals', _onError=ERROR,
                        _onResult="this.SET('asqueel.plan_id', result.getItem('plan_id'));"
                                  "this.SET('asqueel.sql', result.getItem('sql'));"
                                  + STATUS.format("'Plan ' + result.getItem('plan_id')"))
        bar.spacer(flex=1)
        confirm = bar.menuline(group=True)
        confirm.textbox(value='^asqueel.confirm', placeholder='Type the configuration name',
                        id='asqueel-confirm')
        apply = confirm.button('Apply reviewed plan', id='asqueel-apply',
                               disabled='^asqueel.noplan')
        apply.dataRpc('apply', configuration='=asqueel.configuration',
                      expected_plan='=asqueel.plan_id', confirm='=asqueel.confirm',
                      allow_removals='=asqueel.allow_removals', _onError=ERROR,
                      _onResult="this.SET('asqueel.plan_id', null);this.SET('asqueel.confirm', null);"
                                + STATUS.format('result'))
        trees = frame.div(flex='1', min_height=0)
        self.pair(trees, ('desired', 'Desired · Asqueel migration JSON'),
                  ('current', 'Current · database JSON'))
        frame.codeMirror(value='^asqueel.sql', language='sql', readonly=True, height='200px',
                         id='asqueel-sql')
