"""
Tests for valid and invalid TLS handhshakes, various violations in
handshake messages.
"""
from framework import tester
from framework.x509 import CertGenerator
from helpers import remote, tf_cfg
from handshake import *
from fuzzer import tls_record_fuzzer

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2019 Tempesta Technologies, Inc.'
__license__ = 'GPL2'


class TlsHandshakeTest(tester.TempestaTest):

    WARN = "Warning: Unrecognized TLS receive return code"

    backends = [
        {
            'id' : '0',
            'type' : 'deproxy',
            'port' : '8000',
            'response' : 'static',
            'response_content' :
                'HTTP/1.1 200 OK\r\n'
                'Content-Length: 0\r\n'
                'Connection: keep-alive\r\n\r\n'
        }
    ]

    tempesta = {
        'config' : """
            cache 0;
            listen 443 proto=https;

            tls_certificate ${general_workdir}/tempesta.crt;
            tls_certificate_key ${general_workdir}/tempesta.key;

            srv_group srv_grp1 {
                server ${server_ip}:8000;
            }
            vhost tempesta-tech.com {
                proxy_pass srv_grp1;
                # TODO tls_certificate ${general_workdir}/tempesta.crt;
                # TODO tls_certificate_key ${general_workdir}/tempesta.key;
            }
            http_chain {
                host == "tempesta-tech.com" -> tempesta-tech.com;
                -> block;
            }
        """
    }

    def start_all(self):
        deproxy_srv = self.get_server('0')
        deproxy_srv.start()
        self.start_tempesta()
        self.assertTrue(deproxy_srv.wait_for_connections(timeout=1),
                        "Cannot start Tempesta")

    def test_tls12_synthetic(self):
        self.start_all()
        res = TlsHandshake(addr='127.0.0.1', port=443).do_12()
        self.assertTrue(res, "Wrong handshake result: %s" % res)

    def test_many_ciphers(self):
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        hs12.ciphers = [i for i in xrange(2000)] # TTLS_HS_CS_MAX_SZ = 984
        # Test compressions as well - they're just ignored anyway.
        hs12.compressions = [i for i in xrange(15)]
        self.assertTrue(hs12.do_12(), "Extra ciphers aren't ignored")

    def test_long_sni(self):
        """ Also tests receiving of TLS alert. """
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        hs12.sni = ["a" * 100 for i in xrange(10)]
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "No warning about bad ClientHello")

    def test_empty_sni_default(self):
        """
        We must process requests from SNI anaware clients in default
        configuration without tls_fallback_default.
        """
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        hs12.sni = []
        self.assertTrue(hs12.do_12(), "Empty SNI isn't accepted by default")

    def test_bad_sni(self):
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        hs12.sni = ["bad.server.name"]
        hs12.host = "tempesta-tech.com"
        res = hs12.do_12()
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "Bad SNI isn't rejected")

    def test_bad_sign_algs(self):
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        # Generate bad extension mismatching length and actual data.
        hs12.sign_algs = [tls.TLSExtension() /
                          tls.TLSExtSignatureAlgorithms(
                              algs=[0x0201, 0x0401, 0x0501, 0x0601, 0x0403],
                              length=11)]
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "No warning about bad ClientHello")

    def test_bad_elliptic_curves(self):
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        # Generate bit longer data than Tempesta accepts (TTLS_ECP_DP_MAX = 12).
        hs12.elliptic_curves = [tls.TLSExtension() /
                                tls.TLSExtEllipticCurves(
                                    named_group_list=[i for i in xrange(13)],
                                    length=26)]
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "No warning about bad ClientHello")

    def test_bad_renegotiation_info(self):
        self.start_all()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        # Generate bit longer data than Tempesta accepts (TTLS_ECP_DP_MAX = 12).
        hs12.renegotiation_info = [tls.TLSExtension() /
                                   tls.TLSExtRenegotiationInfo(data="foo")]
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "No warning about non-empty RenegotiationInfo")

    def test_alert(self):
        self.start_all()
        tls_conn = TlsHandshake(addr='127.0.0.1', port=443)
        with tls_conn.socket_ctx():
            self.assertTrue(tls_conn._do_12_hs(), "Can not connect to Tempesta")
            tls_conn.send_12_alert(tls.TLSAlertLevel.WARNING,
                                   tls.TLSAlertDescription.UNEXPECTED_MESSAGE)
            res = tls_conn._do_12_req()
            self.assertTrue(res, "Wrong request 1 result: %s" % res)
            # Unknown alerts are just ignored.
            tls_conn.send_12_alert(22, 77)
            res = tls_conn._do_12_req()
            self.assertTrue(res, "Wrong request 2 result: %s" % res)
            tls_conn.send_12_alert(tls.TLSAlertLevel.FATAL,
                                   tls.TLSAlertDescription.UNEXPECTED_MESSAGE)
            res = tls_conn._do_12_req()
            self.assertFalse(res, "Request processed on closed socket")

    def test_fuzzing(self):
        """
        Inject bad (fuzzed) TLS records at different places on TLS handshake.
        Also try different message variants for each place.
        """
        self.start_all()
        fuzzer = tls_record_fuzzer()
        for _ in xrange(10):
            # Only 4 places to inject a pakcet in simple handshake and
            # request test.
            for inject_rec in xrange(4):
                tls_conn = TlsHandshake(addr='127.0.0.1', port=443)
                tls_conn.inject = inject_rec
                try:
                    res = tls_conn.do_12(fuzzer)
                    self.assertFalse(res, "Got request on fuzzed connection")
                except socket.error:
                    pass # broken pipe is expected

    def test_old_handshakes(self):
        self.start_all()
        res = TlsHandshakeStandard(addr='127.0.0.1', port=443).do_old()
        self.assertTrue(res, "Wrong old handshake result: %s" % res)


class TlsVhostHandshakeTest(tester.TempestaTest):
    backends = [
        {
            'id' : 'be1',
            'type' : 'deproxy',
            'port' : '8000',
            'response' : 'static',
            'response_content' :
                'HTTP/1.1 200 OK\r\n'
                'Content-Length: 3\r\n'
                'Connection: keep-alive\r\n'
                '\r\n'
                'be1'
        },
        {
            'id' : 'be2',
            'type' : 'deproxy',
            'port' : '8001',
            'response' : 'static',
            'response_content' :
                'HTTP/1.1 200 OK\r\n'
                'Content-Length: 3\r\n'
                'Connection: keep-alive\r\n'
                '\r\n'
                'be2'
        }
    ]

    tempesta = {
        'config' : """
            cache 0;
            listen 443 proto=https;

            srv_group be1 { server ${server_ip}:8000; }
            srv_group be2 { server ${server_ip}:8001; }

            tls_fallback_default off;

            vhost vhost1.net {
                proxy_pass be1;
                tls_certificate ${general_workdir}/vhost1.crt;
                tls_certificate_key ${general_workdir}/vhost1.key;
            }

            vhost vhost2.net {
                proxy_pass be2;
                tls_certificate ${general_workdir}/vhost2.crt;
                tls_certificate_key ${general_workdir}/vhost2.key;
            }

            http_chain {
                host == "vhost1.net" -> vhost1.net;
                host == "vhost2.net" -> vhost2.net;
                -> block;
            }
        """,
        'custom_cert': True
    }

    @staticmethod
    def gen_cert(host_name):
        workdir = tf_cfg.cfg.get('General', 'workdir')
        cert_path = "%s/%s.crt" % (workdir, host_name)
        key_path = "%s/%s.key" % (workdir, host_name)
        cgen = CertGenerator(cert_path, key_path)
        cgen.CN = host_name + u'.net'
        cgen.generate()
        remote.tempesta.copy_file(cert_path, cgen.serialize_cert())
        remote.tempesta.copy_file(key_path, cgen.serialize_priv_key())

    def test_vhost_sni(self):
        self.gen_cert("vhost1")
        self.gen_cert("vhost2")

        self.start_all_servers()
        self.start_tempesta()

        vhs = TlsHandshake(addr='127.0.0.1', port=443)
        vhs.sni = ["vhost1.net"]
        res = vhs.do_12()
        self.assertTrue(res, "Bad handshake with vhost1: %s" % res)
        self.assertTrue(vhs.http_resp.endswith("be1"),
                        "Bad response from vhost1: [%s]" % vhs.http_resp)
        self.assertTrue(x509_check_cn(vhs.cert, "vhost1.net"),
                        "Wrong certificate received for vhost1")

        vhs = TlsHandshake(addr='127.0.0.1', port=443)
        vhs.sni = ["vhost2.net"]
        res = vhs.do_12()
        self.assertTrue(res, "Bad handshake with vhost2: %s" % res)
        self.assertTrue(vhs.http_resp.endswith("be2"),
                        "Bad response from vhost2: [%s]" % vhs.http_resp)
        self.assertTrue(x509_check_cn(vhs.cert, "vhost2.net"),
                        "Wrong certificate received for vhost2")

    def test_empty_sni_default(self):
        """
        We must process requests from SNI anaware clients in default
        configuration without tls_fallback_default.
        """
        self.gen_cert("vhost1")
        self.gen_cert("vhost2")
        self.start_all_servers()
        self.start_tempesta()
        hs12 = TlsHandshake(addr='127.0.0.1', port=443)
        hs12.sni = []
        warns = dmesg.count_warnings(self.WARN)
        with self.assertRaises(tls.TLSProtocolError):
            hs12.do_12()
        self.assertEqual(dmesg.count_warnings(self.WARN), warns + 1,
                         "No warning about bad SNI")


class TlsCertReconfig(tester.TempestaTest):
    """
    Strictly speaking this is not a TLS handshake test, it's certificates
    test. However, we need low level access to exchanged certificate, so
    ScaPy interface is required and the test went here.
    """
    backends = [
        {
            'id' : '0',
            'type' : 'deproxy',
            'port' : '8000',
            'response' : 'static',
            'response_content' :
                'HTTP/1.1 200 OK\r\n'
                'Content-Length: 0\r\n'
                'Connection: keep-alive\r\n\r\n'
        },
    ]

    tempesta = {
        'config' : """
            cache 0;
            listen 443 proto=https;

            tls_certificate ${general_workdir}/tempesta.crt;
            tls_certificate_key ${general_workdir}/tempesta.key;
            tls_fallback_default allow_fallback;

            srv_group srv_grp1 {
                server ${server_ip}:8000;
            }
            vhost tempesta-tech.com {
                proxy_pass srv_grp1;
            }
            http_chain {
                host == "tempesta-tech.com" -> tempesta-tech.com;
                -> block;
            }
        """,
    }

    @staticmethod
    def gen_cert():
        workdir = tf_cfg.cfg.get('General', 'workdir')
        cert_path = "%s/tempesta.crt" % workdir
        key_path = "%s/tempesta.key" % workdir
        cgen = CertGenerator(cert_path, key_path)
        cgen.O = u'New Issuer'
        cgen.generate()
        remote.tempesta.copy_file(cert_path, cgen.serialize_cert())
        remote.tempesta.copy_file(key_path, cgen.serialize_priv_key())

    def test(self):
        deproxy_srv = self.get_server('0')
        deproxy_srv.start()
        self.start_tempesta()
        self.assertTrue(deproxy_srv.wait_for_connections(timeout=1),
                        "Cannot start Tempesta")

        vhs = TlsHandshake(addr='127.0.0.1', port=443)
        res = vhs.do_12()
        self.assertTrue(res, "Bad handshake: %s" % res)
        res = x509_check_issuer(vhs.cert, "Tempesta Technologies Inc.")
        self.assertTrue(res, "Wrong certificate configured")

        # Reload Tempesta with new certificate.
        self.gen_cert()
        self.get_tempesta().reload()

        vhs = TlsHandshake(addr='127.0.0.1', port=443)
        res = vhs.do_12()
        self.assertTrue(res, "Bad second handshake: %s" % res)
        res = x509_check_issuer(vhs.cert, "New Issuer")
        self.assertTrue(res, "Wrong certificate reloaded")
