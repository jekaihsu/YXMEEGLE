"""Immutable command envelope."""
from dataclasses import dataclass

from . import values as V

SOURCES = ('app', 'lark')
RESOLUTIONS = ('keep_current', 'apply_intended', 'set_explicit')


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    entity_id: str
    field_id: str
    expected_value: object      # SetValue | CLEAR (UNKNOWN is invalid)
    expected_revision: int
    intended_value: object      # SetValue | CLEAR (OMITTED/UNKNOWN cannot request mutation)
    actor: str
    source: str
    occurred_at: object         # offset-aware datetime or ISO string
    schema_binding_version: str
    approval_ref: str = None
    resolves: str = None        # conflict id for a resolution command
    resolution: str = None

    def validated(self):
        for name in ('command_id', 'entity_id', 'actor', 'schema_binding_version'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise V.ValidationError(f'{name} is required', 'missing_' + name)
        if self.source not in SOURCES:
            raise V.ValidationError('source must be app or lark', 'invalid_source')
        if self.expected_value is V.UNKNOWN or self.expected_value is V.OMITTED:
            raise V.ValidationError('expected baseline must be a known value or CLEAR', 'unknown_baseline')
        if self.intended_value is V.UNKNOWN or self.intended_value is V.OMITTED:
            raise V.ValidationError('OMITTED/UNKNOWN cannot request a mutation', 'no_mutation_requested')
        if isinstance(self.expected_revision, bool) or not isinstance(self.expected_revision, int) or self.expected_revision < 0:
            raise V.ValidationError('expected_revision must be a non-negative int', 'invalid_revision')
        expected = V.coerce(self.field_id, self.expected_value)
        intended = V.coerce(self.field_id, self.intended_value)
        occurred = V.to_utc_iso(self.occurred_at, 'occurred_at')
        if self.resolution is not None and self.resolution not in RESOLUTIONS:
            raise V.ValidationError('unknown resolution', 'invalid_resolution')
        if (self.resolution is None) != (self.resolves is None):
            raise V.ValidationError('resolution and resolves go together', 'invalid_resolution')
        return {'command_id': self.command_id, 'entity_id': self.entity_id, 'field_id': self.field_id,
                'expected': V.encode(expected), 'expected_revision': self.expected_revision,
                'intended': V.encode(intended), 'actor': self.actor, 'source': self.source,
                'occurred_at': occurred, 'approval_ref': self.approval_ref,
                'schema_binding_version': self.schema_binding_version,
                'resolves': self.resolves, 'resolution': self.resolution}


def payload_fingerprint(payload):
    return V.fingerprint(payload)
