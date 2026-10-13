"""Stable source identity references resolved only by verified registry edges.

This module deliberately does not infer identity from display names, case
numbers, or suffixes.  A caller may provide an edge registry, but an edge is
usable only when its independent verification state and evidence are present.
"""
from dataclasses import dataclass

from .source_entities import entity_id


@dataclass(frozen=True)
class SourceRef:
    """A source record reference retaining the existing source entity key."""

    source_key: str
    base: str
    table: str
    view: str
    record_id: str
    version: int | str | None

    @classmethod
    def from_entity(cls, row, *, view="", version=None):
        """Build a reference from a source entity row using its canonical id."""
        base = row.get("base_token")
        table = row.get("table_id")
        record_id = row.get("record_id")
        if not all(isinstance(value, str) and value for value in (base, table, record_id)):
            raise ValueError("source entity requires non-empty base_token, table_id, and record_id")
        if not isinstance(view, str):
            raise ValueError("view must be a string")
        if version is not None and not isinstance(version, (int, str)):
            raise ValueError("version must be an integer, string, or None")
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
    no exact entry is ``edge_absent``.  Display fields are never consulted,
    even if they happen to match.
    """
    verified_targets = set()
    exact_edge_present = False
    for edge in edge_registry or ():
        if not isinstance(edge, dict) or edge.get("source_key") != source_ref.source_key:
            continue
        exact_edge_present = True
        if edge.get("verification_status") != "independently_verified":
            continue
        if not all(isinstance(edge.get(key), str) and edge[key].strip()
                   for key in ("verified_by", "evidence_ref", "target_source_key")):
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
