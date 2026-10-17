"""Verify only this deployment's isolated demo workspace; never access Lark data."""
from pathlib import Path
import argparse
import hashlib
import json
import secrets
import re
from urllib.parse import parse_qs, urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
URL = 'https://yongxiang-projects-20260925.zeabur.app'


def verification_passed(result):
    checks = result.get('checks')
    return isinstance(checks, dict) and bool(checks) and all(value is True for value in checks.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['before', 'after', 'config', 'assets'])
    args = parser.parse_args()
    state_file = RUNTIME / 'zeabur-persistence-state.json'
    result = {'url': URL, 'phase': args.phase, 'checks': {}}
    with httpx.Client(timeout=45, follow_redirects=True, headers={'Origin': URL}) as client:
        health = client.get(URL + '/api/health')
        health.raise_for_status()
        result['health'] = health.json()
        assert health.json()['database'] == 'postgresql'
        result['checks']['postgresql_health'] = True
        if args.phase == 'assets':
            response = client.get(URL + '/')
            response.raise_for_status()
            expected = sorted(re.findall(r'(?:src|href)="(/assets/[^"]+)"', (ROOT / 'frontend/dist/index.html').read_text(encoding='utf-8')))
            actual = sorted(re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.text))
            result['assets'] = actual
            result['expected_assets'] = expected
            result['checks']['latest_frontend_assets'] = bool(expected) and actual == expected
            downloads_ok = False
            if result['checks']['latest_frontend_assets']:
                try:
                    downloads_ok = all(client.get(URL + asset).status_code == 200 for asset in actual)
                except httpx.HTTPError:
                    downloads_ok = False
            result['checks']['asset_downloads'] = downloads_ok
        elif args.phase == 'config':
            session = client.get(URL + '/api/session')
            session.raise_for_status()
            assert session.json()['auth_configured'] is True
            response = client.get(URL + '/api/auth/lark/login', follow_redirects=False)
            assert response.status_code in (302, 307)
            parsed = urlsplit(response.headers['location'])
            values = parse_qs(parsed.query)
            assert parsed.hostname == 'accounts.larksuite.com'
            assert values['app_id'] == ['cli_aa3cab98b2789e17']
            assert values['redirect_uri'] == [URL + '/api/auth/lark/callback']
            assert set(values.get('scope', [''])[0].split()) == {'bitable:app:readonly', 'approval:approval:readonly'}
            result['checks'].update({'new_app_configured': True, 'oauth_redirect_app_and_callback': True, 'explicit_readonly_scopes': True})
            result['live_oauth_completed'] = False
        elif args.phase == 'before':
            page = client.get(URL + '/')
            assert page.status_code == 200 and '<div id="root">' in page.text
            result['checks']['frontend_served'] = True
            session = client.get(URL + '/api/session')
            session.raise_for_status()
            assert session.json()['mode'] == 'demo'
            w = client.get(URL + '/api/workspace').json()
            marker = 'Deployment persistence check ' + secrets.token_hex(8)
            comment = client.post(URL + '/api/actions', json={'action': 'comment_add', 'version': w['version'], 'request_id': secrets.token_hex(16), 'project_id': 'p1', 'payload': {'body': marker}})
            comment.raise_for_status()
            w = comment.json()
            data = marker.encode()
            uploaded = client.post(URL + '/api/files', data={'project_id': 'p1', 'node_id': 'p1-pm', 'direction': 'input', 'version': str(w['version'])}, files={'file': ('deployment-check.txt', data, 'text/plain')})
            uploaded.raise_for_status()
            project = next(p for p in uploaded.json()['projects'] if p['id'] == 'p1')
            entry = next(f for f in project['files'] if f['name'] == 'deployment-check.txt')
            assert client.get(URL + entry['url']).content == data
            source = client.get(URL + '/api/sources').json()
            assert not source['records'] and source['status'] == 'requires_login'
            denied = client.post(URL + '/api/sources/sync')
            assert denied.status_code == 403
            state = {'cookies': dict(client.cookies), 'marker': marker, 'file_url': entry['url'], 'sha256': hashlib.sha256(data).hexdigest()}
            state_file.write_text(json.dumps(state), encoding='utf-8')
            result['checks'].update({'demo_session': True, 'database_write': True, 'attachment_write_download': True, 'demo_live_source_denied': True})
        else:
            state = json.loads(state_file.read_text(encoding='utf-8'))
            client.cookies.update(state['cookies'])
            r = client.get(URL + '/api/workspace')
            r.raise_for_status()
            project = next(p for p in r.json()['projects'] if p['id'] == 'p1')
            assert any(c['body'] == state['marker'] for c in project['comments'])
            file = client.get(URL + state['file_url'])
            file.raise_for_status()
            assert hashlib.sha256(file.content).hexdigest() == state['sha256']
            result['checks'].update({'same_session_after_restart': True, 'database_record_retained': True, 'attachment_bytes_retained': True})
    result['ok'] = verification_passed(result)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / ('zeabur-verification-' + args.phase + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
