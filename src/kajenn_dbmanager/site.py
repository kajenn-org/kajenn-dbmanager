"""The Kajenn site recipe of a standalone DB Manager server."""

from kajenn.config.templates import DefaultConfiguration

from .app import DbManagerApp, DbManagerWorker


def site(*, ui=False, access_mode='local'):
    """A recipe with the service at the root and, with ``ui``, the workbench at ``/ui/``."""

    class DbManagerSite(DefaultConfiguration):
        def applications_section(self, cfg):
            applications = cfg.applications()
            applications.application(code='dbmanager', mount='', app_class=DbManagerApp,
                                     access_mode=access_mode)
            applications.application(code='dbmanager_worker', mount='_dbmanager_worker',
                                     app_class=DbManagerWorker)
            if ui:
                from .ui_app import DbManagerUI

                applications.application(code='ui', mount='ui', app_class=DbManagerUI,
                                         access_mode=access_mode).request(body='raw')

    return DbManagerSite
