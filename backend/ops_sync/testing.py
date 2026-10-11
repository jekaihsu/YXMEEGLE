"""Synthetic fixtures for ops_sync tests (no real people or production data)."""
from datetime import datetime, timezone

from . import values as V
from .adapter import BINDING
from .commands import CommandEnvelope

NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def env(command_id, field='case.deadline', expected=V.CLEAR, expected_revision=0, intended=V.SetValue('2026-10-20'),
        entity='case_test_1', actor='ou_test_pm_1', binding=BINDING, **extra):
    return CommandEnvelope(command_id, entity, field, expected, expected_revision, intended, actor, 'app', NOW, binding, **extra)
