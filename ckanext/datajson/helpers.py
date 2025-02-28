try:
    from collections import OrderedDict  # 2.7
except ImportError:
    from sqlalchemy.util import OrderedDict

import logging

from pylons import config
from ckan import plugins as p
from ckan.lib import helpers as h
from ckan.logic import NotFound, get_action, check_access
from ckan.lib.munge import munge_title_to_name
import re
import simplejson as json

REDACTED_REGEX = re.compile(
    r'^(\[\[REDACTED).*?(\]\])$'
)

REDACTED_TAGS_REGEX = re.compile(
    r'\[\[/?REDACTED(-EX\sB\d)?\]\]'
)

PARTIAL_REDACTION_REGEX = re.compile(
    r'\[\[REDACTED-EX B[\d]\]\](.*?\[\[/REDACTED\]\])'
)

log = logging.getLogger(__name__)


def get_reference_date(date_str):
    """
        Gets a reference date extra created by the harvesters and formats it
        nicely for the UI.

        Examples:
            [{"type": "creation", "value": "1977"}, {"type": "revision", "value": "1981-05-15"}]
            [{"type": "publication", "value": "1977"}]
            [{"type": "publication", "value": "NaN-NaN-NaN"}]

        Results
            1977 (creation), May 15, 1981 (revision)
            1977 (publication)
            NaN-NaN-NaN (publication)
    """
    try:
        out = []
        for date in h.json.loads(date_str):
            value = h.render_datetime(date['value']) or date['value']
            out.append('{0} ({1})'.format(value, date['type']))
        return ', '.join(out)
    except (ValueError, TypeError):
        return date_str


def get_responsible_party(value):
    """
        Gets a responsible party extra created by the harvesters and formats it
        nicely for the UI.

        Examples:
            [{"name": "Complex Systems Research Center", "roles": ["pointOfContact"]}]
            [{"name": "British Geological Survey", "roles": ["custodian", "pointOfContact"]},
             {"name": "Natural England", "roles": ["publisher"]}]

        Results
            Complex Systems Research Center (pointOfContact)
            British Geological Survey (custodian, pointOfContact); Natural England (publisher)
    """
    if not value:
        return None

    formatted = {
        'resourceProvider': p.toolkit._('Resource Provider'),
        'pointOfContact': p.toolkit._('Point of Contact'),
        'principalInvestigator': p.toolkit._('Principal Investigator'),
    }

    try:
        out = []
        parties = h.json.loads(value)
        for party in parties:
            roles = [formatted[role] if role in formatted.keys() else p.toolkit._(role.capitalize()) for role in
                     party['roles']]
            out.append('{0} ({1})'.format(party['name'], ', '.join(roles)))
        return '; '.join(out)
    except (ValueError, TypeError):
        pass
    return value


def get_common_map_config():
    """
        Returns a dict with all configuration options related to the common
        base map (ie those starting with 'ckanext.spatial.common_map.')
    """
    namespace = 'ckanext.spatial.common_map.'
    return dict([(k.replace(namespace, ''), v) for k, v in config.iteritems() if k.startswith(namespace)])


def strip_if_string(val):
    """
    :param val: any
    :return: str|None
    """
    if isinstance(val, (str, unicode)):
        val = val.strip()
        if '' == val:
            val = None
    return val


def get_export_map_json(map_filename):
    """
    Reading json export map from file
    :param map_filename: str
    :return: obj
    """
    import os

    map_path = os.path.join(os.path.dirname(__file__), 'export_map', map_filename)

    if not os.path.isfile(map_path):
        log.warn("Could not find %s ! Please create it. Use samples from same folder", map_path)
        map_path = os.path.join(os.path.dirname(__file__), 'export_map', 'export.catalog.map.sample.json')

    with open(map_path, 'r') as export_map_json:
        json_export_map = json.load(export_map_json, object_pairs_hook=OrderedDict)

    return json_export_map


def get_data_processor_json(filename):
    """
    Reading json data processor from file
    :param filename: str
    :return: obj
    """
    import os

    path = os.path.join(os.path.dirname(__file__), 'data_processors', filename)

    if not os.path.isfile(path):
        log.warn("Could not find %s ! Please create it. Use samples from same folder", path)
        path = os.path.join(os.path.dirname(__file__), 'export_map', 'export.catalog.map.sample.json')

    with open(path, 'r') as data:
        data_json = json.load(data, object_pairs_hook=OrderedDict)

    return data_json

def detect_publisher(extras):
    """
    Detect publisher by package extras
    :param extras: dict
    :return: str
    """
    publisher = None

    if 'publisher' in extras and extras['publisher']:
        publisher = strip_if_string(extras['publisher'])

    for i in range(1, 6):
        key = 'publisher_' + str(i)
        if key in extras and extras[key] and strip_if_string(extras[key]):
            publisher = strip_if_string(extras[key])
    return publisher


def is_redacted(value):
    """
    Checks if value is valid POD v1.1 [REDACTED-*]
    :param value: str
    :return: bool
    """
    return isinstance(value, (str, unicode)) and REDACTED_REGEX.match(value)


def get_validator(schema_type="federal-v1.1"):
    """
    Get POD json validator object
    :param schema_type: str
    :return: obj
    """
    import os
    from jsonschema import Draft4Validator, FormatChecker

    schema_path = os.path.join(os.path.dirname(__file__), 'pod_schema', schema_type, 'dataset.json')
    with open(schema_path, 'r') as schema:
        schema = json.loads(schema.read())
        return Draft4Validator(schema, format_checker=FormatChecker())


def uglify(key):
    """
    lower string and remove spaces
    :param key: string
    :return: string
    """
    if isinstance(key, (str, unicode)):
        return "".join(key.lower().split()).replace('_', '').replace('-', '')
    return key


def get_extra(package, key, default=None):
    """
    Retrieves the value of an extras field.
    """
    return packageExtraCache.get(package, key, default)


def publisher_to_org(publisher_name, context):
    """ create (if not exists) an organization from a publisher """
    
    name = munge_title_to_name(publisher_name).replace('_', '-')
    check_access('organization_show', context, {'id': name})

    try:
        org = get_action('organization_show')(context, {'id': name})
    except NotFound:
        context.pop('__auth_audit', None)
        log.error('Publisher as ORG not found. Creating')    
        org_base = {'title': publisher_name, 'name': name}
        check_access('organization_create', context, org_base)
        org = get_action('organization_create')(context, org_base)

    log.info('Pub: {} to org: {}'.format(publisher_name, org))
    return org


class PackageExtraCache:
    def __init__(self):
        self.pid = None
        self.extras = {}
        pass

    def store(self, package):
        import sys, os

        try:
            self.pid = package.get('id')

            current_extras = package.get('extras', [])
            new_extras = {}
            for extra in current_extras:
                if 'extras_rollup' == extra.get('key'):
                    rolledup_extras = json.loads(extra.get('value'))
                    for k, value in rolledup_extras.iteritems():
                        if isinstance(value, (list, tuple)):
                            value = ", ".join(map(unicode, value))
                        new_extras[uglify(k)] = value
                else:
                    value = extra.get('value')
                    if isinstance(value, (list, tuple)):
                        value = ", ".join(map(unicode, value))
                    new_extras[uglify(extra['key'])] = value

            self.extras = new_extras
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            filename = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error("%s : %s : %s : %s", exc_type, filename, exc_tb.tb_lineno, unicode(e))
            raise e

    def get(self, package, key, default=None):
        if self.pid != package.get('id'):
            self.store(package)
        return strip_if_string(self.extras.get(uglify(key), default))


packageExtraCache = PackageExtraCache()

# used by get_accrual_periodicity
accrual_periodicity_dict = {
    'completely irregular': 'irregular',
    'decennial': 'R/P10Y',
    'quadrennial': 'R/P4Y',
    'annual': 'R/P1Y',
    'bimonthly': 'R/P2M',  # or R/P0.5M
    'semiweekly': 'R/P3.5D',
    'daily': 'R/P1D',
    'biweekly': 'R/P2W',  # or R/P0.5W
    'semiannual': 'R/P6M',
    'biennial': 'R/P2Y',
    'triennial': 'R/P3Y',
    'three times a week': 'R/P0.33W',
    'three times a month': 'R/P0.33M',
    'continuously updated': 'R/PT1S',
    'monthly': 'R/P1M',
    'quarterly': 'R/P3M',
    'every five years': 'R/P5Y',
    'every eight years': 'R/P8Y',
    'semimonthly': 'R/P0.5M',
    'three times a year': 'R/P4M',
    'weekly': 'R/P1W',
    'hourly': 'R/PT1H',
    'continual': 'R/PT1S',
    'fortnightly': 'R/P0.5M',
    'annually': 'R/P1Y',
    'biannualy': 'R/P0.5Y',
    'asneeded': 'irregular',
    'irregular': 'irregular',
    'notplanned': 'irregular',
    'unknown': 'irregular',
    'not updated': 'irregular'
}

reverse_accrual_periodicity_dict = dict((v, k[0].upper() + k[1:].lower())
                                        for k, v
                                        in accrual_periodicity_dict.iteritems()
                                        if v.startswith('R/'))
reverse_accrual_periodicity_dict['irregular'] = 'Irregular'
reverse_accrual_periodicity_dict['R/P0.25Y'] = 'Quarterly'
