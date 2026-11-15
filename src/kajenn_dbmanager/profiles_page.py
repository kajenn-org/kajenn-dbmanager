"""Workbench pages that list database profiles and register new ones."""

from genro_bag import Bag
from gramlot import endpoint

from .access import caller
from .workbench_page import WorkbenchPage, as_bag


class ProfilesPage(WorkbenchPage):
    """A frameGrid of the caller's profiles and a registration dialog.

    Subclasses name the Data root, the registration action, the profile source
    they list (``None`` for every source) and the fields of the dialog.
    """

    root_path = 'profiles'
    source_kind = None
    register_action = 'register'
    dialog_title = 'Register'

    @endpoint
    def profiles(self, **kwargs):
        """The caller's profiles of ``source_kind``, as grid rows."""
        app = self.dbmanager
        owner, admin = caller(self.request_identity, app.access_mode)
        listed = app.workbench.call('list', {}, owner, admin)['databases']
        if self.source_kind is not None:
            listed = [item for item in listed if item['source'].get('kind') == self.source_kind]
        return as_bag(listed)

    def main(self, root):
        base = self.root_path
        page = root.main(datapath=base, height='100vh', display='flex',
                         flex_direction='column', padding='12px', gap='8px', min_height=0)
        page.dataSetter('.rows', Bag())
        frame = page.frameGrid(storepath='.rows', rowMode='values', searchOn=True,
                               flex='1', min_height=0, grid_id=f'{base}-grid')
        self.columns(frame.grid.struct())
        top = frame.top.menu(presentation='bar', aria_label=f'{self.title} commands',
                             padding='4px 8px')
        top.menuline(group=True).strong(self.title)
        top.spacer(flex=1)
        actions = top.menuline(group=True)
        actions.button('Refresh', id=f'{base}-refresh',
                       action=f"this.SET('{base}.refresh', Date.now())")
        actions.button(self.dialog_title, id=f'{base}-register',
                       action=f"this.SET('{base}.dialog', true)")
        page.dataRpc('profiles', refresh='^.refresh', _onStart=True,
                     _onCalling=f"this.SET('{base}.status', 'Loading profiles…')",
                     _onError=f"this.SET('{base}.status', error.message)",
                     _onResult=f"this.GET('{base}.rows').replace(result);"
                               f"this.SET('{base}.status', null)")
        self.status(page, f'{base}.status')
        self.registration(page)

    def columns(self, struct):
        struct.column('database', name='Profile', width='200px')
        struct.column('source_kind', name='Source', width='120px')
        struct.column('source_instance', name='Genropy instance', width='180px')
        struct.column('enrollment', name='AI enrollment', width='140px')

    def fields(self, form):
        """The registration fields, bound below ``<root_path>.form``."""
        raise NotImplementedError

    def registration(self, page):
        base = self.root_path
        dialog = page.dialog(title=self.dialog_title, open='^.dialog', width='30rem',
                             height='26rem', movable=True, resizable=True)
        frame = dialog.frame
        center = frame.center.contentPane(padding='12px', overflow='auto')
        form = center.formlet(datapath=f'{base}.form', columns=1, lbl_position='L')
        form.textbox(value='^.database', lbl='Profile name', id=f'{base}-profile')
        self.fields(form)
        center.p('The storage key must already be configured (1Password or server environment). '
                 'Existing profiles are never overwritten.', class_='muted')
        footer = frame.bottom.menu(presentation='bar', padding='4px 8px')
        footer.spacer(flex=1)
        buttons = footer.menuline(group=True)
        buttons.button('Cancel', action=f"this.SET('{base}.dialog', false)")
        save = buttons.button('Check & register', id=f'{base}-submit')
        save.dataRpc('workbench', action=self.register_action, data=f'={base}.form',
                     _onResult=f"this.SET('{base}.form.connection.password', null);"
                               f"this.SET('{base}.dialog', false);"
                               f"this.SET('{base}.status', 'Registered ' + result.getItem('database'));"
                               f"this.SET('{base}.refresh', Date.now())",
                     _onError=f"this.SET('{base}.form.connection.password', null);"
                              f"this.SET('{base}.status', error.message)")
