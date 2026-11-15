"""Backups of a profile: create, list, verify and restore into an empty database."""

from genro_bag import Bag

from kajenn_dbmanager.workbench_page import WorkbenchPage

STATUS = "this.SET('backups.status', {})"
ERROR = STATUS.format('error.message')


class Page(WorkbenchPage):
    title = 'Backup & restore'

    def main(self, root):
        page = root.main(datapath='backups', height='100vh', display='flex',
                         flex_direction='column', padding='12px', gap='8px', min_height=0)
        page.dataSetter('.rows', Bag())
        self.load_profiles(page)
        frame = page.frameGrid(storepath='.rows', rowMode='values', searchOn=True, flex='1',
                               min_height=0, grid_id='backups-grid',
                               selected_backup_id='^.selected')
        struct = frame.grid.struct()
        struct.column('backup_id', name='Backup', width='280px')
        struct.column('database', name='Database', width='160px')
        struct.column('created_at', name='Created (UTC)', width='220px')
        struct.column('size_bytes', name='Size (bytes)', dtype='L', width='120px', align='end')
        struct.column('format', name='Format', width='150px')
        self.toolbar(frame.top.menu(presentation='bar', aria_label='Backup commands',
                                    padding='4px 8px'))
        page.dataRpc('workbench', action='backups', data_database='^.database',
                     refresh='^.refresh', _if='data_database', _onError=ERROR,
                     _onResult="this.GET('backups.rows').replace(result.getItem('backups'))")
        self.status(page, 'backups.status')
        self.restore_dialog(page)

    def toolbar(self, top):
        self.database_select(top.menuline(group=True), '^backups.database',
                             lbl='Source database', id='backups-database')
        top.spacer(flex=1)
        actions = top.menuline(group=True)
        actions.button('Refresh', id='backups-refresh',
                       action="this.SET('backups.refresh', Date.now())")
        create = actions.button('Create backup', id='backups-create')
        create.dataRpc('workbench', action='backup', data_database='=backups.database',
                       _onCalling=STATUS.format("'Creating backup…'"), _onError=ERROR,
                       _onResult=STATUS.format("'Created ' + result.getItem('backup_id')")
                       + ";this.SET('backups.refresh', Date.now())")
        verify = actions.button('Verify selected', id='backups-verify')
        verify.dataRpc('workbench', action='verify_backup', data_database='=backups.database',
                       data_backup_id='=backups.selected', _onError=ERROR,
                       _onResult=STATUS.format("'Verified ' + result.getItem('backup_id')"))
        actions.button('Restore selected…', id='backups-restore',
                       action="this.SET('backups.dialog', true)")

    def restore_dialog(self, page):
        dialog = page.dialog(title='Restore into an existing empty database', open='^.dialog',
                             width='32rem', height='20rem', movable=True, resizable=True)
        frame = dialog.frame
        center = frame.center.contentPane(padding='12px', overflow='auto')
        form = center.formlet(columns=1, lbl_position='L')
        form.div('^backups.selected', lbl='Backup')
        self.database_select(form, '^backups.destination', lbl='Destination',
                             id='backups-destination')
        form.textbox(value='^backups.confirm', lbl='Type the destination name',
                     id='backups-confirm')
        center.p('Only archives created here for the selected source profile are listed. '
                 'Restore never overwrites a populated database.', class_='muted')
        footer = frame.bottom.menu(presentation='bar', padding='4px 8px')
        footer.spacer(flex=1)
        buttons = footer.menuline(group=True)
        buttons.button('Cancel', action="this.SET('backups.dialog', false)")
        restore = buttons.button('Restore', id='backups-restore-submit')
        restore.dataRpc('workbench', action='restore', data_database='=backups.destination',
                        data_source_database='=backups.database',
                        data_backup_id='=backups.selected', data_confirm_database='=backups.confirm',
                        _onCalling=STATUS.format("'Restoring…'"), _onError=ERROR,
                        _onResult="this.SET('backups.dialog', false);this.SET('backups.confirm', null);"
                                  + STATUS.format("'Restored into ' + result.getItem('database')"))
