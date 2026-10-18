"""Dispatch rollout and the explicitly permitted V4 projections."""
from dataclasses import dataclass

from ..node_assignment.config import NodeAssignmentConfig


@dataclass(frozen=True)
class SourceTable:
    table_id: str
    fields: dict[str, tuple[int, ...]]


TABLES = {
    'schedule': SourceTable('tblZz6Mkhv9gHrB2', {
        '條類型': (3,), '開始日期': (5,), '結束日期': (5,), '組別': (3,), '業別': (3,),
        '案件': (18, 21), '工作內容': (1,), '人員': (18, 21), '儀器': (18, 21), '車輛': (18, 21),
    }),
    'people': SourceTable('tblfaCO2xPUNptQH', {'姓名': (1,), '在職': (7,)}),
    'instruments': SourceTable('tblg3Fo23T6Gos6S', {'儀器名稱': (1,), '啟用': (7,), '狀態': (3,)}),
    'vehicles': SourceTable('tblTQv8l5ntnbwyp', {'車牌': (1,), '啟用': (7,)}),
    'cases': SourceTable('tblmSQrcCs9vPQZx', {'工程確認單編號': (1,), '工程名稱': (1,)}),
}


@dataclass(frozen=True)
class DispatchBoardConfig:
    enabled: bool
    base: str
    ttl_seconds: float = 60
    stale_max_seconds: float = 900

    @classmethod
    def from_env(cls, cfg):
        existing = NodeAssignmentConfig.from_env(cfg)
        return cls(str(cfg.get('DISPATCH_BOARD_ENABLED', 'false')).lower() == 'true',
                   cfg.get('LARK_V4_BASE_TOKEN') or existing.base,
                   existing.read_ttl_seconds, existing.stale_max_seconds)
