from gramlot import IndexPage

from kajenn_dbmanager.workbench_page import navigation


class Page(IndexPage):
    title = 'DB Manager'
    navigation = navigation()
