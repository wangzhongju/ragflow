"""Forward a loopback registry over SSH to Docker Hub through a local HTTP proxy.

Requires requests and paramiko. Authenticate SSH hosts once with the ssh client
before use; this tool rejects unknown host keys. No Docker daemon restart needed.
"""

import argparse
import getpass
import http.server
import select
import socket
import threading
import time

import paramiko
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", required=True)
    parser.add_argument("--user", default="cdky")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--remote-port", type=int, default=15080)
    args = parser.parse_args()
    password = getpass.getpass("SSH password (not saved): ")
    proxies = {"http": args.proxy, "https": args.proxy}
    tokens = {}
    allowed = {"library/mysql", "library/redis", "redis/redisinsight", "infiniflow/ragflow"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_HEAD(self):
            self.forward(False)

        def do_GET(self):
            self.forward(True)

        def forward(self, body):
            if self.path.rstrip("/") == "/v2":
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                if body:
                    self.wfile.write(b"{}")
                return
            name = self.path[4:].rsplit("/", 2)[0]
            if not self.path.startswith("/v2/") or name not in allowed:
                self.send_error(403)
                return
            sent = False
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    session.proxies = proxies
                    token, expires = tokens.get(name, (None, 0))
                    if time.monotonic() >= expires:
                        auth = session.get("https://auth.docker.io/token", params={"service": "registry.docker.io", "scope": f"repository:{name}:pull"}, timeout=30)
                        auth.raise_for_status()
                        token = auth.json()["token"]
                        tokens[name] = (token, time.monotonic() + 240)
                    headers = {"Authorization": f"Bearer {token}", "Accept": self.headers.get("Accept", "*/*"), "Accept-Encoding": "identity"}
                    with session.request(self.command, "https://registry-1.docker.io" + self.path, headers=headers, stream=True, timeout=(30, 180)) as upstream:
                        self.send_response(upstream.status_code)
                        for key in ("Content-Type", "Content-Length", "Docker-Content-Digest", "Docker-Distribution-Api-Version"):
                            if key in upstream.headers:
                                self.send_header(key, upstream.headers[key])
                        self.send_header("Connection", "close")
                        self.end_headers()
                        sent = True
                        if body:
                            for chunk in upstream.iter_content(256 * 1024):
                                self.wfile.write(chunk)
                        if "/manifests/" in self.path:
                            print(self.path, upstream.status_code, upstream.headers.get("Docker-Content-Digest", ""), flush=True)
            except Exception as exc:
                print(type(exc).__name__, str(exc), flush=True)
                if not sent:
                    self.send_error(502)
            finally:
                self.close_connection = True

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def relay(channel):
        with socket.create_connection(server.server_address) as connection:
            try:
                while True:
                    ready, _, _ = select.select([channel, connection], [], [], 30)
                    for source in ready:
                        data = source.recv(256 * 1024)
                        if not data:
                            return
                        (channel if source is connection else connection).sendall(data)
            finally:
                channel.close()

    clients = []
    try:
        for host in args.host:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.connect(host, username=args.user, password=password, timeout=15)
            clients.append(client)
            transport = client.get_transport()
            transport.set_keepalive(20)
            transport.request_port_forward("127.0.0.1", args.remote_port, handler=lambda channel, *unused: threading.Thread(target=relay, args=(channel,), daemon=True).start())
            print(f"{host}:127.0.0.1:{args.remote_port} -> official Docker Hub; Ctrl+C to close", flush=True)
        while all(client.get_transport().is_active() for client in clients):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
