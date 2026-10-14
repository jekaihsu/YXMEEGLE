"""Shared weekly view; the existing coordinator owns leases and last-good data."""
from copy import deepcopy
from fastapi import HTTPException
from .coordinator import RefreshCoordinator
from .datasets.weekly_attendance import week_window, empty_view
from .client import ReadFailure


class PeopleAttendance(RefreshCoordinator):
    def __init__(self, sessions, cache_row, live, cfg, **kwargs):
        self.live = live
        super().__init__(sessions, cache_row, {'attendance': self._weekly}, cfg, **kwargs)

    def _key(self, wid, dataset):
        return 'people-attendance:' + wid

    def _weekly(self, key):
        wid, monday = key.rsplit('|', 1)
        state = self.live.ensure(wid, 'roster', wait=True)
        if state['status'] != 'fresh':
            raise ReadFailure('Roster has not been read')
        return self.live.refreshers['attendance'].weekly(wid, week_window(monday))

    def view(self, wid, week=None):
        try:
            days = week_window(week)
        except (ValueError, TypeError):
            raise HTTPException(422, '請提供有效週日期') from None
        key = wid + '|' + days[0]
        result = empty_view(days)
        if not self._enabled(wid):
            return dict(result, status='not-connected')
        attempt = self.ensure(key, 'attendance')
        row = self._read(self._key(key, 'attendance'))
        snapshot = deepcopy(row.get('snapshot'))
        if snapshot:
            result = snapshot
        state = self._dataset_status('attendance', row)
        result.update(incomplete=result['status'] == 'incomplete', as_of=state['as_of'], missing_scopes=state.get('missing_scopes', []),
                      refreshing=state['status'] == 'refreshing' or attempt['status'] in ('busy', 'refreshing'))
        if not snapshot and attempt['status'] == 'error':
            result.update(status='read-failed', incomplete=False, refreshing=False)
        elif not snapshot and result['refreshing']:
            result.update(status='loading', incomplete=False)
        elif state['status'] in ('needs-permission', 'blocked', 'error'):
            result['status'] = 'needs-permission' if state['status'] == 'needs-permission' else 'read-failed'
            result['summary'] = empty_view(days)['summary']
        elif snapshot and state['status'] in ('stale', 'refreshing'):
            result['status'] = 'stale'
        return result
