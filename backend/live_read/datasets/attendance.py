"""Refresh today's fourteen-day schedule with the existing manual override rules."""
from . import DatasetRefresher, content_fingerprint
from ..client import ALLOWED_POSTS


class AttendanceRefresher(DatasetRefresher):
    # This narrowly scoped read query is the only extra POST for this dataset.
    allowed_posts = ALLOWED_POSTS + (r'/attendance/v1/user_daily_shifts/query',)

    def __call__(self, wid):
        service, clients = self.reader()
        status = service.sync(wid, None)
        with service.sessions() as db:
            state = service._state(db, db.get(service.W, wid))
        rows = [{key: value for key, value in row.items()
                 if key not in ('id', 'history', 'version', 'updated_at', 'source_verified_at')}
                for row in state['work_schedules']
                if row.get('basis') == 'attendance_schedule'
                and status['date_from'] <= row['day'] <= status['date_to']]
        return dict(fingerprint=content_fingerprint(rows),
                    fetched_at=status['last_success_at'], lark=self.metrics(clients))

    refresh = __call__
