from framework import tester
from helpers import tf_cfg, deproxy
import inspect;

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2021 Tempesta Technologies, Inc.'
__license__ = 'GPL2'

class MalformedRqLineTest(tester.TempestaTest):
    # There are diagnostic tests for incorect processing of HTTP Method in http_parser.c (issue #1536)
    # These tests are for diagnostic purpose. They always end with positive of false-positive result.
    # Important information for diagnostics is printed onto stdout during execution.
    #
    backends = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'port' : '8000',
            'keep_original_data' : True,
            'response' : 'static',
            'response_content' :
"""HTTP/1.1 200 OK
Content-Length: 0
Connection: keep-alive

"""
        },
    ]

    tempesta = {
        'config' : """
cache 0;
server ${general_ip}:8000;

""",
    }

    clients = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '80'
        },
    ]

    def common_check(self, request, expect_status=200, expect='', chunked=False):
        # Set expect to expected proxied request,
        # to empty string to skip request check and
        # to None to check that request is missing
        callername = inspect.stack()[1][3];
        print("=====" + callername + "=====")
        pipeline = callername.find("pipeline") >= 0
        if pipeline:
            ovr = 2
        else:
            ovr = 1
        deproxy_srv = self.get_server('deproxy')
        deproxy_srv.start()
        self.start_tempesta()
        deproxy_cl = self.get_client('deproxy')
        if chunked:
            deproxy_cl.segment_size = 1
        deproxy_cl.start()
        self.deproxy_manager.start()
        self.assertTrue(deproxy_srv.wait_for_connections(timeout=1))
        print("Sending request----")
        print(request)
        print("-------------------")
        deproxy_cl.make_request(request)
        has_resp = deproxy_cl.wait_for_response(timeout=5)
        has_backend_request = not deproxy_srv.last_request is None;
        if has_backend_request:
            print("Request forwarded to backend----")
            print(deproxy_srv.last_request.original_data)
            print("--------------------------------")
            if expect is None:
                print("*** Expected NONE")
            else:
                print("*** Expected--------------")
                print(expect)
                print("--------------------------")
        else:
            print("Request was not forwarded to backend")
            if not expect is None:
                print("*** Expected--------------")
                print(expect)
                print("--------------------------")
        if not has_resp:
            print("*** Response not received")
        else:
            status = int(deproxy_cl.last_response.status)
            print("Response status:" + str(status))
            if status != expect_status:
                print("*** Expected: " + str(expect_status))

    def test_00_disclaimer(self):
        print("************************************************************")
        print("* This is a diagnistic tests rather than evaluation tests  *")
        print("* Trust messages on screen rather than overal test results *")
        print("************************************************************")

    def test_01_double_lf(self):
    	# Test double LF before request
    	# Request should be rejected by the proxy
    	#
        request = \
                  '\n' \
                  '\n' \
                  'GET / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect)

    def test_02_double_lf_pipeline(self):
    	# Test double LF before 2nd request in a pipeline
    	# The 1st request should be sent to backed
    	# The 2nd request should be rejected by the proxy
    	#
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  '\n' \
                  '\n' \
                  'GET /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect)

    def test_03_malformed_get(self):
        request = \
                  '\tGET / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect)

    def test_04_malformed_get_pipeline(self):
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  '\tGET /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect)

    def test_05_malformed_post(self):
        request = \
                  'PO\tT / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect)

    def test_06_malformed_post_pipeline(self):
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  'POS\tT /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect)

    ##### Heavy chunked versions of the tests

    def test_07_double_lf_hch(self):
    	# Test double LF before request
    	# Request should be rejected by the proxy
    	#
        # This is a heavy chunked version of the test
        #
        request = \
                  '\n' \
                  '\n' \
                  'GET / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect, True)

    def test_08_double_lf_pipeline_hch(self):
    	# Test double LF before 2nd request in a pipeline
    	# The 1st request should be sent to backed
    	# The 2nd request should be rejected by the proxy
    	#
        # This is a heavy chunked version of the test
        #
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  '\n' \
                  '\n' \
                  'GET /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect, True)

    def test_09_malformed_get_hch(self):
        request = \
                  '\tGET / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect, True)

    def test_10_malformed_get_pipeline_hch(self):
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  '\tGET /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect, True)

    def test_11_malformed_post_hch(self):
        request = \
                  'PO\tT / HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = None
        self.common_check(request, 400, expect, True)

    def test_12_malformed_post_pipeline_hch(self):
        request = \
                  'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n' \
                  'POS\tT /bbb HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        expect = 'GET /aaa HTTP/1.1\r\n' \
                  'Host: localhost\r\n' \
                  '\r\n'
        self.common_check(request, 400, expect, True)

