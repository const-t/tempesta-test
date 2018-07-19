import abc
import time

from helpers import deproxy, tf_cfg, stateful

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2018 Tempesta Technologies, Inc.'
__license__ = 'GPL2'

class BaseDeproxyClient(deproxy.Client):

    def handle_read(self):
        self.response_buffer += self.recv(deproxy.MAX_MESSAGE_SIZE)
        if not self.response_buffer:
            return
        tf_cfg.dbg(4, '\tDeproxy: Client: Receive response.')
        tf_cfg.dbg(5, self.response_buffer)
        try:
            response = deproxy.Response(self.response_buffer,
                                method=self.request.method)
            self.response_buffer = self.response_buffer[len(response.msg):]
        except deproxy.IncompliteMessage:
            return
        except deproxy.ParseError:
            tf_cfg.dbg(4, ('Deproxy: Client: Can\'t parse message\n'
                           '<<<<<\n%s>>>>>'
                           % self.response_buffer))
            raise
        if len(self.response_buffer) > 0:
            # TODO: take care about pipelined case
            raise deproxy.ParseError('Garbage after response'
                                     ' end:\n```\n%s\n```\n' % \
                                     self.response_buffer)
        self.recieve_response(response)
        self.response_buffer = ''

    def writable(self):
        return len(self.request_buffer) > 0

    def make_request(self, request):
        self.request = deproxy.Request(request)
        self.request_buffer = request

    @abc.abstractmethod
    def recieve_response(self, response):
        raise NotImplementedError("Not implemented 'recieve_response()'")

class DeproxyClient(BaseDeproxyClient):
    last_response = None
    responses = []
    nr = 0

    def recieve_response(self, response):
        tf_cfg.dbg(4, "Recieved response: %s" % str(response.msg))
        self.responses.append(response)
        self.last_response = response

    def make_request(self, request):
        self.nr = len(self.responses)
        BaseDeproxyClient.make_request(self, request)

    def wait_for_response(self, timeout=5):
        if self.state != stateful.STATE_STARTED:
            return False

        t0 = time.time()
        while len(self.responses) == self.nr:
            t = time.time()
            if t - t0 > timeout:
                return False
            time.sleep(0.01)
        return True