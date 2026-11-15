"""Registered database profiles, and the registration of a PostgreSQL connection."""

from kajenn_dbmanager.profiles_page import ProfilesPage


class Page(ProfilesPage):
    title = 'Databases'
    root_path = 'databases'
    dialog_title = 'Register database'

    def fields(self, form):
        form.textbox(value='^.connection.host', lbl='Host', default='localhost')
        form.numberTextBox(value='^.connection.port', lbl='Port', default=5432)
        form.textbox(value='^.connection.dbname', lbl='Database name', id='databases-dbname')
        form.textbox(value='^.connection.user', lbl='User')
        form.passwordbox(value='^.connection.password', lbl='Password')
