"""V4 人員名單, limited to the five approved columns.

Used only to decide who may act on a node and whom a manager may assign. It is
never persisted and never merged into the workspace people directory.
"""
from collections import Counter
from dataclasses import dataclass

from ..sources import text
from .domain import NODE_DEPARTMENTS, NodeKey, Person
from .errors import Failure
from .lark_table import PEOPLE_FIELDS, BitableClient, Table, canon, check_schema, users

FIELD_NAMES = [name for name, _ in PEOPLE_FIELDS.values()]


@dataclass(frozen=True)
class Roster:
    people: dict[str, Person]
    ambiguous: frozenset[str]

    def person(self, open_id) -> Person | None:
        return self.people.get(open_id)

    def assignable(self, key: NodeKey) -> list[Person]:
        return sorted((p for p in self.people.values() if p.member_of(key)), key=lambda p: (p.name, p.open_id))

    def public(self, person: Person, key: NodeKey):
        return {'open_id': person.open_id, 'name': person.name,
                'departments': [d for d in NODE_DEPARTMENTS[key] if d in person.departments]}


def parse_roster(records) -> Roster:
    people, counts = [], Counter()
    for record in records:
        values = record.get('fields')
        if not isinstance(values, dict) or not set(values) <= set(FIELD_NAMES):
            raise Failure('lark_error', '人員名單回應包含未要求的欄位，停止處理')
        accounts = users(values.get(PEOPLE_FIELDS['account'][0]))
        if len(accounts) != 1:
            continue
        account = accounts[0]
        counts[account.open_id] += 1
        rank = text(values.get(PEOPLE_FIELDS['rank'][0])).strip() or None
        people.append(Person(account.open_id, text(values.get(PEOPLE_FIELDS['name'][0])).strip() or account.name,
                             frozenset(canon(PEOPLE_FIELDS['departments'][1], values.get(PEOPLE_FIELDS['departments'][0]))),
                             rank, values.get(PEOPLE_FIELDS['employed'][0]) is True))
    # One Lark account on two roster rows could grant either row's rank; trust neither.
    ambiguous = frozenset(ident for ident, count in counts.items() if count > 1)
    return Roster({p.open_id: p for p in people if p.open_id not in ambiguous}, ambiguous)


def fetch_roster(client: BitableClient) -> Roster:
    check_schema(client, Table.PEOPLE)
    return parse_roster(client.list_records(Table.PEOPLE, FIELD_NAMES))
