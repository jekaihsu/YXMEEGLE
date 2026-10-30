"""Tri-state values, strict Asia/Taipei date handling and canonical fingerprints."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo('Asia/Taipei')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class OpsError(Exception):
    """Base for contract violations; `code` is a stable machine-readable reason."""
    code = 'ops_error'

    def __init__(self, message='', code=None):
        super().__init__(message or self.code)
        if code:
            self.code = code


class ValidationError(OpsError):
    code = 'invalid'


class _Marker:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


CLEAR = _Marker('CLEAR')        # explicitly observed/requested empty value
OMITTED = _Marker('OMITTED')    # outside the command/patch: preserve, send nothing
UNKNOWN = _Marker('UNKNOWN')    # unreadable/forbidden/unverified: never a baseline


class SetValue:
    """A concrete value. SET(None) is invalid; use CLEAR."""
    __slots__ = ('value',)

    def __init__(self, value):
        if value is None:
            raise ValidationError('SET(null) is invalid; encode CLEAR explicitly', 'set_null')
        self.value = value

    def __eq__(self, other):
        return isinstance(other, SetValue) and self.value == other.value

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):
        return f'SET({self.value!r})'


def normalize_date(value):
    """Strict YYYY-MM-DD calendar date; returns the canonical string."""
    if isinstance(value, datetime):
        raise ValidationError('datetime is not a date-only value', 'invalid_date')
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValidationError(f'invalid date {value!r}', 'invalid_date')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValidationError(f'invalid calendar date {value!r}', 'invalid_date') from None


def require_aware(value, what='timestamp'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValidationError(f'{what} is not ISO-8601', 'invalid_timestamp') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f'{what} must be an offset-aware datetime', 'naive_datetime')
    return value


def to_utc_iso(value, what='timestamp'):
    return require_aware(value, what).astimezone(timezone.utc).isoformat()


def taipei_date_from_instant(instant):
    """Convert an aware instant to Asia/Taipei BEFORE extracting the day."""
    return require_aware(instant).astimezone(TAIPEI).date().isoformat()


def taipei_date_from_millis(millis):
    if isinstance(millis, bool) or not isinstance(millis, int):
        raise ValidationError('timestamp millis must be an int', 'invalid_timestamp')
    return taipei_date_from_instant(datetime.fromtimestamp(millis / 1000, tz=timezone.utc))


def date_to_taipei_millis(day):
    parsed = date.fromisoformat(normalize_date(day))
    midnight = datetime(parsed.year, parsed.month, parsed.day, tzinfo=TAIPEI)
    return int(midnight.timestamp() * 1000)


FIELD_TYPES = {'case.pm': 'person', 'case.deadline': 'date', 'node.responsible': 'person', 'node.deadline': 'date'}


def coerce(field_id, value):
    """Validate a SET/CLEAR/OMITTED/UNKNOWN value for a governed field; SET payload is canonicalised."""
    if field_id not in FIELD_TYPES:
        raise ValidationError(f'unknown governed field {field_id!r}', 'unknown_field')
    if value is CLEAR or value is OMITTED or value is UNKNOWN:
        return value
    if not isinstance(value, SetValue):
        raise ValidationError('value must be SetValue, CLEAR, OMITTED or UNKNOWN', 'invalid_value')
    kind = FIELD_TYPES[field_id]
    if kind == 'date':
        return SetValue(normalize_date(value.value))
    if not isinstance(value.value, str) or not value.value.strip() or value.value != value.value.strip():
        raise ValidationError('person value must be one stable identity string', 'invalid_person')
    return SetValue(value.value)


def encode(value):
    """Tagged JSON form. OMITTED/UNKNOWN are never persisted as values."""
    if value is CLEAR:
        return {'t': 'clear'}
    if isinstance(value, SetValue):
        return {'t': 'set', 'v': value.value}
    raise ValidationError(f'{value!r} cannot be encoded as a stored value', 'unstorable')


def decode(blob):
    if blob is None:
        return UNKNOWN
    if blob['t'] == 'clear':
        return CLEAR
    if blob['t'] == 'set':
        return SetValue(blob['v'])
    raise ValidationError('corrupt stored value', 'corrupt_value')


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def backoff_seconds(attempt, retry_after=0):
    """min(60, 2^(attempt-1)) seconds, honouring a larger retry-after."""
    return max(min(60, 2 ** (attempt - 1)), retry_after or 0)


def add_seconds(iso, seconds):
    return (require_aware(iso) + timedelta(seconds=seconds)).isoformat()
