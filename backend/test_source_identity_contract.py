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
    {"name": "same name"},
    {"case_number": "C115001"},
    {"suffix": "r1"},
    {"source_key": "r1"},
])
def test_names_case_numbers_and_suffixes_do_not_join(candidate):
    ref = SourceRef.from_entity({
        "base_token": "base-A", "table_id": "table-B", "record_id": "r1",
        "name": "same name", "case_number": "C115001",
    })
    edge = {
        **candidate,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "independently_verified",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }

    assert resolve_edge(ref, [edge]) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "edge_absent",
        "target_source_key": None,
    }


@pytest.mark.parametrize("field,value", [
    ("verification_status", None),
    ("verification_status", "pending"),
    ("verified_by", None),
    ("verified_by", ""),
    ("verified_by", " \t\n"),
    ("evidence_ref", None),
    ("evidence_ref", ""),
    ("evidence_ref", " \t\n"),
    ("target_source_key", None),
    ("target_source_key", ""),
    ("target_source_key", " \t\n"),
])
def test_unverified_or_incomplete_edge_returns_unresolved_row(field, value):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edge = {
        "source_key": ref.source_key,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "independently_verified",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }
    if value is None:
        del edge[field]
    else:
        edge[field] = value

    assert resolve_edge(ref, [edge]) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "edge_unverified",
        "target_source_key": None,
    }


@pytest.mark.parametrize("source_key", [
    "base-a/table-B/r1",
    "base-A/table-b/r1",
    "base-A/table-B/R1",
    "base-a/table-b/r1",
    "base-other/table-B/r1",
    "base-A/table-other/r1",
])
def test_verified_edge_requires_exact_base_table_and_record_identity(source_key):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edge = {
        "source_key": source_key,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "independently_verified",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }

    assert resolve_edge(ref, [edge]) == {
        "source_key": "base-A/table-B/r1",
        "mapping_status": "unresolved",
        "mapping_reason": "edge_absent",
        "target_source_key": None,
    }


@pytest.mark.parametrize("edges", [None, [], [{"source_key": "unrelated"}], [None]])
def test_absent_exact_edge_returns_edge_absent(edges):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})

    assert resolve_edge(ref, edges) == {
        "source_key": "base-A/table-B/r1",
        "mapping_status": "unresolved",
        "mapping_reason": "edge_absent",
        "target_source_key": None,
    }


def test_verified_target_resolves_despite_duplicate_and_unverified_edges():
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    verified = {
        "source_key": ref.source_key,
        "target_source_key": "base-X/table-Y/record-Z",
        "verification_status": "independently_verified",
        "verified_by": "reviewer-1",
        "evidence_ref": "evidence-123",
    }
    unverified = {**verified, "target_source_key": "other-target", "verified_by": ""}

    assert resolve_edge(ref, [unverified, verified, dict(verified)]) == {
        "source_key": "base-A/table-B/r1",
        "mapping_status": "resolved",
        "mapping_reason": "independently_verified_edge",
        "target_source_key": "base-X/table-Y/record-Z",
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
