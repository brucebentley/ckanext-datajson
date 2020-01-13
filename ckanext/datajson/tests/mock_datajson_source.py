from __future__ import print_function

import os
import json
import re
import copy
import urllib
import ssl

from urllib2 import URLError
import SimpleHTTPServer
import SocketServer
from threading import Thread
import logging
log = logging.getLogger(__name__)

PORT = 8998


class MockDataJSONHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

    counter = {}

    def do_GET(self):

        if self.path not in self.counter.keys():
            self.counter[self.path] = 0
        self.counter[self.path] += 1
        log.info('GET mock at path {} ({})'.format(self.path, self.counter[self.path]))

        # test name is the first bit of the URL and makes CKAN behave
        # differently in some way.
        # Its value is recorded and then removed from the path
        self.test_name = None
        self.sample_datajson_file = None
        self.samples_path = 'ckanext/datajson/tests/datajson-samples'
        if self.path == '/arm':
            self.sample_datajson_file = 'arm.data.json'
            self.test_name = 'arm'
        elif self.path == '/usda':
            self.sample_datajson_file = 'usda.gov.data.json'
            self.test_name = 'usda'
        elif self.path == '/ed':
            self.sample_datajson_file = 'www2.ed.gov.data.json'
            self.test_name = 'ed'
        elif self.path == '/defense':
            self.sample_datajson_file = 'www.defense.gov.data.json'
            self.test_name = 'defense'
        elif self.path == '/charset':
            self.sample_datajson_file = 'charset-problems.json'
            self.test_name = 'charset'
        elif self.path == '/404':
            self.test_name = 'e404'
            self.respond('Not found', status=404)
        elif self.path == '/500':
            self.test_name = 'e500'
            self.respond('Error', status=500)
        elif self.path == '/ssl-certificate-error':
            log.info('HEADERS: {}'.format(self.headers))
            # TODO learn how to detect context at this http request
            # by now we raise error first time and a godd response the second time
            context = ssl._create_unverified_context if self.counter[self.path] > 1 else None    
            if context == ssl._create_unverified_context:
                self.sample_datajson_file = 'www2.ed.gov.data.json'
                self.test_name = 'ed'
            else:
                raise URLError('certificate verify failed')
        
        if self.sample_datajson_file is not None:
            log.info('return json file {}'.format(self.sample_datajson_file))
            self.respond_json_sample_file(file_path=self.sample_datajson_file)

        if self.test_name is None:
            self.respond('Mock DataJSON doesnt recognize that call', status=400)

    def respond_json(self, content_dict, status=200):
        return self.respond(json.dumps(content_dict), status=status,
                            content_type='application/json')
    
    def respond_json_sample_file(self, file_path, status=200):
        pt = os.path.join(self.samples_path, file_path)
        data = open(pt, 'r')
        content = data.read()
        log.info('mock respond {}'.format(content[:90]))
        return self.respond(content=content, status=status,
                            content_type='application/json')

    def respond(self, content, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(content)
        self.wfile.close()


def serve(port=PORT):
    '''Runs a CKAN-alike app (over HTTP) that is used for harvesting tests'''

    class TestServer(SocketServer.TCPServer):
        allow_reuse_address = True

    httpd = TestServer(("", PORT), MockDataJSONHandler)

    info = 'Serving test HTTP server at port {}'.format(PORT)
    print(info)
    log.info(info)

    httpd_thread = Thread(target=httpd.serve_forever)
    httpd_thread.setDaemon(True)
    httpd_thread.start()
