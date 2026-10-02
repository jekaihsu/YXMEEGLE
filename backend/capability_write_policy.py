"""User decision 2026-09-27: salary-linked Base remains read-only.

There is deliberately no administrator/environment switch to resume writes.
Resumption requires a new explicit business decision and reviewed code change.
"""
CAPABILITY_BASE = 'VwAsbezz9app3YsramgjduLYp2U'
PAUSED_MESSAGE = '能力地圖回寫暫停：涉及薪資，僅保留工作台紀錄，不更新 Lark'


def protected_request(method, path):
    from urllib.parse import unquote, urlsplit
    parts = unquote(urlsplit(path).path).strip('/').split('/')
    if 'apps' not in parts:
        return False
    index = parts.index('apps')
    if len(parts) <= index + 1 or parts[index + 1] != CAPABILITY_BASE:
        return False
    method = method.upper()
    return method not in ('GET', 'HEAD') and not (
        method == 'POST' and parts[-2:] == ['records', 'search'])
