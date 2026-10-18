"""The only V4 write path of dispatch publish: one 任務 row per command.

The table comes from the source manifest, never from a request, and must sit inside the code-level formal
write allowlist. Writes carry client_token = command_id, run once (an uncertain outcome is never blindly
re-sent here) and only touch the allowlisted fields.
"""
from ..dispatch_board.config import PUBLISH_TABLES
from ..node_assignment.config import NodeAssignmentConfig
from ..node_assignment.lark_table import BitableClient, Table
from .domain import WRITABLE

READ_FIELDS = list(PUBLISH_TABLES['tasks'].fields)


class TaskTable:
    def __init__(self, cfg, base, transport=None, client_options=None):
        self.cfg, self.transport, self.client_options = cfg, transport, client_options or {}
        self.config = NodeAssignmentConfig(base=base, task_table=PUBLISH_TABLES['tasks'].table_id)

    def _client(self):
        return BitableClient(self.cfg, self.config, self.transport, **self.client_options)

    @staticmethod
    def _allowed(fields):
        extra = set(fields) - WRITABLE
        if extra:
            raise ValueError(f'fields outside the 任務 write allowlist: {sorted(extra)}')

    def create(self, fields, client_token):
        self._allowed(fields)
        with self._client() as client:
            return client.create(Table.TASKS, fields, client_token)

    def update(self, record_id, fields):
        self._allowed(fields)
        with self._client() as client:
            client.update(Table.TASKS, record_id, fields)

    def get(self, record_id):
        with self._client() as client:
            return client.get(Table.TASKS, record_id)

    def by_command(self, command_id):
        with self._client() as client:
            return client.search(Table.TASKS, [{'field_name': '命令編號', 'operator': 'is', 'value': [command_id]}],
                                 'and', field_names=READ_FIELDS)
