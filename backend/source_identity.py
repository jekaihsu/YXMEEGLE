"""Stable source identity references and typed native edges (C-ID).

This module deliberately does not infer identity from display names, case
numbers, or suffixes.  Two edge sources exist:

* ``resolve_edge`` is the legacy record-key lookup over a caller-supplied
  registry.  It never returns ``resolved``: free-form verification strings are
  not authority, so a well-formed claim is ``verifier_unavailable``.
* ``build_native_edge_graph`` derives typed edge instances from the native
  Lark links already resolved by ``v4_sources.native_records``.  An edge type is
  declared once (``EdgeType``); instances are keyed by (source, edge type), so
  several edge types on one record never conflict.  A missing native target is
  kept as an explicit unresolved row.  Reverse navigation is built from the
  same forward instances, so parent->child and child->parent agree.

Unresolved gates (owner decision; nothing below is decided or invented here):

* VCC-117 receipts are absent.  The receipt schema and verifier authority are
  unresolved, and no trustworthy read-only source evidence for them exists.  No
  caller-supplied string is treated as a receipt or as enough to mark an edge
  accepted, mapped or verified.  Every edge instance and edge type is
  therefore ``receipt_missing`` (navigable by native edge id, never mapped or
  accepted), and ``resolve_edge`` reports ``verifier_unavailable``.
* Lark token encoding is unresolved.  Keys are the existing slash-joined
  ``entity_id``; ``SourceRef`` rejects a component that is empty, padded or
  contains '/' (D8), so a would-be collision is an explicit unresolvable ref.
  Whether real Lark tokens can contain '/' and how to encode them is unverified.

Permission boundary: nothing here takes a viewer or reports ``forbidden``.
Callers must apply ``production_access``/``source_case_policy``/
``case_redaction`` and redact target keys, native record ids and reasons
before any output.  Stable business identity is only the existing
``project_id`` reached through the import ``assignments`` mapping.
"""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

from .source_entities import entity_id
from .sources import source_id
from .v4_sources import native_records


def _key_component(value):
    """A key part is a non-empty str with no '/' and no surrounding whitespace."""
    return isinstance(value, str) and bool(value) and value == value.strip() and "/" not in value


def is_source_key(value):
    """True for an exact ``base/table/record`` key whose three parts are clean."""
    if not isinstance(value, str):
        return False
    parts = value.split("/")
    return len(parts) == 3 and all(_key_component(part) for part in parts)


def _valid_version(version):
    """A version is an int (not bool), a non-blank unpadded str, or None."""
    if isinstance(version, bool):
        return False
    return version is None or isinstance(version, int) or (
        isinstance(version, str) and bool(version) and version == version.strip())


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
        if not _valid_version(self.version):
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

    @property
    def version_key(self):
        """Version-qualified identity; two versions of one record never collapse."""
        return (self.base, self.table, self.record_id, self.version)


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
    endpoints.  No exact entry is ``edge_absent``; an exact entry that is
    malformed (status, verifier or evidence strings missing, or a bad target)
    is ``edge_unverified``; a well-formed claim is ``verifier_unavailable``
    because no verifier or receipt authority exists, so this never returns
    ``resolved``.  A target must itself be an exact, unpadded
    ``base/table/record`` key.  Display fields are never consulted,
    even if they happen to match.  A registry that is a mapping, string or
    scalar raises ``TypeError`` rather than reading as an absent edge.
    """
    well_formed_claims = 0
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
        well_formed_claims += 1

    if not well_formed_claims:
        return unresolved_row(
            source_ref, reason="edge_unverified" if exact_edge_present else "edge_absent"
        )
    return unresolved_row(source_ref, reason="verifier_unavailable")


EDGE_DIRECTIONS = ("parent_to_child", "child_to_parent")
EDGE_CARDINALITIES = ("one", "many")
RECEIPT_MISSING = "receipt_missing"


def _optional_component(value, name):
    if value is not None and not _key_component(value):
        raise ValueError(f"{name} must be None or a non-empty, unpadded str without '/'")


@dataclass(frozen=True)
class EdgeType:
    """One declared native edge: the source record's link field and its target.

    ``direction`` states whether the source record is the parent or the child.
    With ``field_id`` the field is located through the table's field schema (as
    ``source_work_items`` does) and must carry the declared ``source_field``.
    """

    edge_type: str
    source_kind: str
    source_field: str
    target_kinds: frozenset
    direction: str
    cardinality: str
    source_table: str | None = None
    field_id: str | None = None

    def __post_init__(self):
        for name in ("edge_type", "source_kind", "source_field"):
            value = getattr(self, name)
            if not (isinstance(value, str) and value and value == value.strip()):
                raise ValueError(f"{name} must be a non-blank, unpadded str")
        kinds = self.target_kinds
        if isinstance(kinds, (str, bytes, Mapping)) or not isinstance(kinds, Iterable):
            raise TypeError("target_kinds must be a collection of kinds")
        kinds = frozenset(kinds)
        if not kinds or not all(isinstance(kind, str) and kind and kind == kind.strip()
                                for kind in kinds):
            raise ValueError("target_kinds must be non-blank, unpadded kinds")
        object.__setattr__(self, "target_kinds", kinds)
        if self.direction not in EDGE_DIRECTIONS:
            raise ValueError(f"direction must be one of {EDGE_DIRECTIONS}")
        if self.cardinality not in EDGE_CARDINALITIES:
            raise ValueError(f"cardinality must be one of {EDGE_CARDINALITIES}")
        _optional_component(self.source_table, "source_table")
        _optional_component(self.field_id, "field_id")


class _FrozenRow(Mapping):
    """Read-only row holding exactly the declared ``FIELDS``; nothing else is stored or emitted.

    Values are copied on the way in and out, so neither the caller's original
    objects nor a returned value can change what the row holds.
    """

    __slots__ = ("_data",)
    FIELDS = ()

    def __init__(self, values):
        object.__setattr__(self, "_data", MappingProxyType({k: deepcopy(values[k]) for k in self.FIELDS}))

    def __setattr__(self, name, value):
        raise AttributeError(f"{type(self).__name__} is immutable")

    __delattr__ = __setattr__

    def __getitem__(self, key):
        if key not in self._data:
            raise KeyError(key)
        return deepcopy(self._data[key])

    def __iter__(self):
        return iter(self.FIELDS)

    def __len__(self):
        return len(self.FIELDS)

    def __repr__(self):
        return f"{type(self).__name__}({dict(self)!r})"

    def to_dict(self):
        """A fresh plain dict of the declared fields."""
        return {k: self[k] for k in self.FIELDS}


def _require_canonical_version_key(source_key, supplied, canonical=None):
    """Reject any source_version_key that is not exactly (base, table, record, version) for ``source_key``.

    ``canonical`` (the graph-snapshot key) is additionally enforced when known; ``version`` is exactly an int/str/None, so ``True``/``1.0`` never
    pass for ``1``, nor ``False``/``0.0`` for ``0``.
    """
    ok = (isinstance(supplied, tuple) and len(supplied) == 4 and is_source_key(source_key)
          and tuple(supplied[:3]) == tuple(source_key.split("/"))
          and all(type(c) is str for c in supplied[:3]) and type(supplied[3]) in (int, str, type(None)))
    if ok and canonical is not None:
        ok = supplied == canonical and all(type(a) is type(b) for a, b in zip(supplied, canonical))
    if not ok:
        raise ValueError("edge instance source_version_key must match source_key and the graph version")


class EdgeInstance(_FrozenRow):
    """One immutable edge instance exposing only the declared instance schema.

    ``verification`` and ``receipt_ref`` are not stored: they are produced from
    ``RECEIPT_MISSING`` on every read, so no input can set or change them.
    """

    __slots__ = ()
    STORED = ("edge_type", "source_key", "source_version_key", "navigation", "reason",
              "target_key", "target_table_id", "target_record_id")
    FIELDS = STORED + ("verification", "receipt_ref")

    def __init__(self, values):
        data = {k: deepcopy(values[k]) for k in self.STORED}
        _require_canonical_version_key(data["source_key"], data["source_version_key"])
        object.__setattr__(self, "_data", MappingProxyType(
            {**data,
             "verification": RECEIPT_MISSING, "receipt_ref": None}))

    @classmethod
    def from_row(cls, row, version):
        """Validate one caller row against the graph snapshot ``version``; extra fields are dropped."""
        if not isinstance(row, Mapping):
            raise TypeError("instances must contain edge instance mappings")
        missing = {"edge_type", "source_key", "source_version_key", "navigation", "target_key"} - set(row)
        if missing:
            raise ValueError(f"edge instance lacks {sorted(missing)}")
        navigation, target_key = row["navigation"], row["target_key"]
        if navigation not in ("linked", "unresolved"):
            raise ValueError("edge instance navigation must be linked or unresolved")
        if not (isinstance(row["edge_type"], str) and row["edge_type"]):
            raise ValueError("edge instance edge_type must be a non-empty str")
        if not is_source_key(row["source_key"]):
            raise ValueError("edge instance source_key must be a base/table/record key")
        base, table, record_id = row["source_key"].split("/")
        canonical_key = (base, table, record_id, version)
        _require_canonical_version_key(row["source_key"], row["source_version_key"], canonical_key)
        if navigation == "linked" and not is_source_key(target_key):
            raise ValueError("linked edge instance needs a base/table/record target_key")
        if navigation == "unresolved" and target_key is not None:
            raise ValueError("unresolved edge instance must have target_key None")
        reason = row.get("reason", "native_link" if navigation == "linked" else "native_target_unresolved")
        if not isinstance(reason, str):
            raise ValueError("edge instance reason must be a str")
        return cls({"edge_type": row["edge_type"], "source_key": row["source_key"],
                    "source_version_key": canonical_key, "navigation": navigation,
                    "reason": reason, "target_key": target_key,
                    "target_table_id": row.get("target_table_id"),
                    "target_record_id": row.get("target_record_id")})

    @property
    def identity(self):
        """Hashable identity; malformed diagnostics are compared by repr, never hashed raw."""
        d = self._data
        return tuple(repr(d[k]) if k.startswith("target_") and k != "target_key" else d[k]
                     for k in self.STORED)


class RejectedRow(_FrozenRow):
    """Immutable diagnostic for a source row whose identity could not form a safe key."""

    __slots__ = ()
    FIELDS = ("edge_type", "reason", "base_token", "table_id", "record_id")

    def __init__(self, values):
        super().__init__({k: values.get(k) for k in self.FIELDS})


@dataclass(frozen=True)
class NativeEdgeGraph:
    """Immutable edge instances of one record snapshot (``version``), with both indexes."""

    edge_types: Mapping
    version: int | str | None
    instances: tuple
    rejected: tuple
    forward: Mapping
    reverse: Mapping

    def __post_init__(self):
        """Validate and rebuild: rows become immutable ``EdgeInstance`` values, indexes are derived.

        Caller-supplied ``forward``/``reverse`` are ignored.  Contradictory rows
        (unresolved with a target, linked without a valid target, key/version
        mismatch, undeclared edge type) raise ``ValueError``.
        """
        if not isinstance(self.edge_types, Mapping) or not all(
                isinstance(k, str) and isinstance(v, EdgeType) for k, v in self.edge_types.items()):
            raise TypeError("edge_types must map names to EdgeType declarations")
        if not _valid_version(self.version):
            raise ValueError("version must be an integer, a non-blank unpadded string, or None")
        unique = {}
        for row in _sequence(self.instances, "instances"):
            instance = EdgeInstance.from_row(row, self.version)
            if instance["edge_type"] not in self.edge_types:
                raise ValueError(f"instance of undeclared edge type {instance['edge_type']!r}")
            unique.setdefault(instance.identity, instance)
        instances = tuple(unique.values())
        forward, reverse = _index_instances(instances)
        rejected = []
        for row in _sequence(self.rejected, "rejected"):
            if not isinstance(row, Mapping):
                raise TypeError("rejected must contain row mappings")
            rejected.append(RejectedRow(row))
        object.__setattr__(self, "edge_types", MappingProxyType(dict(self.edge_types)))
        object.__setattr__(self, "instances", instances)
        object.__setattr__(self, "rejected", tuple(rejected))
        object.__setattr__(self, "forward", forward)
        object.__setattr__(self, "reverse", reverse)


def _index_instances(instances):
    forward, reverse = {}, {}
    for instance in instances:
        forward.setdefault((instance["source_version_key"], instance["edge_type"]), []).append(instance)
        if instance["navigation"] == "linked":
            reverse.setdefault((instance["target_key"], instance["edge_type"]), []).append(instance)
    return (MappingProxyType({k: tuple(v) for k, v in forward.items()}),
            MappingProxyType({k: tuple(v) for k, v in reverse.items()}))


def _field_schemas(tables):
    schemas = {}
    for table in _sequence(tables, "tables"):
        if not isinstance(table, Mapping):
            raise TypeError("tables must contain table mappings")
        schemas[(table.get("base_token"), table.get("table_id"))] = {
            field["field_id"]: field for field in table.get("field_schema") or ()
            if isinstance(field, Mapping) and field.get("field_id")}
    return schemas


_LINK_KEYS = ("record_id", "record_ids", "link_record_ids")


def _clean_native_link(value, bad):
    """Mirror ``v4_sources.native_records.visit`` and return ``value`` minus malformed descendants.

    Every malformed descendant is appended to ``bad``; valid branches (and the table_id they inherit)
    are kept. A dict whose own ``table_id`` is malformed is dropped whole: no table is guessed for it.
    ``None`` under a link key is an absent optional collection, exactly as the native resolver sees it.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        kept = []
        for item in value:
            cleaned = _clean_native_link(item, bad)
            if cleaned is not _DROP:
                kept.append(cleaned)
        return kept
    if isinstance(value, dict):
        table = value.get("table_id")
        if table is not None and not isinstance(table, str):
            bad.append(value)
            return _DROP
        present = [k for k in _LINK_KEYS if value.get(k) is not None]
        if not present:
            bad.append(value)
            return _DROP
        kept = {} if table is None else {"table_id": table}
        for key in present:
            cleaned = _clean_native_link(value[key], bad)
            if cleaned is not _DROP:
                kept[key] = cleaned
        return kept
    bad.append(value)
    return _DROP


_DROP = object()


def _split_native_links(value):
    """Split a raw link value into (well-formed value, malformed items); nothing is guessed."""
    if value is None:
        return None, []
    bad = []
    clean = _clean_native_link(value, bad)
    return (None if clean is _DROP else clean), bad


def _malformed_link_row(item):
    table = item.get("table_id") if isinstance(item, dict) else None
    record = {k: item[k] for k in _LINK_KEYS if k in item} if isinstance(item, dict) else item
    return {"navigation": "unresolved", "reason": "malformed_native_link", "target_key": None,
            "target_table_id": table, "target_record_id": record}


def _native_links(row, edge, index, schemas):
    """Return (targets, missing, reason, malformed) from the existing native resolver."""
    fields = row.get("fields")
    field = edge.source_field
    if isinstance(fields, Mapping) and field in fields:
        clean, malformed = _split_native_links(fields[field])
        if malformed:
            row = {**row, "fields": {**fields, field: clean}}
    else:
        malformed = []
    targets, missing, reason = _resolve_native_links(row, edge, index, schemas)
    return targets, missing, reason, malformed


def _resolve_native_links(row, edge, index, schemas):
    if edge.field_id is None:
        targets, missing = native_records(row, edge.source_field, index, edge.target_kinds)
        return targets, missing, None
    schema = schemas.get((row["base_token"], row["table_id"]), {}).get(edge.field_id, {})
    name = schema.get("field_name")
    if not name:
        return [], [], "field_schema_unlocated"
    if name != edge.source_field:
        return [], [], "field_schema_mismatch"
    linked = {**row.get("linked_tables", {}), name: (schema.get("property") or {}).get("table_id")}
    targets, missing = native_records({**row, "linked_tables": linked}, name, index, edge.target_kinds)
    return targets, missing, None


def build_native_edge_graph(records, edge_types, *, tables=None, version=None):
    """Derive typed edge instances for one snapshot of native source records.

    Each instance row carries ``edge_type``, ``source_key``,
    ``source_version_key`` and either a ``target_key`` (``navigation="linked"``)
    or the native target reference with ``navigation="unresolved"`` and a
    reason.  ``verification`` is always ``receipt_missing`` and ``receipt_ref``
    is None: there is no receipt schema or verifier, and no input can change that.
    A source row whose identity cannot form a safe key is listed in ``rejected``.
    """
    if not _valid_version(version):
        raise ValueError("version must be an integer, a non-blank unpadded string, or None")
    declared = {}
    for edge in _sequence(edge_types, "edge_types"):
        if not isinstance(edge, EdgeType):
            raise TypeError("edge_types must contain EdgeType declarations")
        if edge.edge_type in declared:
            raise ValueError(f"edge type {edge.edge_type!r} is declared twice")
        declared[edge.edge_type] = edge
    schemas = _field_schemas(tables)
    rows = []
    for row in _sequence(records, "records"):
        if not isinstance(row, Mapping):
            raise TypeError("records must contain source record mappings")
        rows.append(row)
    index = {}
    for row in rows:
        base, record_id = row.get("base_token"), row.get("record_id")
        if isinstance(base, str) and isinstance(record_id, str):
            index.setdefault((base, record_id), []).append(row)  # others are rejected below, never hashed

    instances, rejected = [], []
    for row in rows:
        for edge in declared.values():
            if row.get("kind") != edge.source_kind:
                continue
            if edge.source_table is not None and row.get("table_id") != edge.source_table:
                continue
            try:
                ref = SourceRef.from_entity(row, version=version)
            except ValueError:
                rejected.append(RejectedRow({"edge_type": edge.edge_type, "reason": "invalid_source_key",
                                             **{k: row.get(k) for k in ("base_token", "table_id", "record_id")}}))
                continue
            common = {"edge_type": edge.edge_type, "source_key": ref.source_key,
                      "source_version_key": ref.version_key}
            targets, missing, schema_reason, malformed = _native_links(row, edge, index, schemas)
            found = []
            if schema_reason:
                found.append({"navigation": "unresolved", "reason": schema_reason,
                              "target_key": None, "target_table_id": None, "target_record_id": None})
            for target in targets:
                try:
                    target_key = SourceRef.from_entity(target).source_key
                except ValueError:
                    found.append({"navigation": "unresolved", "reason": "invalid_target_key",
                                  "target_key": None, "target_table_id": target.get("table_id"),
                                  "target_record_id": target.get("record_id")})
                    continue
                found.append({"navigation": "linked", "reason": "native_link", "target_key": target_key,
                              "target_table_id": target["table_id"], "target_record_id": target["record_id"]})
            found.extend(_malformed_link_row(item) for item in malformed)
            for item in missing:
                found.append({"navigation": "unresolved", "reason": "native_target_unresolved",
                              "target_key": None, "target_table_id": item.get("table_id"),
                              "target_record_id": item.get("record_id")})
            instances.extend({**common, **item} for item in found)

    return NativeEdgeGraph(declared, version, instances, rejected, {}, {})


def _declared(graph, edge_type):
    if edge_type not in graph.edge_types:
        raise ValueError(f"undeclared edge type {edge_type!r}")
    return graph.edge_types[edge_type]


def edge_targets(graph, source_ref, edge_type):
    """Navigate one edge type forward from one source record version.

    ``navigation`` is ``linked`` (all targets resolved), ``partial`` (a many
    edge with some unresolved targets), ``contested`` (a one edge with one
    resolved target and competing unresolved ones; ``contested`` is True),
    ``ambiguous`` (a one edge with several distinct resolved targets; no
    target is chosen) or ``unresolved``.  ``verification`` is independent of
    navigation and is always ``receipt_missing``.
    """
    edge = _declared(graph, edge_type)
    result = {"source_key": source_ref.source_key, "source_version_key": source_ref.version_key,
              "edge_type": edge_type, "cardinality": edge.cardinality, "direction": edge.direction,
              "verification": RECEIPT_MISSING, "receipt_ref": None, "contested": False,
              "target_keys": (), "candidate_keys": (), "unresolved": ()}
    if source_ref.version != graph.version:
        return {**result, "navigation": "unresolved", "reason": "version_not_in_graph"}
    rows = graph.forward.get((source_ref.version_key, edge_type), ())
    linked = tuple(sorted({row["target_key"] for row in rows if row["navigation"] == "linked"}))
    unresolved = tuple(row for row in rows if row["navigation"] == "unresolved")
    result["unresolved"] = tuple(row.to_dict() for row in unresolved)
    if not linked:
        reason = unresolved[0]["reason"] if unresolved else "no_native_link"
        return {**result, "navigation": "unresolved", "reason": reason}
    if edge.cardinality == "many":
        return {**result, "navigation": "partial" if unresolved else "linked",
                "reason": "native_link", "target_keys": linked}
    if len(linked) > 1:
        return {**result, "navigation": "ambiguous", "reason": "ambiguous_native_targets",
                "candidate_keys": linked}
    if unresolved:
        return {**result, "navigation": "contested", "reason": "competing_unresolved_targets",
                "contested": True, "target_keys": linked}
    return {**result, "navigation": "linked", "reason": "native_link", "target_keys": linked}


def edge_sources(graph, target_ref, edge_type):
    """Reverse one edge type: source version keys whose native link resolves to the target.

    Built from the same instances as ``edge_targets``, so the two agree.
    """
    _declared(graph, edge_type)
    if target_ref.version != graph.version:
        return ()
    return tuple(sorted({row["source_version_key"]
                         for row in graph.reverse.get((target_ref.source_key, edge_type), ())},
                        key=repr))


def _related(graph, ref, role):
    """Linked neighbours of ``ref`` in ``role`` ('children' or 'parents').

    Uses the same forward/reverse indexes as ``edge_targets``/``edge_sources``.
    """
    if ref.version != graph.version:
        return ()
    out = set()
    for edge_type, edge in graph.edge_types.items():
        if (role == "children") == (edge.direction == "parent_to_child"):
            out.update((edge_type, row["target_key"], RECEIPT_MISSING)
                       for row in graph.forward.get((ref.version_key, edge_type), ())
                       if row["navigation"] == "linked")
        else:
            out.update((edge_type, row["source_key"], RECEIPT_MISSING)
                       for row in graph.reverse.get((ref.source_key, edge_type), ()))
    return tuple(sorted(out))


def children_of(graph, parent_ref):
    """(edge_type, child_key, verification) for every linked edge where ``parent_ref`` is the parent."""
    return _related(graph, parent_ref, "children")


def parents_of(graph, child_ref):
    """(edge_type, parent_key, verification) for every linked edge where ``child_ref`` is the child."""
    return _related(graph, child_ref, "parents")


def stable_identity(source_ref, assignments):
    """The existing project id assigned to a source record, or explicitly unresolved.

    ``assignments`` is the import mapping ``sources.source_id -> project id``.
    No identity is issued here and nothing is grouped by name, case number or
    suffix.
    """
    if not isinstance(assignments, Mapping):
        raise TypeError(f"assignments must be a mapping, not {type(assignments).__name__}")
    project_id = assignments.get(source_id({"base_token": source_ref.base, "table_id": source_ref.table,
                                            "record_id": source_ref.record_id}))
    if isinstance(project_id, str) and project_id.strip():
        return {"source_key": source_ref.source_key, "stable_id": project_id,
                "provenance": "assignment", "reason": None}
    return {"source_key": source_ref.source_key, "stable_id": None, "provenance": None,
            "reason": "assignment_absent" if project_id is None else "assignment_invalid"}
