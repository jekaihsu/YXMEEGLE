from dataclasses import FrozenInstanceError

import pytest

from .source_identity import SourceRef, resolve_edge
from .source_entities import entity_id


def test_source_ref_wraps_existing_entity_id_and_retains_components():
    row = {"base_token": "base-A", "table_id": "table-B", "record_id": "record-C"}

    ref = SourceRef.from_entity(row, view="view-D", version=7)

    assert ref.source_key == entity_id(row) == "base-A/table-B/record-C"
    assert (ref.base, ref.table, ref.view, ref.record_id, ref.version) == (
        "base-A", "table-B", "view-D", "record-C", 7
    )
    with pytest.raises(FrozenInstanceError):
        ref.version = 8


def test_source_ref_requires_complete_source_entity_identity():
    with pytest.raises(ValueError, match="base_token, table_id, and record_id"):
        SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B"})


def test_only_independently_verified_exact_source_key_edge_resolves():
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edges = [{
        "source_key": ref.source_key,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "independently_verified",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }]

    assert resolve_edge(ref, edges) == {
        "source_key": "base-A/table-B/r1",
        "mapping_status": "resolved",
        "mapping_reason": "independently_verified_edge",
        "target_source_key": "base-X/table-Y/record-Z",
    }


@pytest.mark.parametrize("candidate", [
    {"name": "same name", "target_source_key": "guessed-by-name"},
    {"case_number": "C115001", "target_source_key": "guessed-by-case"},
    {"suffix": "-01", "target_source_key": "guessed-by-suffix"},
])
def test_names_case_numbers_and_suffixes_do_not_join(candidate):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})

    assert resolve_edge(ref, [candidate]) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "edge_absent",
        "target_source_key": None,
    }


def test_unverified_or_incomplete_edge_returns_unresolved_row():
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edge = {
        "source_key": ref.source_key,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "pending",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }

    assert resolve_edge(ref, [edge]) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "edge_absent",
        "target_source_key": None,
    }


def test_conflicting_verified_edges_remain_unresolved():
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edges = [
        {"source_key": ref.source_key, "target_source_key": target,
         "verification_status": "independently_verified", "verified_by": "reviewer",
         "evidence_ref": "evidence"}
        for target in ("target-1", "target-2")
    ]

    assert resolve_edge(ref, edges) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "ambiguous_verified_edges",
        "target_source_key": None,
    }
