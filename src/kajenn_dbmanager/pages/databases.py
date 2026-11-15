"""Registered database profiles, and the registration of a new one."""

from genro_bag import Bag

from kajenn_dbmanager.workbench_page import WorkbenchPage

ERROR = "this.SET('.status', error.message)"


class Page(WorkbenchPage):
    title = 'Databases'

    def main(self, root):
        page = root.main(datapath='databases', height='100vh', display='flex',
                         flex_direction='column', padding='12px', gap='8px', min_height=0)
        page.dataSetter('.rows', Bag())
        frame = page.frameGrid(storepath='.rows', rowMode='values', searchOn=True,
                               flex='1', min_height=0, grid_id='databases-grid')
        struct = frame.grid.struct()
        struct.column('database', name='Profile', width='200px')
        struct.column('source_kind', name='Source', width='120px')
        struct.column('source_instance', name='Genropy instance', width='180px')
        struct.column('enrollment', name='AI enrollment', width='140px')
        top = frame.top.menu(presentation='bar', aria_label='Database commands', padding='4px 8px')
        top.menuline(group=True).strong('Registered databases')
        top.spacer(flex=1)
        actions = top.menuline(group=True)
        actions.button('Refresh', id='databases-refresh',
                       action="this.SET('databases.refresh', Date.now())")
        actions.button('Register database', id='databases-register',
                       action="this.SET('databases.dialog', true)")
        page.dataRpc('workbench', action='list', refresh='^.refresh', _onStart=True,
                     _onCalling="this.SET('databases.status', 'Loading profiles…')",
                     _onError=ERROR,
                     _onResult="this.GET('databases.rows').replace(result.getItem('databases'));"
                               "this.SET('databases.status', null)")
        self.status(page, 'databases.status')
        self.registration(page)

    def registration(self, page):
        dialog = page.dialog(title='Register database', open='^.dialog', width='30rem',
                             height='26rem', movable=True, resizable=True)
        frame = dialog.frame
        center = frame.center.contentPane(padding='12px', overflow='auto')
        form = center.formlet(datapath='databases.form', columns=1, lbl_position='L')
        form.textbox(value='^.database', lbl='Profile name', id='register-profile')
        form.textbox(value='^.connection.host', lbl='Host', default='localhost')
        form.numberTextBox(value='^.connection.port', lbl='Port', default=5432)
        form.textbox(value='^.connection.dbname', lbl='Database name', id='register-dbname')
        form.textbox(value='^.connection.user', lbl='User')
        form.passwordbox(value='^.connection.password', lbl='Password')
        center.p('The storage key must already be configured (1Password or server environment). '
                 'Existing profiles are never overwritten.', class_='muted')
        footer = frame.bottom.menu(presentation='bar', padding='4px 8px')
        footer.spacer(flex=1)
        buttons = footer.menuline(group=True)
        buttons.button('Cancel', action="this.SET('databases.dialog', false)")
        save = buttons.button('Check & register', id='register-submit')
        save.dataRpc('workbench', action='register', data='=databases.form',
                     _onResult="this.SET('databases.form.connection.password', null);"
                               "this.SET('databases.dialog', false);"
                               "this.SET('databases.status', 'Registered ' + result.getItem('database'));"
                               "this.SET('databases.refresh', Date.now())",
                     _onError="this.SET('databases.form.connection.password', null);"
                              "this.SET('databases.status', error.message)")
