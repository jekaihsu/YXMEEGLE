"""Dispatch publish rollout, approval policy and seat holders, read once from the environment."""
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from ..dispatch_board.config import DispatchBoardConfig


class Seat(StrEnum):
    GROUP_LEADER = 'group_leader_confirmed'
    MANAGER_REVIEW = 'manager_review'
    PM_FINAL = 'pm_final'


SEAT_ORDER = (Seat.GROUP_LEADER, Seat.MANAGER_REVIEW, Seat.PM_FINAL)
SEAT_ENV = {Seat.GROUP_LEADER: 'DISPATCH_SEAT_GROUP_LEADER', Seat.MANAGER_REVIEW: 'DISPATCH_SEAT_MANAGER_REVIEW',
            Seat.PM_FINAL: 'DISPATCH_SEAT_PM_FINAL'}
OPEN_ID = re.compile(r'ou_[A-Za-z0-9]+')


def _flag(env, key):
    return str(env.get(key, 'false')).lower() == 'true'


@dataclass(frozen=True)
class DispatchPublishConfig:
    enabled: bool = False
    board_enabled: bool = False
    policy: Literal['required', 'direct'] = 'required'
    allow_unknown: bool = False
    seats: dict = field(default_factory=dict)
    base: str = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
    preview_ttl_seconds: float = 900
    pending_grace_seconds: float = 60

    @classmethod
    def from_env(cls, env):
        def number(key, default, low, high):
            try:
                value = float(env.get(key, default))
            except (TypeError, ValueError):
                return default
            return min(high, max(low, value)) if math.isfinite(value) else default

        # Any value other than an explicit "direct" keeps the approval seats.
        policy = 'direct' if str(env.get('DISPATCH_APPROVAL_POLICY', 'required')).strip().lower() == 'direct' else 'required'
        seats = {seat: frozenset(v for v in (p.strip() for p in str(env.get(key, '')).split(',')) if OPEN_ID.fullmatch(v))
                 for seat, key in SEAT_ENV.items()}
        return cls(_flag(env, 'DISPATCH_WRITE_ENABLED'), _flag(env, 'DISPATCH_BOARD_ENABLED'), policy,
                   _flag(env, 'DISPATCH_ALLOW_UNKNOWN'), seats, DispatchBoardConfig.from_env(env).base,
                   number('DISPATCH_PREVIEW_TTL_SECONDS', 900, 60, 3600),
                   number('DISPATCH_PENDING_GRACE_SECONDS', 60, 5, 3600))

    @property
    def required_seats(self):
        return () if self.policy == 'direct' else SEAT_ORDER

    def holds(self, open_id):
        return frozenset(seat for seat in self.required_seats if open_id in self.seats.get(seat, ()))
