"""Stable source identity references resolved only by verified registry edges.

This module deliberately does not infer identity from display names, case
numbers, or suffixes.  A caller may provide an edge registry, but an edge is
usable only when its independent verification state and evidence are present.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .source_entities import entity_id


def _key_component(value):
    """A key part is a non-empty str with no '/' and no surrounding whitespace."""
    return isinstance(value, str) and bool(value) and value == value.strip() and "/" not in value


def is_source_key(value):
    """True for an exact ``base/table/record`` key whose three parts are clean."""
    if not isinstance(value, str):
        return False
    parts = value.split("/")
    return len(parts) == 3 and all(_key_component(part) for part in parts)


def _sequence(value, name):
    """Iterate a caller list; a mapping, string or scalar is a caller bug, not "absent"."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of rows, not {type(value).__name__}")
    return value


@dataclass(frozen=True)
class SourceRef:
    """A source record reference retaining the existing source entity key."""

    source_key: str
    base: str
    table: str
    view: str
    record_id: str
    version: int | str | None

    def __post_init__(self):
        if not all(_key_component(value) for value in (self.base, self.table, self.record_id)):
            raise ValueError("base, table and record_id must be non-empty, unpadded and contain no '/'")
        if self.source_key != "/".join((self.base, self.table, self.record_id)):
            raise ValueError("source_key must equal the joined base/table/record_id")
        if not isinstance(self.view, str):
            raise ValueError("view must be a string")
        version = self.version
        if isinstance(version, bool) or not (
                version is None or isinstance(version, int)
                or (isinstance(version, str) and version and version == version.strip())):
            raise ValueError("version must be an integer, a non-blank unpadded string, or None")

    @classmethod
    def from_entity(cls, row, *, view="", version=None):
        """Build a reference from a source entity row using its canonical id."""
        base = row.get("base_token")
        table = row.get("table_id")
        record_id = row.get("record_id")
        if not all(isinstance(value, str) and value for value in (base, table, record_id)):
            raise ValueError("source entity requires non-empty base_token, table_id, and record_id")
        return cls(entity_id(row), base, table, view, record_id, version)


def unresolved_row(source_ref, *, reason="edge_absent"):
    """Return an explicit unresolved result without claiming a target mapping."""
    return {
        "source_key": source_ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": reason,
        "target_source_key": None,
    }


def resolve_edge(source_ref, edge_registry):
    """Resolve an exact source key through independently verified registry edges.

    Registry entries use ``source_key`` and ``target_source_key`` as identity
    endpoints.  Entries without an explicit independent verification status,
    verifier, and evidence reference remain unresolved as ``edge_unverified``;
    no exact entry is ``edge_absent``.  A target must itself be an exact,
    unpadded ``base/table/record`` key.  Display fields are never consulted,
    even if they happen to match.  A registry that is a mapping, string or
    scalar raises ``TypeError`` rather than reading as an absent edge.
    """
    verified_targets = set()
    exact_edge_present = False
    for edge in _sequence(edge_registry, "edge_registry"):
        if not isinstance(edge, dict) or edge.get("source_key") != source_ref.source_key:
            continue
        exact_edge_present = True
        if edge.get("verification_status") != "independently_verified":
            continue
        if not all(isinstance(edge.get(key), str) and edge[key].strip()
                   for key in ("verified_by", "evidence_ref")):
            continue
        if not is_source_key(edge.get("target_source_key")):
            continue
        verified_targets.add(edge["target_source_key"])

    if not verified_targets:
        return unresolved_row(
            source_ref, reason="edge_unverified" if exact_edge_present else "edge_absent"
        )
    if len(verified_targets) != 1:
        return unresolved_row(source_ref, reason="ambiguous_verified_edges")
    return {
        "source_key": source_ref.source_key,
        "mapping_status": "resolved",
        "mapping_reason": "independently_verified_edge",
        "target_source_key": next(iter(verified_targets)),
    }
