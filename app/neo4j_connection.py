"""Process-owned Neo4j pool and WSL -> Windows loopback transport.

The optional bridge is loopback-only, carries the original Bolt bytes, and never
receives credentials in process arguments. It starts/stops with this process.
"""
import atexit
import platform
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from urllib.parse import urlsplit

from app.config import settings

# Windows Console streams carry raw Bolt bytes through WSL interop pipes.
RELAY = r'''Add-Type -TypeDefinition 'using System; using System.Net.Sockets; using System.Threading.Tasks; public class BoltRelay { public static void Run(int port) { using(var c=new TcpClient("127.0.0.1",port)) { c.NoDelay=true; var n=c.GetStream(); var a=Console.OpenStandardInput().CopyToAsync(n); var b=n.CopyToAsync(Console.OpenStandardOutput()); Task.WhenAny(a,b).GetAwaiter().GetResult(); } } }'; [BoltRelay]::Run(PORT)'''


def is_wsl():
    return 'microsoft' in platform.release().lower()


def bridge_required(uri, mode):
    parsed = urlsplit(uri)
    eligible = (parsed.hostname in ('localhost', '127.0.0.1', '::1')
                and parsed.scheme in ('bolt', 'neo4j') and is_wsl())
    if mode == 'disabled' or not eligible:
        return False
    if mode == 'enabled':
        return True
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 7687), timeout=.3):
            return False
    except OSError:
        return True


class LoopbackBridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, executable, port):
        self.executable, self.target_port = executable, port
        self.children = set()
        self.children_lock = threading.Lock()
        super().__init__(('127.0.0.1', 0), BridgeHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True, name='neo4j-wsl-bridge')
        self.thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()
        with self.children_lock:
            children = list(self.children)
        for child in children:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)


class BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        process = subprocess.Popen([self.server.executable, '-NoProfile', '-NonInteractive', '-Command',
                                    RELAY.replace('PORT', str(self.server.target_port))],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        with self.server.children_lock:
            self.server.children.add(process)

        def upload():
            try:
                while data := self.request.recv(65536):
                    process.stdin.write(data)
                    process.stdin.flush()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
        thread = threading.Thread(target=upload, daemon=True)
        thread.start()
        try:
            while data := process.stdout.read1(65536):
                self.request.sendall(data)
        except OSError:
            pass
        finally:
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            thread.join(timeout=1)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            process.stdout.close()
            with self.server.children_lock:
                self.server.children.discard(process)


_lock = threading.RLock()
_driver = None
_bridge = None
_config = None
_transport = 'direct'


def get_graph_driver():
    global _driver, _bridge, _config, _transport
    from neo4j import GraphDatabase
    config = (settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, settings.neo4j_wsl_bridge)
    with _lock:
        if _driver is not None and _config == config:
            return _driver
        close_graph_connections()
        uri = settings.neo4j_uri
        if bridge_required(uri, settings.neo4j_wsl_bridge):
            executable = shutil.which('powershell.exe')
            if not executable:
                raise RuntimeError('WSL bridge requires Windows PowerShell on PATH')
            _bridge = LoopbackBridge(executable, urlsplit(uri).port or 7687)
            uri = 'bolt://127.0.0.1:'+str(_bridge.server_address[1])
            _transport = 'wsl_windows_loopback'
        else:
            _transport = 'direct'
        _driver = GraphDatabase.driver(uri, auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=5, connection_acquisition_timeout=10, max_transaction_retry_time=0,
            max_connection_pool_size=4, max_connection_lifetime=1800, keep_alive=True)
        _config = config
        return _driver


def close_graph_connections():
    global _driver, _bridge, _config
    with _lock:
        if _driver is not None:
            _driver.close()
            _driver = None
        if _bridge is not None:
            _bridge.stop()
            _bridge = None
        _config = None


def graph_status():
    if not settings.neo4j_enabled:
        return {'status': 'disabled', 'transport': None}
    started = time.monotonic()
    try:
        from neo4j import Query
        driver = get_graph_driver()
        with driver.session() as session:
            result = session.run(Query('RETURN 1 AS ok', timeout=5))
            row = result.single()
            summary = result.consume()
        return {'status': 'live', 'transport': _transport, 'server': summary.server.agent,
                'latency_ms': round((time.monotonic()-started)*1000), 'ok': row['ok'] == 1}
    except Exception as exc:
        # Error category is sufficient for diagnostics; no credentials or provider output.
        return {'status': 'unavailable', 'transport': _transport, 'error_type': type(exc).__name__,
                'latency_ms': round((time.monotonic()-started)*1000)}


atexit.register(close_graph_connections)
