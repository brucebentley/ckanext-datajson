import logging
import re

import ckan.plugins as p
from flask import Blueprint

from logging import getLogger
from ckanext.harvest.log import DBLogHandler
from ckanext.datajson.views import DataJsonViews, map_filename

logger = logging.getLogger(__name__)

request = p.toolkit.request

try:
    from collections import OrderedDict  # 2.7
except ImportError:
    from sqlalchemy.util import OrderedDict


class DataJsonPlugin(p.SingletonPlugin):
    p.implements(p.interfaces.IConfigurer)
    p.implements(p.ITemplateHelpers)
    p.implements(p.interfaces.IRoutes, inherit=True)
    p.implements(p.IBlueprint)

    # Class Attributes
    route_path = ''
    route_enabled = ''
    route_ld_path = ''
    ld_id = ''
    ld_title = ''
    map_filename = ''
    site_url = ''
    inventory_links_enabled = ''
    route_edata_path = ''
    datajson_blueprint = Blueprint('datajson', __name__, url_prefix='/')

    def configure(self, config):

        self.startup = True
        # Configure database logger to save in HarvesterLog
        _configure_db_logger(config)

        self.startup = False

    def update_config(self, config):
        # Must use IConfigurer rather than IConfigurable because only IConfigurer
        # is called before after_map, in which we need the configuration directives
        # to know how to set the paths.

        # TODO commenting out enterprise data inventory for right now
        # DataJsonPlugin.route_edata_path = config.get("ckanext.enterprisedatajson.path", "/enterprisedata.json")
        self.route_enabled = config.get("ckanext.datajson.url_enabled", "True") == 'True'
        self.route_path = config.get("ckanext.datajson.path", "/data.json")
        self.route_ld_path = config.get("ckanext.datajsonld.path", re.sub(r"\.json$", ".jsonld", self.route_path))
        self.ld_id = config.get("ckanext.datajsonld.id", config.get("ckan.site_url"))
        self.ld_title = config.get("ckan.site_title", "Catalog")
        self.site_url = config.get("ckan.site_url")
        self.map_filename = map_filename

        self.inventory_links_enabled = config.get("ckanext.datajson.inventory_links_enabled", "False") == 'True'

        # Adds our local templates directory. It's smart. It knows it's
        # relative to the path of *this* file. Wow.
        p.toolkit.add_template_directory(config, "templates")

    def _datajson_inventory_links_enabled(self):
        return self.inventory_links_enabled

    def get_helpers(self):
        return {
            'datajson_inventory_links_enabled': self._datajson_inventory_links_enabled
        }

    # def before_map(self, m):
    #     return m

    # def after_map(self, m):
    #     if self.route_enabled:
    #         # /data.json and /data.jsonld (or other path as configured by user)
    #         m.connect('datajson_export', self.route_path,
    #                   controller='ckanext.datajson.views:DataJsonViews', action='generate_json')
    #         m.connect('organization_export', '/organization/{org_id}/data.json',
    #                   controller='ckanext.datajson.views:DataJsonViews', action='generate_org_json')
    #         # TODO commenting out enterprise data inventory for right now
    #         # m.connect('enterprisedatajson', DataJsonPlugin.route_edata_path,
    #         # controller='ckanext.datajson.plugin:DataJsonController', action='generate_enterprise')

    #         # m.connect('datajsonld', DataJsonPlugin.route_ld_path,
    #         # controller='ckanext.datajson.plugin:DataJsonController', action='generate_jsonld')

    #     if self.inventory_links_enabled:
    #         m.connect('public_data_listing', '/organization/{org_id}/redacted.json',
    #                   controller='ckanext.datajson.views:DataJsonViews', action='generate_redacted')

    #         m.connect('enterprise_data_inventory', '/organization/{org_id}/unredacted.json',
    #                   controller='ckanext.datajson.views:DataJsonViews', action='generate_unredacted')

    #         m.connect('enterprise_data_inventory', '/organization/{org_id}/draft.json',
    #                   controller='ckanext.datajson.views:DataJsonViews', action='generate_draft')
    #     return m
    
    def get_blueprint(self):
        datajson_views = DataJsonViews()

        ## Register Blueprints
        if self.route_enabled:
            # datajson_export
            self.datajson_blueprint.add_url_rule(self.route_path,
                view_func=datajson_views.generate_json)
            # organization_export
            self.datajson_blueprint.add_url_rule('/organization/<org_id>/data.json',
                view_func=datajson_views.generate_org_json)

        if self.inventory_links_enabled:
            # public_data_listing
            self.datajson_blueprint.add_url_rule('/organization/<org_id>/redacted.json',
                view_func=datajson_views.generate_redacted)
            # enterprise_data_inventory
            self.datajson_blueprint.add_url_rule('/organization/<org_id>/unredacted.json',
                view_func=datajson_views.generate_unredacted)
            # enterprise_data_inventory
            self.datajson_blueprint.add_url_rule('/organization/<org_id>/draft.json',
                view_func=datajson_views.generate_draft)

        # datajsonvalidator
        self.datajson_blueprint.add_url_rule('/pod/validate',
            view_func=datajson_views.validator, methods=['GET', 'POST'])
        # harvester_versions
        self.datajson_blueprint.add_url_rule('/harvester_versions',
            view_func=datajson_views.get_versions)
    
        return [self.datajson_blueprint]


def _configure_db_logger(config):
    # Log scope
    #
    # -1 - do not log to the database
    #  0 - log everything
    #  1 - model, logic.action, logic.validators, harvesters
    #  2 - model, logic.action, logic.validators
    #  3 - model, logic.action
    #  4 - logic.action
    #  5 - model
    #  6 - plugin
    #  7 - harvesters
    #
    scope = p.toolkit.asint(config.get('ckan.harvest.log_scope', -1))
    if scope == -1:
        return

    parent_logger = 'ckanext.datajson'
    children = ['plugin', 'model', 'logic.action.create', 'logic.action.delete',
                'logic.action.get',  'logic.action.patch', 'logic.action.update',
                'logic.validators',
                'harvester_base', 'helpers',
                'harvester_cmsdatanavigator',
                'harvester_datajson', 'parse_datajson']

    children_ = {0: children, 1: children[1:], 2: children[1:-2],
                 3: children[1:-3], 4: children[2:-3], 5: children[1:2],
                 6: children[:1], 7: children[-2:]}

    # Get log level from config param - default: DEBUG
    from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL
    level = config.get('ckan.harvest.log_level', 'debug').upper()
    if level == 'DEBUG':
        level = DEBUG
    elif level == 'INFO':
        level = INFO
    elif level == 'WARNING':
        level = WARNING
    elif level == 'ERROR':
        level = ERROR
    elif level == 'CRITICAL':
        level = CRITICAL
    else:
        level = DEBUG

    loggers = children_.get(scope)

    # Get root logger and set db handler
    logger = getLogger(parent_logger)
    if scope < 1:
        logger.addHandler(DBLogHandler(level=level))

    # Set db handler to all child loggers
    for _ in loggers:
        child_logger = logger.getChild(_)
        child_logger.addHandler(DBLogHandler(level=level))
