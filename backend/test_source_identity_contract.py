from dataclasses import FrozenInstanceError

import pytest

from . import source_identity, v4_sources
from .source_identity import (
    EdgeType, SourceRef, build_native_edge_graph, children_of, edge_sources, edge_targets,
    parents_of, resolve_edge, stable_identity,
)
from .source_entities import entity_id
from .sources import source_id


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


def test_well_formed_verified_claim_is_unresolved_verifier_unavailable():
    """Owner decision superseding D3: free-form verification strings are not authority (no VCC-117 receipt
    schema/verifier exists), so a well-formed claim stays unresolved as verifier_unavailable."""
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
        "mapping_status": "unresolved",
        "mapping_reason": "verifier_unavailable",
        "target_source_key": None,
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


def test_duplicate_and_unverified_claims_do_not_resolve_either():
    """Owner decision superseding D3: free-form verification strings are not authority (no VCC-117 receipt
    schema/verifier exists), so a well-formed claim stays unresolved as verifier_unavailable."""
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
        "mapping_status": "unresolved",
        "mapping_reason": "verifier_unavailable",
        "target_source_key": None,
    }


def test_conflicting_verified_claims_remain_unresolved():
    """Owner decision superseding D3: free-form verification strings are not authority (no VCC-117 receipt
    schema/verifier exists), so a well-formed claim stays unresolved as verifier_unavailable."""
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
        "mapping_reason": "verifier_unavailable",
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


def test_padded_duplicate_is_ignored_and_clean_claim_still_unverifiable():
    """Owner decision superseding D3: free-form verification strings are not authority (no VCC-117 receipt
    schema/verifier exists), so a well-formed claim stays unresolved as verifier_unavailable."""
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})
    clean = {**VALID_EDGE, "source_key": ref.source_key}
    padded = {**clean, "target_source_key": "base-X/table-Y/record-Z "}

    result = resolve_edge(ref, [clean, padded])

    assert result["mapping_status"] == "unresolved"
    assert result["mapping_reason"] == "verifier_unavailable"
    assert result["target_source_key"] is None


@pytest.mark.parametrize("registry", [
    "base-A/table-B/r1", b"base-A/table-B/r1", 7, object(),
    {"base-A/table-B/r1": {**VALID_EDGE, "source_key": "base-A/table-B/r1"}},
])
def test_non_sequence_registry_fails_instead_of_reporting_absent(registry):
    ref = SourceRef.from_entity({"base_token": "base-A", "table_id": "table-B", "record_id": "r1"})

    with pytest.raises(TypeError):
        resolve_edge(ref, registry)


# Typed native edges (D1-D8). Records mimic native Lark rows: links hold record ids only.
B = "base-A"
CONTRACT_FIELD = "所屬成案確認單（日報關聯）"
ITEM_FIELD = "來源合約明細（日報關聯）"


def row(kind, table, record_id, **fields):
    return {"kind": kind, "base_token": B, "table_id": table, "record_id": record_id, "fields": fields}


def ref(table, record_id, version=None):
    return SourceRef.from_entity({"base_token": B, "table_id": table, "record_id": record_id},
                                 version=version)


CONTRACT_TO_CONFIRMATION = EdgeType("contract_confirmation", "contract", CONTRACT_FIELD,
                                    {"confirmation"}, "child_to_parent", "many")
ITEM_TO_CONTRACT = EdgeType("item_contract", "reporting", ITEM_FIELD, {"contract"},
                            "child_to_parent", "many")
CONFIRMATION_TO_QUOTE = EdgeType("confirmation_quote", "confirmation", "所屬案件", {"quote"},
                                 "child_to_parent", "one")
DAILY_TO_COST = EdgeType("daily_cost", "daily", "所屬成本單", {"cost"}, "child_to_parent", "one")
DAILY_TO_CASE = EdgeType("daily_case", "daily", "所屬案件", {"confirmation"}, "child_to_parent", "one")


def chain_records():
    return [
        row("quote", "tblQ", "recQ1"),
        row("confirmation", "tblC", "recC1", 所屬案件=["recQ1"], 工程確認單編號="C115001", name="same"),
        row("confirmation", "tblC", "recC2", 工程確認單編號="C115001", name="same"),
        row("contract", "tblL", "recL1", **{CONTRACT_FIELD: [{"record_ids": ["recC1"]}]}),
        row("contract", "tblL", "recL2", **{CONTRACT_FIELD: ["recC1", "recC2"]}),
        row("reporting", "tblW", "recW1", **{ITEM_FIELD: ["recL1"]}),
        row("reporting", "tblW", "recW2", **{ITEM_FIELD: ["recL1", "recL2"]}),
        row("reporting", "tblW", "recW3", **{ITEM_FIELD: ["recL1", "recMISSING"]}),
    ]


def chain_graph(**kwargs):
    return build_native_edge_graph(
        chain_records(), [CONTRACT_TO_CONFIRMATION, ITEM_TO_CONTRACT, CONFIRMATION_TO_QUOTE], **kwargs)


def test_native_edges_reuse_existing_native_resolver():
    assert source_identity.native_records is v4_sources.native_records


def test_several_edge_types_on_one_record_do_not_conflict():
    records = [
        row("confirmation", "tblC", "recC1"),
        row("cost", "tblK", "recK1"),
        row("daily", "tblD", "recD1", 所屬案件=["recC1"], 所屬成本單=["recK1"]),
    ]
    graph = build_native_edge_graph(records, [DAILY_TO_CASE, DAILY_TO_COST])
    daily = ref("tblD", "recD1")

    case, cost = edge_targets(graph, daily, "daily_case"), edge_targets(graph, daily, "daily_cost")

    assert (case["navigation"], case["target_keys"]) == ("linked", ("base-A/tblC/recC1",))
    assert (cost["navigation"], cost["target_keys"]) == ("linked", ("base-A/tblK/recK1",))


def test_one_to_many_and_many_to_many_return_all_targets():
    graph = chain_graph()

    assert edge_targets(graph, ref("tblW", "recW2"), "item_contract")["target_keys"] == (
        "base-A/tblL/recL1", "base-A/tblL/recL2")
    assert edge_targets(graph, ref("tblL", "recL2"), "contract_confirmation")["target_keys"] == (
        "base-A/tblC/recC1", "base-A/tblC/recC2")
    assert edge_sources(graph, ref("tblC", "recC1"), "contract_confirmation") == (
        ("base-A", "tblL", "recL1", None), ("base-A", "tblL", "recL2", None))
    assert edge_sources(graph, ref("tblL", "recL1"), "item_contract") == tuple(
        ("base-A", "tblW", rid, None) for rid in ("recW1", "recW2", "recW3"))


def test_forward_and_reverse_navigation_agree_by_construction():
    graph = chain_graph()
    linked = [i for i in graph.instances if i["navigation"] == "linked"]
    assert len(linked) == 8
    refs = {i["source_key"] for i in graph.instances} | {i["target_key"] for i in linked}
    by_key = {key: SourceRef.from_entity(dict(zip(("base_token", "table_id", "record_id"), key.split("/"))))
              for key in refs}

    for key, node in by_key.items():
        for edge_type, child, _ in children_of(graph, node):
            assert (edge_type, key) in {(e, p) for e, p, _ in parents_of(graph, by_key[child])}
        for edge_type, parent, _ in parents_of(graph, node):
            assert (edge_type, key) in {(e, c) for e, c, _ in children_of(graph, by_key[parent])}
    for instance in linked:
        target = by_key[instance["target_key"]]
        assert instance["source_version_key"] in edge_sources(graph, target, instance["edge_type"])

    assert [c for _, c, _ in children_of(graph, ref("tblC", "recC1"))] == [
        "base-A/tblL/recL1", "base-A/tblL/recL2"]
    assert [p for _, p, _ in parents_of(graph, ref("tblL", "recL2"))] == [
        "base-A/tblC/recC1", "base-A/tblC/recC2"]
    assert [p for _, p, _ in parents_of(graph, ref("tblC", "recC1"))] == ["base-A/tblQ/recQ1"]


def test_missing_native_target_stays_an_explicit_unresolved_row():
    graph = chain_graph()

    result = edge_targets(graph, ref("tblW", "recW3"), "item_contract")

    assert result["navigation"] == "partial"
    assert result["target_keys"] == ("base-A/tblL/recL1",)
    assert [(u["reason"], u["target_key"], u["target_record_id"]) for u in result["unresolved"]] == [
        ("native_target_unresolved", None, "recMISSING")]
    assert any(i["target_record_id"] == "recMISSING" and i["navigation"] == "unresolved"
               for i in graph.instances)


def test_one_cardinality_ambiguous_contested_and_unresolved():
    records = [
        row("quote", "tblQ", "recQ1"), row("quote", "tblQ", "recQ2"),
        row("confirmation", "tblC", "recC1", 所屬案件=["recQ1", "recQ2"]),
        row("confirmation", "tblC", "recC2", 所屬案件=["recQ1", "recGONE"]),
        row("confirmation", "tblC", "recC3", 所屬案件=["recGONE"]),
        row("confirmation", "tblC", "recC4"),
    ]
    graph = build_native_edge_graph(records, [CONFIRMATION_TO_QUOTE])
    result = {rid: edge_targets(graph, ref("tblC", rid), "confirmation_quote")
              for rid in ("recC1", "recC2", "recC3", "recC4")}

    assert (result["recC1"]["navigation"], result["recC1"]["target_keys"],
            result["recC1"]["candidate_keys"]) == (
        "ambiguous", (), ("base-A/tblQ/recQ1", "base-A/tblQ/recQ2"))
    assert (result["recC2"]["navigation"], result["recC2"]["contested"],
            result["recC2"]["target_keys"]) == ("contested", True, ("base-A/tblQ/recQ1",))
    assert (result["recC3"]["navigation"], result["recC3"]["reason"]) == (
        "unresolved", "native_target_unresolved")
    assert (result["recC4"]["navigation"], result["recC4"]["reason"]) == ("unresolved", "no_native_link")


def test_every_edge_instance_and_type_is_receipt_missing():
    """Owner decision superseding D3: no receipt schema/verifier exists, so nothing is ever accepted."""
    graph = chain_graph()
    item = ref("tblW", "recW1")

    assert {i["verification"] for i in graph.instances} == {"receipt_missing"}
    assert {i["receipt_ref"] for i in graph.instances} == {None}
    for edge_type in graph.edge_types:
        result = edge_targets(graph, item, edge_type)
        assert (result["verification"], result["receipt_ref"]) == ("receipt_missing", None)
    assert {v for _, _, v in parents_of(graph, item)} <= {"receipt_missing"}
    assert {v for _, _, v in children_of(graph, ref("tblL", "recL1"))} <= {"receipt_missing"}


@pytest.mark.parametrize("receipts", [
    {"item_contract": "receipt-ref-opaque"}, {"item_contract": "x"}, {}, None, "item_contract",
])
def test_receipts_acceptance_path_is_removed(receipts):
    """Owner decision superseding D3: a caller string must not be able to mark an edge accepted."""
    with pytest.raises(TypeError):
        chain_graph(receipts=receipts)
    assert not hasattr(chain_graph(), "receipts")


@pytest.mark.parametrize("text", [
    "accepted", "mapped", "verified", "resolved", "receipt-123", "VCC-117", "independently_verified", " x ", "1",
])
def test_no_input_string_can_yield_accepted_mapped_or_resolved(text):
    """Owner decision superseding D3: whatever strings a caller supplies, nothing is accepted/mapped/resolved."""
    key = ref("tblW", "recW1").source_key
    edge = {"source_key": key, "target_source_key": "base-X/table-Y/record-Z",
            "verification_status": text, "verified_by": text, "evidence_ref": text, "receipt_ref": text,
            "mapping_status": "resolved", "verification": "accepted"}
    legacy = resolve_edge(ref("tblW", "recW1"), [edge, {**edge, "verification_status": "independently_verified"}])
    assert legacy["mapping_status"] == "unresolved" and legacy["target_source_key"] is None

    records = [{**r, "fields": {**r["fields"], "receipt": text, "verification": text}} for r in chain_records()]
    records = [{**r, "verification": "accepted", "receipt_ref": text} for r in records]
    graph = build_native_edge_graph(
        records, [CONTRACT_TO_CONFIRMATION, ITEM_TO_CONTRACT, CONFIRMATION_TO_QUOTE])
    assert {i["verification"] for i in graph.instances} == {"receipt_missing"}
    assert {i["receipt_ref"] for i in graph.instances} == {None}


def test_native_navigation_still_works_while_receipt_missing():
    graph = chain_graph()
    forward = edge_targets(graph, ref("tblW", "recW2"), "item_contract")
    assert (forward["navigation"], forward["verification"]) == ("linked", "receipt_missing")
    assert forward["target_keys"] == (f"{B}/tblL/recL1", f"{B}/tblL/recL2")
    assert edge_sources(graph, ref("tblL", "recL1"), "item_contract") == tuple(sorted(
        (ref("tblW", r).version_key for r in ("recW1", "recW2", "recW3")), key=repr))


def test_two_versions_of_one_record_stay_distinct():
    v1, v2 = ref("tblW", "recW1", version=1), ref("tblW", "recW1", version=2)
    graph_v1 = chain_graph(version=1)
    graph_v2 = chain_graph(version=2)

    assert v1.source_key == v2.source_key and v1.version_key != v2.version_key
    assert len({v1.version_key, v2.version_key}) == 2
    assert edge_targets(graph_v1, v1, "item_contract")["navigation"] == "linked"
    assert edge_targets(graph_v1, v2, "item_contract")["reason"] == "version_not_in_graph"
    assert children_of(graph_v1, v2) == parents_of(graph_v1, v2) == ()
    assert {i["source_version_key"] for i in graph_v1.instances}.isdisjoint(
        {i["source_version_key"] for i in graph_v2.instances})


def test_slash_component_is_rejected_not_joined():
    records = [
        row("contract", "tblL", "recL1"),
        {**row("contract", "tblL/x", "recL2"), "table_id": "tblL/x"},
        {**row("reporting", "tblW", "recW1", **{ITEM_FIELD: ["recL2"]})},
        {**row("reporting", "tblW", "recW2", **{ITEM_FIELD: ["recL1"]}), "base_token": "base-A/tblW"},
    ]
    graph = build_native_edge_graph(records, [ITEM_TO_CONTRACT])

    assert [(r["reason"], r["base_token"]) for r in graph.rejected] == [("invalid_source_key", "base-A/tblW")]
    result = edge_targets(graph, ref("tblW", "recW1"), "item_contract")
    assert result["navigation"] == "unresolved"
    assert result["reason"] == "invalid_target_key"
    assert not any("/x/" in (i["target_key"] or "") or i["source_key"].count("/") != 2
                   for i in graph.instances)


def test_field_id_edge_uses_schema_and_unlocated_schema_is_unresolved():
    by_id = EdgeType("item_contract_fid", "reporting", ITEM_FIELD, {"contract"},
                     "child_to_parent", "many", source_table="tblW", field_id="fldItem")
    records = chain_records()
    schema = [{"base_token": B, "table_id": "tblW", "field_schema": [
        {"field_id": "fldItem", "field_name": ITEM_FIELD, "property": {"table_id": "tblL"}}]}]
    renamed = [{**schema[0], "field_schema": [{"field_id": "fldItem", "field_name": "other"}]}]
    item = ref("tblW", "recW2")

    linked = edge_targets(build_native_edge_graph(records, [by_id], tables=schema), item, "item_contract_fid")
    unlocated = edge_targets(build_native_edge_graph(records, [by_id]), item, "item_contract_fid")
    mismatch = edge_targets(build_native_edge_graph(records, [by_id], tables=renamed), item, "item_contract_fid")

    assert linked["target_keys"] == ("base-A/tblL/recL1", "base-A/tblL/recL2")
    assert (unlocated["navigation"], unlocated["reason"]) == ("unresolved", "field_schema_unlocated")
    assert (mismatch["navigation"], mismatch["reason"]) == ("unresolved", "field_schema_mismatch")


def test_names_and_case_numbers_create_no_edge_or_identity():
    graph = chain_graph()
    c1, c2 = ref("tblC", "recC1"), ref("tblC", "recC2")
    assignments = {source_id({"base_token": B, "table_id": "tblC", "record_id": "recC1"}): "project-1"}

    assert edge_targets(graph, c2, "confirmation_quote")["reason"] == "no_native_link"
    assert stable_identity(c1, assignments) == {
        "source_key": "base-A/tblC/recC1", "stable_id": "project-1",
        "provenance": "assignment", "reason": None}
    assert stable_identity(c2, assignments) == {
        "source_key": "base-A/tblC/recC2", "stable_id": None, "provenance": None,
        "reason": "assignment_absent"}


@pytest.mark.parametrize("assignments,expected", [
    ({}, "assignment_absent"),
    ({source_id({"base_token": B, "table_id": "tblC", "record_id": "recC1"}): " "}, "assignment_invalid"),
    ({"base-A/tblC/recC1": "project-1"}, "assignment_absent"),
    ({"recC1": "project-1"}, "assignment_absent"),
])
def test_stable_identity_only_through_assignment_source_id(assignments, expected):
    assert stable_identity(ref("tblC", "recC1"), assignments)["reason"] == expected


@pytest.mark.parametrize("assignments", [None, [], "x", 7])
def test_stable_identity_rejects_non_mapping_assignments(assignments):
    with pytest.raises(TypeError):
        stable_identity(ref("tblC", "recC1"), assignments)


@pytest.mark.parametrize("kwargs,error", [
    ({"direction": "up"}, ValueError), ({"cardinality": "few"}, ValueError),
    ({"target_kinds": "contract"}, TypeError), ({"target_kinds": set()}, ValueError),
    ({"target_kinds": {" contract"}}, ValueError), ({"edge_type": ""}, ValueError),
    ({"source_field": " x"}, ValueError), ({"field_id": "fld/x"}, ValueError),
    ({"source_table": ""}, ValueError),
])
def test_edge_type_declaration_is_validated(kwargs, error):
    fields = dict(edge_type="t", source_kind="reporting", source_field=ITEM_FIELD,
                  target_kinds={"contract"}, direction="child_to_parent", cardinality="many")
    with pytest.raises(error):
        EdgeType(**{**fields, **kwargs})


def test_graph_inputs_fail_loudly():
    with pytest.raises(ValueError):
        build_native_edge_graph([], [ITEM_TO_CONTRACT, ITEM_TO_CONTRACT])
    with pytest.raises(TypeError):
        build_native_edge_graph({"recW1": chain_records()[0]}, [ITEM_TO_CONTRACT])
    with pytest.raises(TypeError):
        build_native_edge_graph(chain_records(), {"item_contract": ITEM_TO_CONTRACT})
    with pytest.raises(TypeError):
        build_native_edge_graph(["row"], [ITEM_TO_CONTRACT])
    with pytest.raises(ValueError):
        edge_targets(chain_graph(), ref("tblW", "recW1"), "undeclared")


def test_parent_to_child_direction_navigates_the_same_way():
    child_items = EdgeType("contract_items", "contract", "items", {"reporting"}, "parent_to_child", "many")
    records = [row("reporting", "tblW", "recW1"), row("reporting", "tblW", "recW2"),
               row("contract", "tblL", "recL1", items=["recW1", "recW2"])]
    graph = build_native_edge_graph(records, [child_items], version=3)

    assert [c for _, c, _ in children_of(graph, ref("tblL", "recL1", 3))] == [
        "base-A/tblW/recW1", "base-A/tblW/recW2"]
    assert parents_of(graph, ref("tblW", "recW2", 3)) == (
        ("contract_items", "base-A/tblL/recL1", "receipt_missing"),)
    assert children_of(graph, ref("tblW", "recW2", 3)) == ()


@pytest.mark.parametrize("version", [True, "", " 1", 1.5])
def test_graph_version_is_validated(version):
    with pytest.raises(ValueError):
        chain_graph(version=version)


CLAIMS = ["accepted", "mapped", "resolved", "verified"]


def _all_lookups(graph):
    seen = []
    for rf in (ref("tblW", "recW1"), ref("tblL", "recL1"), ref("tblC", "recC1"), ref("tblW", "recW3")):
        seen += [v for _, _, v in parents_of(graph, rf) + children_of(graph, rf)]
        for edge_type in graph.edge_types:
            result = edge_targets(graph, rf, edge_type)
            seen.append(result["verification"])
            seen += [row["verification"] for row in result["unresolved"]]
    return seen


@pytest.mark.parametrize("claim", CLAIMS)
def test_mutating_returned_graph_rows_cannot_promote_lookups(claim):
    graph = chain_graph()
    for container in (graph.instances, *graph.forward.values(), *graph.reverse.values()):
        for instance in container:
            try:
                instance["verification"] = claim
                instance["receipt_ref"] = f"VCC-117-{claim}"
            except TypeError:
                pass  # immutable rows: the write raises
    assert parents_of(graph, ref("tblW", "recW1")) == (
        ("item_contract", "base-A/tblL/recL1", "receipt_missing"),)
    assert ("item_contract", "base-A/tblW/recW1", "receipt_missing") in children_of(graph, ref("tblL", "recL1"))
    assert set(_all_lookups(graph)) == {"receipt_missing"}
    for container in (graph.instances, *graph.forward.values(), *graph.reverse.values()):
        assert {i["verification"] for i in container} == {"receipt_missing"}
        assert {i["receipt_ref"] for i in container} == {None}


@pytest.mark.parametrize("field", ["verification", "receipt_ref", "mapping_status", "x"])
def test_graph_state_is_immutable(field):
    graph = chain_graph()
    for action in (lambda: graph.instances[0].__setitem__(field, "accepted"),
                   lambda: setattr(graph.instances[0], field, "accepted"),
                   lambda: setattr(graph, "instances", ()),
                   lambda: graph.forward.__setitem__("k", ()),
                   lambda: graph.reverse.__setitem__("k", ()),
                   lambda: graph.edge_types.__setitem__("k", None),
                   lambda: graph.instances.append(1)):
        with pytest.raises((TypeError, AttributeError)):
            action()
    assert field not in ("mapping_status", "x") or field not in graph.instances[0]


@pytest.mark.parametrize("field,claim", [("mapping_status", "resolved"),
                                         ("verification_status", "independently_verified")])
def test_direct_rows_with_caller_fields_emit_only_declared_schema(field, claim):
    built = chain_graph()
    graph = source_identity.NativeEdgeGraph(
        built.edge_types, built.version, [{**r, field: claim} for r in built.instances], (), {}, {})
    assert all(field not in row for row in graph.instances)
    result = edge_targets(graph, ref("tblW", "recW3"), "item_contract")
    assert result["unresolved"] and all(field not in row for row in result["unresolved"])
    assert {row["verification"] for row in result["unresolved"]} == {"receipt_missing"}


def test_lookup_output_rows_are_detached_copies():
    graph = chain_graph()
    first = edge_targets(graph, ref("tblW", "recW3"), "item_contract")
    first["unresolved"][0]["verification"] = "accepted"
    first["unresolved"][0]["mapping_status"] = "resolved"
    again = edge_targets(graph, ref("tblW", "recW3"), "item_contract")
    assert again["unresolved"][0]["verification"] == "receipt_missing"
    assert "mapping_status" not in again["unresolved"][0]


@pytest.mark.parametrize("bad", [["bad"], {"a": 1}])
@pytest.mark.parametrize("component", ["table_id", "base_token", "record_id"])
def test_malformed_native_target_is_unresolved_and_does_not_abort_graph(component, bad):
    rows = chain_records()
    rows[3] = {**rows[3], component: bad}  # linked contract recL1
    graph = build_native_edge_graph(rows, [ITEM_TO_CONTRACT])
    result = edge_targets(graph, ref("tblW", "recW1"), "item_contract")
    assert result["navigation"] == "unresolved"
    assert result["unresolved"][0]["reason"] in ("invalid_target_key", "native_target_unresolved")
    assert edge_targets(graph, ref("tblW", "recW2"), "item_contract")["target_keys"] == ("base-A/tblL/recL2",)
    if component == "table_id":
        assert result["unresolved"][0]["target_table_id"] == bad
        assert edge_targets(graph, ref("tblW", "recW3"), "item_contract")["navigation"] == "unresolved"


def _row(graph, key):
    return next(r for r in graph.instances if r["source_key"] == key)


@pytest.mark.parametrize("change", [
    {"navigation": "unresolved"},                       # unresolved but keeps a target
    {"navigation": "linked", "target_key": None},
    {"navigation": "linked", "target_key": "not-a-key"},
    {"navigation": "linked", "target_key": "a/b"},
    {"navigation": "unresolved", "target_key": "base-A/tblL/recL1"},
    {"source_key": "base-A/tblW"},
    {"source_key": "base-A/tblW/recZZ"},                # disagrees with source_version_key
    {"source_version_key": ("base-A", "tblW", "recW1", 9)},
    {"source_version_key": "base-A/tblW/recW1"},
    {"reason": 5},
])
def test_direct_construction_rejects_contradictory_rows(change):
    built = chain_graph()
    row = {**_row(built, "base-A/tblW/recW1"), **change}
    with pytest.raises(ValueError):
        source_identity.NativeEdgeGraph(built.edge_types, built.version, [row], (), {}, {})


def test_reverse_index_only_from_linked_instances():
    graph = chain_graph()
    assert all(i["navigation"] == "linked" for rows in graph.reverse.values() for i in rows)
    assert edge_sources(graph, ref("tblW", "recW3"), "item_contract") == ()


def test_direct_construction_dedups_and_accepts_dict_rows_with_claims():
    built = chain_graph()
    rows = [{**r, "verification": "accepted"} for r in built.instances] * 2
    graph = source_identity.NativeEdgeGraph(built.edge_types, built.version, rows, (), {}, {})
    assert len(graph.instances) == len(built.instances)
    assert {i["verification"] for i in graph.instances} == {"receipt_missing"}


@pytest.mark.parametrize("claim", CLAIMS)
def test_direct_graph_construction_cannot_inject_accepted_state(claim):
    built = chain_graph()
    forged = [{**row, "verification": claim, "receipt_ref": "VCC-117-free-form"} for row in built.instances]
    graph = source_identity.NativeEdgeGraph(
        built.edge_types, built.version, forged, built.rejected,
        {k: tuple(dict(r, verification=claim) for r in v) for k, v in built.forward.items()},
        {k: tuple(dict(r, verification=claim) for r in v) for k, v in built.reverse.items()})
    assert set(_all_lookups(graph)) == {"receipt_missing"}
    assert {row["verification"] for row in graph.instances} == {"receipt_missing"}
    assert {row["receipt_ref"] for row in graph.instances} == {None}


@pytest.mark.parametrize("instances", [[{"edge_type": "item_contract"}], ["x"],
                                       [{"edge_type": "nope", "source_key": "a", "source_version_key": "a",
                                         "navigation": "unresolved", "target_key": None}]])
def test_direct_graph_construction_validates_instances(instances):
    with pytest.raises((TypeError, ValueError)):
        source_identity.NativeEdgeGraph({"item_contract": ITEM_TO_CONTRACT}, None, instances, (), {}, {})


@pytest.mark.parametrize("component", ["base_token", "table_id", "record_id"])
@pytest.mark.parametrize("bad", [["bad"], {"a": 1}, 5])
def test_non_string_identity_component_is_rejected_not_hashed(component, bad):
    rows = chain_records()
    rows[-1] = {**rows[-1], component: bad}
    graph = build_native_edge_graph(rows, [ITEM_TO_CONTRACT])
    assert graph.rejected == ({"edge_type": "item_contract", "reason": "invalid_source_key",
                               "base_token": rows[-1]["base_token"], "table_id": rows[-1]["table_id"],
                               "record_id": rows[-1]["record_id"]},)
    assert all(row["source_key"] != "base-A/tblW/recW3" for row in graph.instances)


# C-ID residuals N1 (equal-but-noncanonical version components) and N2 (malformed raw native links).
@pytest.mark.parametrize("version,bad", [(1, True), (1, 1.0), (0, False), (0, 0.0), ("1", 1), (1, "1")])
def test_direct_instance_rejects_equal_but_type_mismatched_version_component(version, bad):
    built = chain_graph(version=version)
    forged = dict(built.instances[0])
    forged["source_version_key"] = (*forged["source_version_key"][:3], bad)
    with pytest.raises(ValueError, match="source_version_key"):
        source_identity.NativeEdgeGraph(built.edge_types, version, [forged], (), {}, {})
    with pytest.raises(ValueError, match="source_version_key"):
        source_identity.EdgeInstance.from_row(forged, version)


def test_direct_instance_with_canonical_key_keeps_exact_types():
    built = chain_graph(version=1)
    graph = source_identity.NativeEdgeGraph(built.edge_types, 1, [dict(r) for r in built.instances], (), {}, {})
    key = graph.instances[0]["source_version_key"]
    assert key == built.instances[0]["source_version_key"]
    assert [type(c) for c in key] == [str, str, str, int]


@pytest.mark.parametrize("shape,bad", [("table_id", b) for b in (["bad"], {"a": 1}, 5, [5])]
                         + [(k, b) for k in ("record_id", "record_ids", "link_record_ids")
                            for b in ({"a": 1}, 5, [5])])
def test_malformed_raw_native_link_is_explicit_unresolved_and_isolated(shape, bad):
    records = chain_records()
    if shape == "table_id":
        malformed = {"record_id": "recL1", "table_id": bad}
    else:
        malformed = {shape: bad, "table_id": "tblL"}
    records[5]["fields"][ITEM_FIELD] = ["recL2", malformed]  # recL2 is a valid sibling link
    graph = build_native_edge_graph(records, [ITEM_TO_CONTRACT])
    mine = [r for r in graph.instances if r["source_key"] == "base-A/tblW/recW1"]
    reasons = sorted(r["reason"] for r in mine)
    assert reasons == ["malformed_native_link", "native_link"]
    assert {r["target_key"] for r in mine} == {None, "base-A/tblL/recL2"}
    bad_row = next(r for r in mine if r["reason"] == "malformed_native_link")
    assert bad_row["navigation"] == "unresolved" and bad_row["verification"] == "receipt_missing"
    # other sources in the same graph still resolve, and nothing was guessed for the bad item
    other = [r for r in graph.instances if r["source_key"] == "base-A/tblW/recW2"]
    assert {r["target_key"] for r in other} == {"base-A/tblL/recL1", "base-A/tblL/recL2"}
    assert all(r["verification"] == "receipt_missing" for r in graph.instances)


def test_malformed_bare_scalar_link_value_is_flagged_not_dropped():
    records = chain_records()
    records[5]["fields"][ITEM_FIELD] = 5
    graph = build_native_edge_graph(records, [ITEM_TO_CONTRACT])
    mine = [r for r in graph.instances if r["source_key"] == "base-A/tblW/recW1"]
    assert [r["reason"] for r in mine] == ["malformed_native_link"]


def test_valid_absent_native_target_keeps_unresolved_semantics():
    graph = chain_graph()
    missing = [r for r in graph.instances
               if r["source_key"] == "base-A/tblW/recW3" and r["navigation"] == "unresolved"]
    assert [(r["reason"], r["target_record_id"]) for r in missing] == [("native_target_unresolved", "recMISSING")]
