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
# Slice 2: the published task rows, their node position and the roster's Lark accounts.
PUBLISH_TABLES = {
    'tasks': SourceTable('tblsoyGcC6K5AipF', {
        '標題': (1,), '內容': (1,), '負責人': (11,), '指派人': (11,), '截止日': (5,), '部門': (3,), '狀態': (3,),
        '節點指派': (18, 21), '專案編號': (1,), '工程確認單': (18, 21), '任務階段': (3,), '任務種類': (3,),
        '工作包編號': (1,), '父義務': (18, 21), '範圍版本': (2,), '規則版本': (1,), '證據版本': (1,),
        '預定開始': (5,), '預定結束': (5,), '預估人時': (2,), '組員': (11,), '使用儀器': (18, 21), '使用車輛': (18, 21),
        '排程狀態': (3,), '排程版本': (2,), '命令編號': (1,), '讀回時間': (5,), '成果接受狀態': (3,), '接受摘要': (1,),
    }),
    'nodes': SourceTable('tblcPZPmezkyeVb7', {'節點': (3,), '確認單編號': (1,)}),
    'accounts': SourceTable('tblfaCO2xPUNptQH', {'Lark帳號': (11,)}),
}
SOURCES = {**TABLES, **PUBLISH_TABLES}


@dataclass(frozen=True)
class DispatchBoardConfig:
    enabled: bool
    base: str
    ttl_seconds: float = 60
    stale_max_seconds: float = 900
    published_tasks: bool = False

    @classmethod
    def from_env(cls, cfg):
        existing = NodeAssignmentConfig.from_env(cfg)
        return cls(str(cfg.get('DISPATCH_BOARD_ENABLED', 'false')).lower() == 'true',
                   cfg.get('LARK_V4_BASE_TOKEN') or existing.base,
                   existing.read_ttl_seconds, existing.stale_max_seconds,
                   str(cfg.get('DISPATCH_WRITE_ENABLED', 'false')).lower() == 'true')
