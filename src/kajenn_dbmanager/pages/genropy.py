"""Profiles imported from Genropy legacy instances installed on this server."""

from kajenn_dbmanager.profiles_page import ProfilesPage


class Page(ProfilesPage):
    title = 'Genropy legacy instances'
    root_path = 'genropy'
    source_kind = 'genropy'
    register_action = 'register_genropy'
    dialog_title = 'Register Genropy instance'

    def fields(self, form):
        form.textbox(value='^.instance', lbl='Instance name', id='genropy-instance')
        form.div('Uses the Genropy configuration installed on this server and imports the '
                 'primary PostgreSQL connection.', class_='muted')
