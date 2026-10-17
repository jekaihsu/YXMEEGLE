"""Public progress shapes. Raw source records never cross this boundary."""
from typing import TypedDict


class StatusCount(TypedDict):
    status: str
    count: int


class ProgressRow(TypedDict):
    case_key: str | None
    case_code: str
    case_name: str
    status: str
    link: str | None
    planned: float
    actual: float
    matched_points: float
    planned_days: int
    actual_days: int
    matched_days: int
    unplanned_days: int
    achievement: float | None
    diff: float
    expected_total: float | None
    done_total: float | None
    remaining: float | None


class PlanRow(TypedDict):
    date: str
    group: str
    people: str
    items: str
    points: float | None


class Checks(TypedDict):
    status: str
    control_checked: bool | None


class WorkRow(TypedDict):
    date: str
    group: str
    person: str
    item: str
    points: float | None
    checks: Checks
    flags: list[str]
    note: str


class Contract(TypedDict):
    expected: float | None
    actual: float | None


class Billing(TypedDict):
    billed: float | None
    receivable: float | None
    progress: float | None


class CaseFacts(TypedDict):
    code: str
    name: str
    client: str
    pm: str
    status: str
    contract: Contract
    billing: Billing
    revenue_progress: float | None
    cost_progress: float | None
    expected_points: float | None
    cumulative_points_by_dept: dict[str, float | None]


class CaseWeek(TypedDict):
    dept: str
    week: str
    basis: str
    plan_rows: list[PlanRow]
    work_rows: list[WorkRow]
    matched: int
    unplanned: int
    truncated: bool


class CaseDetail(TypedDict):
    case: CaseFacts
    week: CaseWeek
    link: str | None
