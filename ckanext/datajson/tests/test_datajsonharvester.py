import copy
from urllib.error import URLError
from nose.tools import assert_equal, assert_raises, assert_in
from mock import patch, MagicMock, Mock
from requests.exceptions import HTTPError, RequestException

try:
    from ckan.tests.helpers import reset_db, call_action
    from ckan.tests.factories import Organization, Group
except ImportError:
    from ckan.new_tests.helpers import reset_db, call_action
    from ckan.new_tests.factories import Organization, Group
from ckan import model
from ckan.plugins import toolkit
from ckan.lib.munge import munge_title_to_name
# from ckanext.harvest.tests.factories import (HarvestSourceObj, HarvestJobObj,
#                                              HarvestObjectObj)
from factories import (HarvestSourceObj,
                       HarvestJobObj,
                       HarvestObjectObj)

import ckanext.harvest.model as harvest_model
from ckanext.harvest.harvesters.base import HarvesterBase
from ckanext.datajson.harvester_datajson import DataJsonHarvester
import logging
log = logging.getLogger(__name__)

import mock_datajson_source


class TestDataJSONHarvester(object):
    
    @classmethod
    def setup_class(cls):
        log.info('Starting mock http server')
        mock_datajson_source.serve()

    @classmethod
    def setup(cls):
        # Start data json sources server we can test harvesting against it
        reset_db()
        harvest_model.setup()

    def run_source(self, url, limit=1):
        """ harvest a source 
        
        Params
        url: URL of the datajson harvest source
        limit: number of datasets to harvest
        """
        
        source = HarvestSourceObj(url=url)
        job = HarvestJobObj(source=source)

        harvester = DataJsonHarvester()

        # gather stage
        log.info('GATHERING %s', url)
        obj_ids = harvester.gather_stage(job)
        log.info('job.gather_errors=%s', job.gather_errors)

        if len(job.gather_errors) > 0:
            real_errors = []
            for error in job.gather_errors:
                # ignore some not important errors
                if 'Duplicate entry ignored for identifier' in str(error):
                    continue
                else:
                    real_errors.append(error)
            if len(real_errors) > 0:
                raise ValueError('Errors Gathering: {}'.format(real_errors))

        log.info('obj_ids=%s', obj_ids)
        if len(obj_ids) == 0:
            # nothing to see
            return

        c = 0
        for obj_id in obj_ids:
            if c > limit:
                break
            harvest_object = harvest_model.HarvestObject.get(obj_id)
            log.info('ho guid=%s', harvest_object.guid)
            log.info('ho content=%s', harvest_object.content)

            # fetch stage
            log.info('FETCHING %s', url)
            result = harvester.fetch_stage(harvest_object)

            log.info('ho errors=%s', harvest_object.errors)
            log.info('result 1=%s', result)

            if len(harvest_object.errors) > 0:
                raise ValueError('Errors Fetching: {}'.format(harvest_object.errors))

            # fetch stage
            log.info('IMPORTING %s', url)
            result = harvester.import_stage(harvest_object)

            log.info('ho errors 2=%s', harvest_object.errors)

            if len(harvest_object.errors) > 0:
                raise ValueError('Errors Importing: {}'.format(harvest_object.errors))

            log.info('result 2=%s', result)
            log.info('ho pkg id=%s', harvest_object.package_id)
            dataset = model.Package.get(harvest_object.package_id)
            log.info('dataset name=%s', dataset.name)

            yield harvest_object, result, dataset
            c += 1

    def test_datason_arm(self):
        url = 'http://127.0.0.1:%s/arm' % mock_datajson_source.PORT
        
        # just the firs one
        for harvest_object, result, dataset in self.run_source(url=url):
            expected_title = "NCEP GFS: vertical profiles of met quantities at standard pressures, at Barrow"
            assert_equal(dataset.title, expected_title)
            tags = [tag.name for tag in dataset.get_tags()]
            assert_in(munge_title_to_name("ORNL"), tags)
            assert_equal(len(dataset.resources), 1)
            break
    
    def test_datason_usda(self):
        url = 'http://127.0.0.1:%s/usda' % mock_datajson_source.PORT

        # just the firs one
        for harvest_object, result, dataset in self.run_source(url=url, limit=20):
            expected_title = "Department of Agriculture Congressional Logs for Fiscal Year 2014"
            assert_equal(dataset.title, expected_title)
            tags = [tag.name for tag in dataset.get_tags()]
            assert_in(munge_title_to_name("Congressional Logs"), tags)
            assert_equal(len(dataset.resources), 1)
            break
    
    def test_datason_404(self):
        url = 'http://127.0.0.1:%s/404' % mock_datajson_source.PORT
        with assert_raises(URLError) as harvest_context:
            for harvest_object, result, dataset in self.run_source(url=url):
                pass
        
    def test_datason_500(self):
        url = 'http://127.0.0.1:%s/500' % mock_datajson_source.PORT
        with assert_raises(URLError) as harvest_context:
            for harvest_object, result, dataset in self.run_source(url=url):
                pass
        
    def test_datason_ed(self):
        url = 'http://127.0.0.1:%s/ed' % mock_datajson_source.PORT
        
        for harvest_object, result, dataset in self.run_source(url=url, limit=20):
            log.info('Dataset: {}'.format(dataset))
            tags = [tag.name for tag in dataset.get_tags()]
            log.info('Tags: {}'.format(tags))
            log.info('Result: {}'.format(result))
            
            if dataset.title == 'National Reporting System for Adult Education, 2007-08':
                log.info('Found: Academic Libraries Survey, 2010')
                assert 'adult-literacy' in tags
                assert 'annual-performance-report' in tags
                assert 'financial-reports' in tags
                assert 'ovaes-gpra-goals-for-adult-education' in tags
                # "keyword": [ "Annual Performance Report", "Financial Reports", "OVAE's GPRA goals for adult education", "Adult literacy"],
                expected_tag_string = 'annual-performance-report, financial-reports, ovaes-gpra-goals-for-adult-education, adult-literacy'
                assert dataset.tag_string == expected_tag_string

            if dataset.title == 'Academic Libraries Survey, 2010':
                log.info('Found: Academic Libraries Survey, 2010')
                # "keyword": [ "Research libraries", "Research librarians", "University libraries", "College libraries", "University librarians", "College librarians" ],
                expected_tag_string = 'research-libraries, research-librarians, university-libraries, college-libraries, university-librarians, college-librarians'
                assert dataset.tag_string == expected_tag_string

    def test_ssl_fail(self):
        # not fail if SSL error
        url = 'http://127.0.0.1:%s/ssl-certificate-error' % mock_datajson_source.PORT
        
        for harvest_object, result, dataset in self.run_source(url=url, limit=20):
            log.info('Dataset: {}'.format(dataset))
            tags = [tag.name for tag in dataset.get_tags()]
            log.info('Tags: {}'.format(tags))
            log.info('Result: {}'.format(result))
            
            if dataset.title == 'National Reporting System for Adult Education, 2007-08':
                # "keyword": [ "Annual Performance Report", "Financial Reports", "OVAE's GPRA goals for adult education", "Adult literacy"],
                assert 'adult-literacy' in tags
                assert 'annual-performance-report' in tags
                assert 'financial-reports' in tags
                assert 'ovaes-gpra-goals-for-adult-education' in tags
    
    def test_datason_defense_bad_charset(self):
        url = 'http://127.0.0.1:%s/defense' % mock_datajson_source.PORT
        log.info('Testing defense.gov/data.json')
        for harvest_object, result, dataset in self.run_source(url=url, limit=20):
            log.info('Dataset: {}'.format(dataset))
            tags = [tag.name for tag in dataset.get_tags()]
            log.info('Tags: {}'.format(tags))
            log.info('Result: {}'.format(result))
    
    def test_utf8(self):
        url = 'http://127.0.0.1:%s/charset' % mock_datajson_source.PORT
        log.info('Testing char utf8')
        for harvest_object, result, dataset in self.run_source(url=url, limit=20):
            log.info('Dataset: {}'.format(dataset))
            tags = [tag.name for tag in dataset.get_tags()]
            log.info('Tags: {}'.format(tags))
            log.info('Result: {}'.format(result))
