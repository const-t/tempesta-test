#! /usr/bin/python3
from framework import tester

from multiprocessing import Process
from random import randint
import websockets
import asyncio
import ssl
import os
from framework.x509 import CertGenerator


hostname = 'localhost'
ping_message = "ping_test"


TEMPESTA_CONFIG = """
listen 81;
listen 82 proto=https;

srv_group localhost {

    server ${server_ip}:8099;
}

vhost localhost {
    tls_certificate /tmp/cert.pem;
    tls_certificate_key /tmp/key.pem;

    proxy_pass localhost;

}

http_chain {
    -> localhost;
}
%s
"""

TEMPESTA_STRESS_CONFIG = """
listen 81;
listen 82 proto=https;

srv_group localhost {

    server ${server_ip}:8099;
    server ${server_ip}:8100;
    server ${server_ip}:8101;
    server ${server_ip}:8102;
    server ${server_ip}:8103;
    server ${server_ip}:8104;
    server ${server_ip}:8105;
    server ${server_ip}:8106;

}

vhost localhost {
    tls_certificate /tmp/cert.pem;
    tls_certificate_key /tmp/key.pem;

    proxy_pass localhost;

}

http_chain {
    -> localhost;
}
"""

TEMPESTA_NGINX_CONFIG = """
listen 81;
listen 82 proto=https;

srv_group localhost {
    server ${server_ip}:8000;
}

vhost localhost {
    tls_certificate /tmp/cert.pem;
    tls_certificate_key /tmp/key.pem;

    proxy_pass localhost;

}

http_chain {
    -> localhost;
}
%s
"""

NGINX_CONFIG = """
pid ${pid};
worker_processes  auto;

events {
    worker_connections   1024;
    use epoll;
}

http {
    map $$http_upgrade $$connection_upgrade {
        default Upgrade;
        ''      close;
    }

    upstream websocket {
        ip_hash;
        server 0.0.0.0:8099;
    }

    upstream wss_websockets {
        ip_hash;
        server 0.0.0.0:8099;
    }

    server {
        listen 8000;
        location / {
            proxy_pass http://websocket;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $$http_upgrade;
            proxy_set_header Connection $$connection_upgrade;
            proxy_set_header Host $$host;
        }
    }

    server {
        listen 8001 ssl;
        ssl_protocols TLSv1.2;
        ssl_certificate /tmp/cert.pem;
        ssl_certificate_key /tmp/key.pem;
        location / {
            proxy_pass http://wss_websockets;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $$http_upgrade;
            proxy_set_header Connection $$connection_upgrade;
            proxy_set_header Host $$host;
        }
    }
}
"""


def gen_cert(host_name):
    cert_path = "/tmp/cert.pem"
    key_path = "/tmp/key.pem"
    cgen = CertGenerator(cert_path, key_path)
    cgen.CN = host_name
    cgen.generate()


def remove_certs(cert_files_):
    for cert in cert_files_:
        os.remove(cert)


class Ws_ping(tester.TempestaTest):

    backends = []        

    clients = []

    tempesta = {
        'config': TEMPESTA_CONFIG % "",
    }

    # Client

    def run_test(self, port, n):
        asyncio.run(self.ws_ping_test(port, n))

    async def ws_ping_test(self, port, n):
        global ping_message
        host = hostname
        for i in range(n):
            async with websockets.connect(f"ws://{host}:{port}") as websocket:
                await websocket.send(ping_message)
                await websocket.recv()

    async def wss_ping_test(self, port, n):
        global ping_message
        host = hostname
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations("/tmp/cert.pem")
        for _ in range(n):
            async with websockets.connect(f"wss://{host}:{port}",
                                          ssl=ssl_context) as websocket:
                await websocket.send(ping_message)
                await websocket.recv()

    async def run_stress(port, n):
        print("run_stress")
        global ping_message
        host = hostname
        for _ in range(n):
            timeout_ = randint(0, 2)
            async with websockets.connect(f"ws://{host}:{port}",
                                          timeout=timeout_) as websocket:
                await websocket.send(ping_message)

    def run_ws(self, port, count=1, proxy=False):
        gen_cert(hostname)
        ssl._create_default_https_context = ssl._create_unverified_context
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain("/tmp/cert.pem", keyfile="/tmp/key.pem")
        if proxy:
            self.start_all_servers()
        loop = asyncio.get_event_loop()
        for i in range(count):
            asyncio.ensure_future(websockets.serve(self.handler, hostname, port+i))
        loop.run_forever()

    def test_ping_websockets(self):
        p1 = Process(target=self.run_ws, args=(8099,))
        p2 = Process(target=self.run_test, args=(81, 4))
        p1.start()
        self.get_tempesta().start()
        while not self.get_tempesta().is_running():
            pass
        p2.start()
        p2.join()
        p1.terminate()
        p2.terminate()

    # Backend

    def remove_certs(self, cert_files_):
        for cert in cert_files_:
            os.remove(cert)

    async def handler(self, websocket, path):
        global ping_message
        data = await websocket.recv()
        reply = f"{data}"
        if f"{data}" == ping_message:
            print("message_ok")
        await websocket.send(reply)


class Wss_ping(Ws_ping):

    def run_test(self, port, n):
        asyncio.run(self.wss_ping_test(port, n))

    def test_ping_websockets(self):
        p1 = Process(target=self.run_ws, args=(8099,))
        p2 = Process(target=self.run_test, args=(82, 4))
        p1.start()
        self.get_tempesta().start()
        while not self.get_tempesta().is_running():
            pass
        p2.start()
        p2.join()
        p1.terminate()
        remove_certs(['/tmp/cert.pem', '/tmp/key.pem'])


class Wss_ping_with_nginx(Wss_ping):

    backends = [{
            'id': 'nginx',
            'type': 'nginx',
            'port': '8000',
            'status_uri': 'http://${server_ip}:8000/nginx_status',
            'config': NGINX_CONFIG,
        }]

    tempesta = {
        'config': TEMPESTA_NGINX_CONFIG % "",
    }

    def test_ping_websockets(self):
        p1 = Process(target=self.run_ws, args=(8099, 1, True))
        p2 = Process(target=self.run_test, args=(82, 4))
        p1.start()
        self.get_tempesta().start()
        while not self.get_tempesta().is_running():
            pass
        p2.start()
        p2.join()
        p1.terminate()
        self.get_server('nginx').stop_nginx()
        remove_certs(['/tmp/cert.pem', '/tmp/key.pem'])


class Wss_stress(Wss_ping):

    tempesta = {
        'config': TEMPESTA_STRESS_CONFIG,
    }

    def run_test(self, port, n):
        asyncio.run(self.wss_ping_test(port, n))

    def test_ping_websockets(self):
        p1 = Process(target=self.run_ws, args=(8099, 8))
        p2 = Process(target=self.run_test, args=(82, 400))
        p1.start()
        self.get_tempesta().start()
        while not self.get_tempesta().is_running():
            pass
        p2.start()
        p2.join()
        p1.terminate()
        remove_certs(['/tmp/cert.pem', '/tmp/key.pem'])

    async def wss_ping_test(self, port, n):
        host = hostname
        global ping_message
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations("/tmp/cert.pem")
        count = 0
        next_restart = randint(0, int(n/4))
        for _ in range(n):
            count += 1
            if count == next_restart:
                count = 0
                next_restart = randint(0, int(n/4))
                self.get_tempesta().restart()
            async with websockets.connect(f"wss://{host}:{port}",
                                          ssl=ssl_context) as websocket:
                await websocket.send(ping_message)
                await websocket.recv()