# Basic TLS 1.2 handshake test.
#
# Also usable as a TLS traffic generator to debug early TLS server
# implementation. This tool emphasises flexibility in generation of TLS traffic,
# not performance.
#
# ScaPy is still not fully compatible with Python3, but I still use __future__
# module for easier migration to Python3.
# https://github.com/tintinweb/scapy-ssl_tls/issues/39
#
# TLS 1.2 is specified in RFC 5246. See also these useful references:
#   - https://wiki.osdev.org/SSL/TLS
#   - https://wiki.osdev.org/TLS_Handshake
#   - https://wiki.osdev.org/TLS_Encryption

from __future__ import print_function
from contextlib import contextmanager
import random
import socket
import ssl # OpenSSL based API
import struct
import scapy_ssl_tls.ssl_tls as tls

from helpers import dmesg

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2018-2019 Tempesta Technologies, Inc.'
__license__ = 'GPL2'


GOOD_RESP = "HTTP/1.1 200"
TLS_HS_WARN = "Warning: Unrecognized TLS receive return code"


def x509_check_cn(cert, cn):
    """
    Decode x509 certificate in BER and check CommonName (CN, OID '2.5.4.3')
    against passed @cn value. ScaPy-TLS can not parse ASN1 from certificates
    generated by the cryptography library, so we can not use full string
    matching and have to use substring matching instead.
    """
    for f in cert.fields['subject']:
        if f.oid.val == '2.5.4.3':
            return str(f.value).endswith(cn)
    raise Exception("Certificate has no CommonName")


def x509_check_issuer(cert, issuer):
    """
    The same as above, but for Issuer OrganizationName (O, OID '2.5.4.10').
    """
    for f in cert.fields['issuer']:
        if f.oid.val == '2.5.4.10':
            return str(f.value).endswith(issuer)
    raise Exception("Certificate has no Issuer OrganizationName")


class TlsHandshake:
    """
    Class for custom TLS handshakes - mainly ScaPy-TLS wrapper.
    Update the fields defined in __init__() to customize a handshake.

    Use higher @rto values to debug/test Tempesta in debug mode.
    Use True for @verbose to see debug output for the handshake.
    """
    def __init__(self, addr='127.0.0.1', port=443, rto=0.5, verbose=False):
        self.addr = addr
        self.port = port
        self.rto = rto
        self.verbose = verbose
        # Service members.
        self.sock = None
        # Additional handshake options.
        self.sni = ['tempesta-tech.com'] # vhost string names.
        self.exts = [] # Extra extensions
        self.sign_algs = []
        self.elliptic_curves = []
        self.ciphers = []
        self.compressions = []
        self.renegotiation_info = []
        self.inject = None
        # HTTP server response (headers and body), if any.
        self.http_resp = None
        # Host request header value, taken from SNI by default.
        self.host = None
        # Server certificate.
        self.cert = None

    @contextmanager
    def socket_ctx(self):
        try:
            yield
        finally:
            self.sock.close()

    def conn_estab(self):
        assert not self.sock, "Connection has already been established"
        self.sock = tls.TLSSocket(socket.socket(), client=True)
        # Set large enough send and receive timeouts which will be used by
        # default.
        self.sock.settimeout(self.rto)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO,
                             struct.pack('ll', 2, self.rto * 1000))
        self.sock.connect((self.addr, self.port))

    def send_recv(self, pkt):
        """
        Mainly a copy&paste from tls_do_round_trip(), but uses custom timeout to
        be able to fully read all data from Tempesta in verbose debugging mode
        (serial console verbose logging may be extremely slow).
        """
        assert self.sock, "Try to read and write on invalid socket"
        resp = tls.TLS()
        try:
            self.sock.sendall(pkt)
            resp = self.sock.recvall(timeout=self.rto)
            if resp.haslayer(tls.TLSAlert):
                alert = resp[tls.TLSAlert]
                if alert.level != tls.TLSAlertLevel.WARNING:
                    level = tls.TLS_ALERT_LEVELS.get(alert.level, "unknown")
                    desc = tls.TLS_ALERT_DESCRIPTIONS.get(alert.description,
                                                          "unknown description")
                    raise tls.TLSProtocolError("%s alert returned by server: %s"
                                               % (level.upper(), desc.upper()),
                                               pkt, resp)
        except socket.error as sock_except:
            raise tls.TLSProtocolError(sock_except, pkt, resp)
        return resp

    @staticmethod
    def static_rnd(begin, end):
        """ A replacement for random.randint() to return constant results. """
        return (begin + end) / 2

    def inject_bad(self, fuzzer):
        """
        Inject a bad record after @self.inject normal records.
        """
        if self.inject is None or not fuzzer:
            return
        if self.inject > 0:
            self.inject -= 1
            return
        self.sock.send(next(fuzzer))

    def extra_extensions(self):
        # Add ServerNameIdentification (SNI) extensiosn by specified vhosts.
        if self.sni:
            sns = [tls.TLSServerName(data=sname) for sname in self.sni]
            self.exts += [tls.TLSExtension() /
                          tls.TLSExtServerNameIndication(server_names=sns)]
        if self.sign_algs:
            self.exts += self.sign_algs
        else:
            self.exts += [tls.TLSExtension() / tls.TLSExtSignatureAlgorithms()]
        if self.elliptic_curves:
            self.exts += self.elliptic_curves
        else:
            self.exts += [tls.TLSExtension() / tls.TLSExtSupportedGroups()]
        if self.renegotiation_info:
            self.exts += self.renegotiation_info
        else:
            self.exts += [tls.TLSExtension() /
                          tls.TLSExtRenegotiationInfo(data="")]
        # We're must be good with standard, but unsupported options.
        self.exts += [
            tls.TLSExtension(type=0x3), # TrustedCA, RFC 6066 6.
            tls.TLSExtension(type=0x5), # StatusRequest, RFC 6066 8.
            tls.TLSExtension(type=0xf0), # Bad extension, just skipped

            tls.TLSExtension() /
            tls.TLSExtALPN(protocol_name_list=[
                tls.TLSALPNProtocol(data="http/1.1"),
                tls.TLSALPNProtocol(data="http/2.0")]),

            tls.TLSExtension() /
            tls.TLSExtMaxFragmentLength(fragment_length=0x01), # 512 bytes

            tls.TLSExtension() /
            tls.TLSExtCertificateURL(certificate_urls=[
                tls.TLSURLAndOptionalHash(url="http://www.tempesta-tech.com")]),

            tls.TLSExtension() /
            tls.TLSExtHeartbeat(
                mode=tls.TLSHeartbeatMode.PEER_NOT_ALLOWED_TO_SEND),

            tls.TLSExtension() /
            tls.TLSExtSessionTicketTLS(data="myticket")
        ]
        return self.exts

    def send_12_alert(self, level, desc):
        self.sock.sendall(tls.TLSRecord(version='TLS_1_2') /
                          tls.TLSAlert(level=level, description=desc))

    def _do_12_hs(self, fuzzer=None):
        """
        Test TLS 1.2 handshake: establish a new TCP connection and send
        predefined TLS handshake records. This test is suitable for debug build
        of Tempesta FW, which replaces random and time functions with
        deterministic data. The test doesn't actually verify any functionality,
        but rather just helps to debug the core handshake functionality.
        """
        try:
            self.conn_estab()
        except socket.error:
            return False

        c_h = tls.TLSClientHello(
            gmt_unix_time=0x22222222,
            random_bytes='\x11' * 28,
            cipher_suites=[
                tls.TLSCipherSuite.ECDHE_ECDSA_WITH_AES_128_GCM_SHA256] +
                self.ciphers,
            compression_methods=[tls.TLSCompressionMethod.NULL] +
                self.compressions,
            # EtM isn't supported - just try to negate an unsupported extension.
            extensions=[
                tls.TLSExtension(type=0x16), # Encrypt-then-MAC
                tls.TLSExtension() / tls.TLSExtECPointsFormat()]
            + self.extra_extensions()
        )
        msg1 = tls.TLSRecord(version='TLS_1_2') / \
               tls.TLSHandshakes(handshakes=[tls.TLSHandshake() / c_h])
        if self.verbose:
            msg1.show()

        # Send ClientHello and read ServerHello, ServerCertificate,
        # ServerKeyExchange, ServerHelloDone.
        self.inject_bad(fuzzer)
        resp = self.send_recv(msg1)
        if not resp.haslayer(tls.TLSCertificate):
            return False
        self.cert = resp[tls.TLSCertificate].data
        assert self.cert, "No cerfificate received"
        if self.verbose:
            resp.show()

        # Check that before encryoptin non-critical alerts are just ignored.
        self.send_12_alert(tls.TLSAlertLevel.WARNING,
                           tls.TLSAlertDescription.RECORD_OVERFLOW)

        # Send ClientKeyExchange, ChangeCipherSpec.
        # get_client_kex_data() -> get_client_ecdh_pubkey() -> make_keypair()
        # use random, so replace it with our mock.
        randint_save = random.randint
        random.randint = self.static_rnd
        cke_h = tls.TLSHandshakes(
            handshakes=[tls.TLSHandshake() /
                        self.sock.tls_ctx.get_client_kex_data()])
        random.randint = randint_save
        msg1 = tls.TLSRecord(version='TLS_1_2') / cke_h
        msg2 = tls.TLSRecord(version='TLS_1_2') / tls.TLSChangeCipherSpec()
        if self.verbose:
            msg1.show()
            msg2.show()

        self.inject_bad(fuzzer)
        self.sock.sendall(tls.TLS.from_records([msg1, msg2]))
        # Now we can calculate the final session checksum, send ClientFinished,
        # and receive ServerFinished.
        cf_h = tls.TLSHandshakes(
            handshakes=[tls.TLSHandshake() /
                        tls.TLSFinished(
                            data=self.sock.tls_ctx.get_verify_data())])
        msg1 = tls.TLSRecord(version='TLS_1_2') / cf_h
        if self.verbose:
            msg1.show()

        self.inject_bad(fuzzer)
        resp = self.send_recv(msg1)
        if self.verbose:
            resp.show()
            print(self.sock.tls_ctx)
        return False

    def _do_12_req(self, fuzzer=None):
        """ Send an HTTP request and get a response. """
        self.inject_bad(fuzzer)
        req = "GET / HTTP/1.1\r\nHost: %s\r\n\r\n" \
              % (self.host if self.host else self.sni[0])
        resp = self.send_recv(tls.TLSPlaintext(data=req))
        if resp.haslayer(tls.TLSRecord):
            self.http_resp = resp[tls.TLSRecord].data
            res = self.http_resp.startswith(GOOD_RESP)
        else:
            res = False
        if self.verbose:
            if res:
                print("==> Got response from server")
                resp.show()
                print("\n=== PASSED ===\n")
            else:
                print("\n=== FAILED ===\n")
        return res

    def do_12(self, fuzzer=None):
        with self.socket_ctx():
            if not self._do_12_hs(fuzzer):
                return False
            return self._do_12_req(fuzzer)


class TlsHandshakeStandard:
    """
    This class uses OpenSSL backend, so all its routines less customizable,
    but are good to test TempestaTLS behavior with standard tools and libs.
    """
    def __init__(self, addr='127.0.0.1', port=443, rto=0.5, verbose=False):
        self.addr = addr
        self.port = port
        self.rto = rto
        self.verbose = verbose

    def try_tls_vers(self, version):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.rto)

        # Collect warnings before TCP connection - we should have exactly
        # one warning for the whole test.
        warns = dmesg.count_warnings(TLS_HS_WARN)

        sock.connect((self.addr, self.port))
        try:
            tls_sock = ssl.wrap_socket(sock, ssl_version=version)
        except IOError:
            # Exception on client side TLS with established TCP connection -
            # we're good with connection rejection.
            sock.close()
            if dmesg.count_warnings(TLS_HS_WARN) == warns + 1:
                return True
            if self.verbose:
                print("TLS handshake failed w/o warning")
            return False

        tls_sock.send("GET / HTTP/1.1\r\nHost: tempesta-tech.com\r\n\r\n")
        resp = tls_sock.recv(100)
        tls_sock.close()
        if resp.startswith(GOOD_RESP):
            return False
        return True

    def do_old(self):
        """
        Test TLS 1.0 and TLS 1.1 handshakes.
        Modern OpenSSL versions don't support SSLv{1,2,3}.0, so use TLSv1.{0,1}
        just to test that we correctly drop wrong TLS connections. We do not
        support SSL as well and any SSL record is treated as a broken TLS
        record, so fuzzing of normal TLS fields should be used to test TLS
        fields processing.
        """
        for version in (ssl.PROTOCOL_TLSv1, ssl.PROTOCOL_TLSv1_1):
            if not self.try_tls_vers(version):
                return False
        return True
