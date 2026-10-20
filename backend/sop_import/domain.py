"""Local checklist vocabulary and lifecycle policy."""
from enum import Enum


class Disposition(str, Enum):
    TASK = 'task'
    REFERENCE = 'routing_reference'
    REVIEW = 'review_required'
    ROUTINE = 'routine_excluded'
    DISABLED = 'disabled_excluded'


class Applicability(str, Enum):
    APPLICABLE = 'applicable'
    NOT_APPLICABLE = 'not_applicable'
    UNRESOLVED = 'unresolved'


class Lifecycle(str, Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    BLOCKED = 'blocked'
    DONE = 'done'
    ARCHIVED = 'archived'


TRANSITIONS = {
    'start': ({Lifecycle.PENDING}, Lifecycle.IN_PROGRESS, False),
    'block': ({Lifecycle.PENDING, Lifecycle.IN_PROGRESS}, Lifecycle.BLOCKED, True),
    'resume': ({Lifecycle.BLOCKED}, Lifecycle.IN_PROGRESS, True),
    'reset': ({Lifecycle.BLOCKED}, Lifecycle.PENDING, True),
    'complete': ({Lifecycle.PENDING, Lifecycle.IN_PROGRESS, Lifecycle.BLOCKED}, Lifecycle.DONE, False),
    'reopen': ({Lifecycle.DONE}, Lifecycle.IN_PROGRESS, True),
    'archive': (set(Lifecycle) - {Lifecycle.ARCHIVED}, Lifecycle.ARCHIVED, True),
}
NODE_MAP = dict(zip(('N01', 'N02', 'N03', 'N04', 'N05', 'N06', 'N07', 'N08', 'N09'),
                    ('sales', 'pm', 'confirmation', 'field', 'control', 'mapping', 'report', 'pricing', 'settlement')))
SUBCONTRACT = {7, 20, 49, 54, 55, 56}
CONDITIONAL = SUBCONTRACT | {18, 22}
PARTICIPANT_ROLES = {'executor', 'checker', 'confirmer'}


class Failure(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status
        super().__init__(code)


def require(condition, code, status=422):
    if not condition:
        raise Failure(code, status)
