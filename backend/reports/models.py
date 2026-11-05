"""Public report shapes. Raw source records never cross this boundary."""
from typing import Literal, NotRequired, TypedDict


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


class ProgressOptions(TypedDict):
    group: list[str]
    status: list[StatusCount]


class ProgressKpi(TypedDict):
    matched_points: float
    planned_points: float | None
    actual_points: float
    planned_days: int
    actual_days: int
    matched_days: int
    unplanned_days: int
    achievement: float | None
    open_cases: int
    remaining_points: float | None


class ProgressGroup(TypedDict):
    group: str
    group_label: str
    matched_points: float
    planned_days: int
    matched_days: int
    planned: float
    actual: float
    unplanned_days: int
    achievement: float | None


class ProgressResponse(TypedDict):
    gaps: list[dict]
    options: ProgressOptions
    dept: str
    week: str
    basis: str
    kpi: ProgressKpi
    by_group: list[ProgressGroup]
    items: list[ProgressRow]
    total: int
    offset: int
    limit: int


class Gap(TypedDict):
    id: str
    severity: Literal['info','warn']
    message: str


class Meta(TypedDict):
    fetched_at: str
    stale: bool
    snapshot: str
    gaps: list[Gap]
    refresh_error: NotRequired[bool]
    can_refresh: NotRequired[bool]


class Kpi(TypedDict):
    total: int
    passed: int
    returned: int
    pending: int
    unset: int
    error_rate: float | None
    pending_rate: float | None
    coverage: float | None


class ReviewTrend(TypedDict):
    week: str
    total: int
    returned: int
    passed: int
    error_rate: float | None


class ReviewGroup(Kpi):
    group: str


class ReviewControl(TypedDict):
    checked: int
    unchecked: int
    violated: int


class HomeOffice(TypedDict):
    gaps: list[Gap]
    kpi: Kpi


class HomeQuality(HomeOffice):
    kpi_prev: Kpi
    trend: list[ReviewTrend]
    by_group: list[ReviewGroup]
    control: ReviewControl


class SalesKpi(TypedDict):
    cases: int
    contract_total: float | None
    billed_total: float | None
    received_total: float | None
    unbilled_billable: float | None
    receivable: float | None


class SalesStatus(TypedDict):
    status: str
    count: int
    contract_total: float | None


class SalesRow(TypedDict):
    id: str
    code: str
    name: str
    client: str
    pm: str
    status: str
    contract: float | None
    progress_revenue: float | None
    progress_cost: float | None
    progress_billing: float | None
    billable_unbilled: float | None
    receivable: float | None
    link: str


class HomeSales(TypedDict):
    gaps: list[Gap]
    kpi: SalesKpi
    by_status: list[SalesStatus]
    top_receivable: list[SalesRow]


class AssetKpi(TypedDict):
    total: int
    active: int
    in_use: int
    idle: int
    repair: int
    km: float | None
    daily_rent_total: float | None
    mileage_excluded: NotRequired[int]
    coverage: NotRequired[float | None]


class AssetCategory(TypedDict):
    category: str
    total: int
    in_use: int
    repair: int


class HomeAsset(TypedDict):
    gaps: list[Gap]
    kpi: AssetKpi
    by_category: list[AssetCategory]


class HomeAssets(TypedDict):
    instrument: HomeAsset
    vehicle: HomeAsset


class HomeProgress(TypedDict):
    gaps: list[Gap]
    week: str
    basis: Literal['days','points']
    kpi: ProgressKpi
    by_group: list[ProgressGroup]


class HomeResponse(TypedDict):
    meta: Meta
    week: str
    quality: HomeQuality | None
    quality_office: HomeOffice | None
    sales: HomeSales | None
    progress: HomeProgress | None
    assets: HomeAssets | None
