from app import neo4j_connection as connection
from app.config import settings


def test_bridge_is_restricted_to_wsl_unencrypted_loopback(monkeypatch):
    monkeypatch.setattr(connection, 'is_wsl', lambda: True)
    def refused(*args, **kwargs):
        raise ConnectionRefusedError()
    monkeypatch.setattr(connection.socket, 'create_connection', refused)
    assert connection.bridge_required('neo4j://127.0.0.1:7687', 'auto')
    assert connection.bridge_required('bolt://localhost:7687', 'enabled')
    assert not connection.bridge_required('bolt://127.0.0.1:7687', 'disabled')
    assert not connection.bridge_required('bolt://remote.example:7687', 'enabled')
    assert not connection.bridge_required('neo4j+s://localhost:7687', 'auto')
    monkeypatch.setattr(connection, 'is_wsl', lambda: False)
    assert not connection.bridge_required('bolt://localhost:7687', 'enabled')


def test_auto_bridge_preserves_a_reachable_native_database(monkeypatch):
    monkeypatch.setattr(connection, 'is_wsl', lambda: True)
    class Reachable:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(connection.socket, 'create_connection', lambda *a, **k: Reachable())
    assert not connection.bridge_required('bolt://localhost:7687', 'auto')


def test_pool_is_reused_and_replaced_on_configuration_change(monkeypatch):
    from neo4j import GraphDatabase
    created = []
    class Driver:
        closed = False
        def close(self):
            self.closed = True
    def create(*args, **kwargs):
        driver = Driver()
        created.append(driver)
        return driver
    connection.close_graph_connections()
    monkeypatch.setattr(connection, 'bridge_required', lambda *a: False)
    monkeypatch.setattr(GraphDatabase, 'driver', create)
    monkeypatch.setattr(settings, 'neo4j_uri', 'bolt://unit-test.invalid:7687')
    try:
        assert connection.get_graph_driver() is connection.get_graph_driver()
        assert len(created) == 1
        monkeypatch.setattr(settings, 'neo4j_uri', 'bolt://other-test.invalid:7687')
        assert connection.get_graph_driver() is not created[0]
        assert created[0].closed and len(created) == 2
    finally:
        connection.close_graph_connections()
    assert created[1].closed
