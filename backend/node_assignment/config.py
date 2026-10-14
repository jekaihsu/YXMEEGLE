"""Feature flag, table identities and cache windows, read once from the environment."""
import math
from dataclasses import dataclass

from ..remote_policy import formal_write_allowed


@dataclass(frozen=True)
class NodeAssignmentConfig:
    enabled: bool = False
    base: str = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
    node_table: str = 'tblcPZPmezkyeVb7'
    task_table: str = 'tblsoyGcC6K5AipF'
    people_table: str = 'tblfaCO2xPUNptQH'
    confirmation_table: str = 'tblmSQrcCs9vPQZx'
    read_ttl_seconds: float = 60
    roster_ttl_seconds: float = 120
    stale_max_seconds: float = 900
    lock_timeout_seconds: float = 10

    @classmethod
    def from_env(cls, env):
        defaults = cls()

        def number(key, default, minimum, maximum):
            try:
                value = float(env.get('NODE_ASSIGNMENT_' + key, default))
            except (TypeError, ValueError):
                return default
            return min(maximum, max(minimum, value)) if math.isfinite(value) else default

        def ident(key, default):
            value = str(env.get('NODE_ASSIGNMENT_' + key) or default).strip()
            return value if value.isalnum() else default

        return cls(
            enabled=str(env.get('NODE_ASSIGNMENT_ENABLED', 'false')).lower() == 'true',
            base=ident('BASE_TOKEN', defaults.base),
            node_table=ident('NODE_TABLE_ID', defaults.node_table),
            task_table=ident('TASK_TABLE_ID', defaults.task_table),
            people_table=ident('PEOPLE_TABLE_ID', defaults.people_table),
            confirmation_table=ident('CONFIRMATION_TABLE_ID', defaults.confirmation_table),
            read_ttl_seconds=number('READ_TTL_SECONDS', defaults.read_ttl_seconds, 5, 300),
            roster_ttl_seconds=number('ROSTER_TTL_SECONDS', defaults.roster_ttl_seconds, 30, 900),
            stale_max_seconds=number('STALE_MAX_SECONDS', defaults.stale_max_seconds, 60, 3600),
            lock_timeout_seconds=number('LOCK_TIMEOUT_SECONDS', defaults.lock_timeout_seconds, 1, 30),
        )

    @property
    def writable(self):
        """Configured write targets must sit inside the code-level allowlist."""
        return (formal_write_allowed(self.base, self.node_table)
                and formal_write_allowed(self.base, self.task_table))
