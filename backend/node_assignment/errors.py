"""One error type with a stable machine code; the HTTP status follows from the code."""

STATUS = {
    'disabled': 404,
    'not_found': 404,
    'forbidden': 403,
    'writes_disabled': 403,
    'invalid': 422,
    'payload_too_large': 413,
    'rate_limited': 429,
    'illegal_transition': 409,
    'revision_conflict': 409,
    'duplicate_assignment_key': 409,
    'idempotency_conflict': 409,
    'readback_mismatch': 409,
    'busy': 409,
    'preview_stale': 409,
    'nothing_to_start': 409,
    'outcome_unknown': 502,
    'lark_permission': 502,
    'lark_error': 502,
    'lark_unavailable': 503,
    'lark_unconfigured': 503,
    'roster_unavailable': 503,
}


class Failure(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    @property
    def status(self):
        return STATUS[self.code]

    def body(self):
        return {'detail': self.message, 'code': self.code, **self.extra}
