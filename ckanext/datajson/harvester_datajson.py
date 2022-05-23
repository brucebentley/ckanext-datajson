from ckanext.datajson.harvester_base import DatasetHarvesterBase
from ckanext.datajson.parse_datajson import parse_datajson_entry
# from parse_dep_of_ed import parse_datajson_entry_for_dep_of_ed_schema
import logging
log = logging.getLogger(__name__)

from urllib.request import Request, urlopen
import json, ssl

class DataJsonHarvester(DatasetHarvesterBase):
    '''
    A Harvester for /data.json files.
    '''

    HARVESTER_VERSION = "0.9am"  # increment to force an update even if nothing has changed

    def info(self):
        return {
            'name': 'datajson',
            'title': '/data.json',
            'description': 'Harvests remote /data.json files',
        }

    def load_remote_catalog(self, harvest_job):
        url = harvest_job.source.url
        log.info('Loading catalog from URL: {}'.format(url))
        req = Request(url)
        # todo: into config and across harvester
        req.add_header('User-agent', 'Data.gov/2.0')

        try:
            conn = urlopen(req)
        except Exception as e:
            log.error('Failed to connect to {}: {} ({})'.format(url, e, type(e)))
            # try to avoid SSL errors
            try:
                conn = urlopen(req, context=ssl._create_unverified_context())
            except Exception as e:
                log.error('Failed (SSL) to connect to {}: {} ({})'.format(url, e, type(e)))
                raise

        data_readed = conn.read()
        # remove BOM_UTF8 if exists
        clean_data_readed, bom_removed = lstrip_bom(data_readed)
        if bom_removed:
            log.info('BOM_UTF8 removed from URL: {}'.format(url))

        try:
            datasets = json.loads(clean_data_readed)
        except UnicodeDecodeError:
            # try different encode
            log.error('Unicode Error at {}'.format(url))
            charsets = ['cp1252', 'iso-8859-1']
            datasets = None
            for charset in charsets:
                try:
                    data_decoded = clean_data_readed.decode(charset)
                    datasets = json.loads(data_decoded)
                    log.info('Charset detected {} for {}'.format(charset, url))
                    break
                except:
                    log.error('Failed to load URL {} with {} charset'.format(url, charset))
            
            if datasets is None:
                raise ValueError('Unable to decode data from {}. Charsets: utf8, {}'.format(url, charsets))
        

        # The first dataset should be for the data.json file itself. Check that
        # it is, and if so rewrite the dataset's title because Socrata exports
        # these items all with the same generic name that is confusing when
        # harvesting a bunch from different sources. It should have an accessURL
        # but Socrata fills the URL of these in under webService.
        if isinstance(datasets, list) and len(datasets) > 0 and (datasets[0].get("accessURL") == harvest_job.source.url
            or datasets[0].get("webService") == harvest_job.source.url) and \
            datasets[0].get("title") == "Project Open Data, /data.json file":
            datasets[0]["title"] = "%s Project Open Data data.json File" % harvest_job.source.title

        catalog_values = None
        if isinstance(datasets, dict):
            # this is a catalog, not dataset array as in schema 1.0.
            catalog_values = datasets.copy()
            datasets = catalog_values.pop("dataset", [])

        log.info('Catalog Loaded from URL: {}: {} datasets found'.format(url, len(datasets)))
        return (datasets, catalog_values)
        
    def set_dataset_info(self, pkg, dataset, dataset_defaults, schema_version):
        parse_datajson_entry(dataset, pkg, dataset_defaults, schema_version)
  
        
# helper function to remove BOM
def lstrip_bom(str_):
    from codecs import BOM_UTF8
    bom = BOM_UTF8
    if str_.startswith(bom):
        return str_[len(bom):], True
    else:
        return str_, False
