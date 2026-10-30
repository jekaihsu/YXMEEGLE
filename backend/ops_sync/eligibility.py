"""Stable person identity, PM eligibility evidence, application authorization and directory admission.

The three questions are deliberately independent (contract: identity/eligibility/authorization):
  * EligibilitySource  - may this person hold a PM seat?            (eligible | ineligible | unknown)
  * AppPolicy          - may this actor perform this application action?
  * Directory          - is this person an active, application-admitted identity?
Unknown eligibility denies. Names are display text and never take part in matching.
"""
import re
from dataclasses import dataclass
from datetime import timedelta

from . import values as V

ELIGIBLE, INELIGIBLE, UNKNOWN_ELIGIBILITY = 'eligible', 'ineligible', 'unknown'
_ID_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,64}$')


@dataclass(frozen=True)
class PersonIdentity:
    tenant: str
    app_id: str
    person_id: str

    def validated(self):
        for name in ('tenant', 'app_id', 'person_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not _ID_RE.match(value):
                raise V.ValidationError(f'{name} must be a stable identifier, not a display name', 'invalid_person')
        return self

    @property
    def key(self):
        return f'{self.tenant}|{self.app_id}|{self.person_id}'

    @classmethod
    def from_key(cls, key):
        tenant, app_id, person_id = key.split('|')
        return cls(tenant, app_id, person_id).validated()


@dataclass(frozen=True)
class Eligibility:
    status: str
    revision: int = 0
    observed_at: object = None
    valid_until: object = None
    reason: str = ''


def unknown(reason, revision=0):
    return Eligibility(UNKNOWN_ELIGIBILITY, revision, None, None, reason)


def evaluate(source, identity, at):
    """Normalise whatever the source says. Anything missing, stale, malformed or failing is unknown."""
    try:
        identity.validated()
        at = V.require_aware(at, 'at')
        result = source.lookup(identity, at)
    except V.OpsError as exc:
        return unknown(exc.code)
    except Exception:
        return unknown('source_error')
    if not isinstance(result, Eligibility) or result.status not in (ELIGIBLE, INELIGIBLE, UNKNOWN_ELIGIBILITY):
        return unknown('malformed_evidence')
    if isinstance(result.revision, bool) or not isinstance(result.revision, int):
        return unknown('malformed_evidence')
    if result.status == UNKNOWN_ELIGIBILITY:
        return result
    try:
        observed = V.require_aware(result.observed_at, 'observed_at')
        limit = V.require_aware(result.valid_until, 'valid_until')
    except V.OpsError:
        return unknown('malformed_evidence', result.revision)
    if observed > at:
        return unknown('evidence_from_future', result.revision)
    if limit <= at:
        return unknown('stale_evidence', result.revision)
    return result


class MockEligibilitySource:
    """Injected, in-memory evidence. The real Lark field/governance is an OPEN owner decision."""

    def __init__(self, tenant, app_id):
        self.tenant, self.app_id = tenant, app_id
        self._rows = {}
        self.lookups = 0

    def set(self, identity, status, at, valid_seconds=3600, revision=None, reason=''):
        prior = self._rows.get(identity.key)
        revision = revision if revision is not None else (prior.revision + 1 if prior else 1)
        until = V.require_aware(at) + timedelta(seconds=valid_seconds)
        self._rows[identity.key] = Eligibility(status, revision, V.require_aware(at), until, reason)

    def drop(self, identity):
        self._rows.pop(identity.key, None)

    def lookup(self, identity, at):
        self.lookups += 1
        if (identity.tenant, identity.app_id) != (self.tenant, self.app_id):
            return unknown('wrong_application')
        return self._rows.get(identity.key) or unknown('no_evidence')


class MockAppPolicy:
    """Application authorization: (actor key, action) grants. Default deny; eligibility never implies a grant."""

    def __init__(self):
        self._grants = set()

    def grant(self, actor, action):
        self._grants.add((actor.key if hasattr(actor, 'key') else actor, action))

    def revoke(self, actor, action):
        self._grants.discard((actor.key if hasattr(actor, 'key') else actor, action))

    def allows(self, actor_key, action, entity_id=None):
        return (actor_key, action) in self._grants


class MockDirectory:
    """Active, application-admitted stable identities. Display names are kept only for rendering."""

    def __init__(self):
        self._active = {}

    def admit(self, identity, display_name=''):
        self._active[identity.key] = display_name

    def deactivate(self, identity):
        self._active.pop(identity.key, None)

    def is_active(self, identity):
        return identity.key in self._active

    def display_name(self, identity):
        return self._active.get(identity.key, '')

