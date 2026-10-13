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
    unverified = {**verified, "target_source_key": "base-X/table-Y/other", "verified_by": ""}

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
        for target in ("base-X/table-Y/t1", "base-X/table-Y/t2")
    ]

    assert resolve_edge(ref, edges) == {
        "source_key": ref.source_key,
        "mapping_status": "unresolved",
        "mapping_reason": "ambiguous_verified_edges",
        "target_source_key": None,
    }


VALID_EDGE = {
    "target_source_key": "base-X/table-Y/record-Z",
    "verification_status": "independently_verified",
    "verified_by": "reviewer-1",
    "evidence_ref": "evidence-123",
}


@pytest.mark.parametrize("args", [
    ("", "", "", "", "", None),
    ("base-A/table-B/r1", "base-A", "table-B", "", "r1", True),
    ("base-A/table-B/r1", "base-A", "table-B", "", "r1", False),
    ("base-A/table-B/r1", "base-A", "table-B", "", "r1", 1.5),
    ("base-A/table-B/r1", "base-A", "table-B", "", "r1", " "),
    ("base-A/table-B/r1", "base-A", "table-B", None, "r1", None),
    ("other/table-B/r1", "base-A", "table-B", "", "r1", None),
    ("base-A/table-B/r1 ", "base-A", "table-B", "", "r1", None),
    ("b/t/x/r", "b/t", "x", "", "r", None),
    ("b/t/x/r", "b", "t/x", "", "r", None),
    ("b/t/x/r", "b", "t", "", "x/r", None),
    (" b/t/r", " b", "t", "", "r", None),
    ("b/t/r ", "b", "t", "", "r ", None),
    ("b/1/r", "b", 1, "", "r", None),
])
def test_direct_source_ref_construction_is_validated(args):
    with pytest.raises(ValueError):
        SourceRef(*args)


@pytest.mark.parametrize("row", [
    {"base_token": "b/t", "table_id": "x", "record_id": "r"},
    {"base_token": "b", "table_id": "t/x", "record_id": "r"},
    {"base_token": "b", "table_id": "t", "record_id": " r"},
])
def test_slash_or_padded_components_are_rejected_not_collided(row):
    with pytest.raises(ValueError):
        SourceRef.from_entity(row)


@pytest.mark.parametrize("version", [True, False, 1.0, b"1", "", " 1"])
def test_from_entity_rejects_bool_and_malformed_versions(version):
    with pytest.raises(ValueError):
        SourceRef.from_entity({"base_token": "b", "table_id": "t", "record_id": "r"}, version=version)


@pytest.mark.parametrize("target", [
    " base-X/table-Y/record-Z", "base-X/table-Y/record-Z ", "base-X/ table-Y/record-Z",
    "guess", "base-X/table-Y", "base-X/table-Y/record-Z/extra", "base-X//record-Z", 7,
])
def test_padded_or_malformed_target_is_never_resolved(target):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    edge = {**VALID_EDGE, "source_key": ref.source_key, "target_source_key": target}

    assert resolve_edge(ref, [edge])["mapping_reason"] == "edge_unverified"
    assert resolve_edge(ref, [edge])["target_source_key"] is None


def test_padded_duplicate_does_not_create_false_ambiguity():
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    clean = {**VALID_EDGE, "source_key": ref.source_key}
    padded = {**clean, "target_source_key": "base-X/table-Y/record-Z "}

    result = resolve_edge(ref, [clean, padded])

    assert result["mapping_status"] == "resolved"
    assert result["target_source_key"] == "base-X/table-Y/record-Z"


@pytest.mark.parametrize("registry", [
    "base-A/table-B/r1", b"base-A/table-B/r1", 7, object(),
    {"base-A/table-B/r1": {**VALID_EDGE, "source_key": "base-A/table-B/r1"}},
])
def test_non_sequence_registry_fails_instead_of_reporting_absent(registry):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})

    with pytest.raises(TypeError):
        resolve_edge(ref, registry)
