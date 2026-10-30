from types import SimpleNamespace
from .sop_import.lark_projection import drain_lock


def test_postgres_lock_uses_autocommit_during_network_calls():
    class Connection:
        def __init__(self): self.autocommit = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execution_options(self, **kwargs):
            self.autocommit = kwargs == {'isolation_level': 'AUTOCOMMIT'}
            return self
        def execute(self, statement):
            assert self.autocommit
            return SimpleNamespace(scalar=lambda: True)
    connection = Connection()
    engine = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'), connect=lambda: connection)
    with drain_lock(engine) as acquired:
        assert acquired and connection.autocommit
