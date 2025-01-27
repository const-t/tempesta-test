"""
Tests for data integrity transferred via Tempesta TLS.
"""
from contextlib import contextmanager
import hashlib

from helpers import tf_cfg, analyzer, remote, sysnet
from helpers.error import Error
from framework import tester

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2019 Tempesta Technologies, Inc.'
__license__ = 'GPL2'


class TlsIntegrityTester(tester.TempestaTest):

    clients = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
    ]

    backends = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'port' : '8000',
            'response' : 'static',
            'response_content' : 'dummy',
        }
    ]

    def start_all(self):
        deproxy_srv = self.get_server('deproxy')
        deproxy_srv.start()
        self.start_tempesta()
        self.start_all_clients()
        self.deproxy_manager.start()
        self.assertTrue(deproxy_srv.wait_for_connections(timeout=1),
                        "No connection from Tempesta to backends")

    @staticmethod
    def make_resp(body):
        return  'HTTP/1.1 200 OK\r\n' \
                'Content-Length: ' + str(len(body)) + '\r\n' \
                'Connection: keep-alive\r\n\r\n' + body

    @staticmethod
    def make_req(req_len):
        return  'POST /' + str(req_len) + ' HTTP/1.1\r\n' \
                'Host: tempesta-tech.com\r\n' \
                'Content-Length: ' + str(req_len) + '\r\n' \
                '\r\n' + ('x' * req_len)

    def common_check(self, req_len, resp_len):
        resp_body = 'x' * resp_len
        hash1 = hashlib.md5(resp_body.encode()).digest()

        self.get_server('deproxy').set_response(self.make_resp(resp_body))

        for clnt in self.clients:
            client = self.get_client(clnt['id'])
            client.make_request(self.make_req(req_len))
            res = client.wait_for_response(timeout=5)
            self.assertTrue(res, "Cannot process request (len=%d) or response" \
                                 " (len=%d)" % (req_len, resp_len))
            resp = client.responses[-1].body
            tf_cfg.dbg(4, '\tDeproxy response (len=%d): %s...'
                       % (len(resp), resp[:100]))
            hash2 = hashlib.md5(resp.encode()).digest()
            self.assertTrue(hash1 == hash2, "Bad response checksum")

    @contextmanager
    def mtu_ctx(self, node, dev, mtu):
        try:
            yield
        finally:
            sysnet.change_mtu(node, dev, mtu)

    def tcp_flow_check(self, resp_len):
        """ Check how Tempesta generates TCP segments for TLS records. """
        # Run the sniffer first to let it start in separate thread.
        sniffer = analyzer.AnalyzerTCPSegmentation(remote.tempesta, 'Tempesta',
                                                   timeout=3, ports=(443, 8000))
        sniffer.start()

        resp_body = 'x' * resp_len
        self.get_server('deproxy').set_response(self.make_resp(resp_body))

        client = self.get_client(self.clients[0]['id'])

        try:
            # Deproxy client and server run on the same node and network
            # interface, so, regardless where the Tempesta node resides, we can
            # change MTU on the local interface only to get the same MTU for
            # both the client and server connections.
            dev = sysnet.route_dst_ip(remote.client, client.addr[0])
            prev_mtu = sysnet.change_mtu(remote.client, dev, 1500)
        except Error as err:
            self.fail(err)

        with self.mtu_ctx(remote.client, dev, prev_mtu):
            client.make_request(self.make_req(1))
            res = client.wait_for_response(timeout=1)
            self.assertTrue(res, "Cannot process response (len=%d)" % resp_len)
            sniffer.stop()
            self.assertTrue(sniffer.check_results(), "Not optimal TCP flow")


class Proxy(TlsIntegrityTester):

    tempesta = {
        'config' : """
            cache 0;
            listen 443 proto=https;
            tls_certificate ${general_workdir}/tempesta.crt;
            tls_certificate_key ${general_workdir}/tempesta.key;
            server ${server_ip}:8000;
        """
    }

    def test_various_req_resp_sizes(self):
        self.start_all()
        self.common_check(1, 1)
        self.common_check(19, 19)
        self.common_check(567, 567)
        self.common_check(1755, 1755)
        self.common_check(4096, 4096)
        self.common_check(16380, 16380)
        self.common_check(65536, 65536)
        self.common_check(1000000, 1000000)

    def test_tcp_segs(self):
        self.start_all()
        self.tcp_flow_check(8192)


class Cache(TlsIntegrityTester):

    clients = [
        {
            'id' : 'clnt1',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
        {
            'id' : 'clnt2',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
        {
            'id' : 'clnt3',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
        {
            'id' : 'clnt4',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
    ]

    tempesta = {
        'config' : """
            cache 1;
            cache_fulfill * *;
            cache_methods POST;
            listen 443 proto=https;
            tls_certificate ${general_workdir}/tempesta.crt;
            tls_certificate_key ${general_workdir}/tempesta.key;
            server ${server_ip}:8000;
        """
    }

    def test_various_req_resp_sizes(self):
        self.start_all()
        self.common_check(1, 1)
        self.common_check(19, 19)
        self.common_check(567, 567)
        self.common_check(1755, 1755)
        self.common_check(4096, 4096)
        self.common_check(16380, 16380)
        self.common_check(65536, 65536)
        self.common_check(1000000, 1000000)

class CloseConnection(tester.TempestaTest):

    clients = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'addr' : "${tempesta_ip}",
            'port' : '443',
            'ssl' : True,
        },
    ]

    backends = [
        {
            'id' : 'deproxy',
            'type' : 'deproxy',
            'port' : '8000',
            'response' : 'static',
            'response_content' : 'dummy',
        }
    ]

    tempesta = {
        'config' : """
            cache 0;
            listen 443 proto=https;
            tls_certificate ${general_workdir}/tempesta.crt;
            tls_certificate_key ${general_workdir}/tempesta.key;
            server ${server_ip}:8000;
        """
    }

    def start_all(self):
        deproxy_srv = self.get_server('deproxy')
        deproxy_srv.start()
        self.start_tempesta()
        self.start_all_clients()
        self.deproxy_manager.start()
        self.assertTrue(deproxy_srv.wait_for_connections(timeout=1),
                        "No connection from Tempesta to backends")

    @staticmethod
    def make_resp(body):
        return  'HTTP/1.1 200 OK\r\n' \
                'Content-Length: ' + str(len(body)) + '\r\n' \
                'Connection: keep-alive\r\n\r\n' + body

    @staticmethod
    def make_req(req_len):
        return  'GET /' + str(req_len) + ' HTTP/1.1\r\n' \
                'Host: tempesta-tech.com\r\n' \
                'Connection: close\r\n\r\n'

    def common_check(self, req_len, resp_len):
        resp_body = 'x' * resp_len
        hash1 = hashlib.md5(resp_body.encode()).digest()

        self.get_server('deproxy').set_response(self.make_resp(resp_body))

        client = self.get_client(self.clients[0]['id'])
        client.make_request(self.make_req(req_len))
        res = client.wait_for_response(timeout=5)
        self.assertTrue(res, "Cannot process request (len=%d) or response" \
                             " (len=%d)" % (req_len, resp_len))
        resp = client.responses[-1].body
        tf_cfg.dbg(4, '\tDeproxy response (len=%d): %s...'
                   % (len(resp), resp[:100]))
        hash2 = hashlib.md5(resp.encode()).digest()
        self.assertTrue(hash1 == hash2, "Bad response checksum")

    def test1(self):
        self.start_all()
        self.common_check(1, 1)

    def test2(self):
        self.start_all()
        self.common_check(19, 19)

    def test3(self):
        self.start_all()
        self.common_check(567, 567)

    def test4(self):
        self.start_all()
        self.common_check(1755, 1755)

    def test5(self):
        self.start_all()
        self.common_check(4096, 4096)

    def test6(self):
        self.start_all()
        self.common_check(16380, 16380)

    def test7(self):
        self.start_all()
        self.common_check(65536, 65536)

    def test8(self):
        self.start_all()
        self.common_check(1000000, 1000000)
