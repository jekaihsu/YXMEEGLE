"""Avatar URLs accepted from Lark identity and Bitable responses."""
from urllib.parse import urlsplit

AVATAR_HOST_SUFFIXES = ('feishucdn.com',)


def avatar_url(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        if (url.scheme == 'https' and not url.username and not url.password
                and url.port in (None, 443) and not url.fragment
                and any(host == suffix or host.endswith('.' + suffix) for suffix in AVATAR_HOST_SUFFIXES)):
            return value
    except ValueError:
        pass
    return None
