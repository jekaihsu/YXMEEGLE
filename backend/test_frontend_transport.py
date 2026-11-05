"""Production static transport contracts, using only an isolated local app."""
from fastapi.testclient import TestClient

from .app import create_app


def test_hashed_assets_are_immutable_and_html_revalidates(tmp_path):
    frontend = tmp_path / 'dist'
    assets = frontend / 'assets'
    assets.mkdir(parents=True)
    (frontend / 'index.html').write_text('<!doctype html><h1>workbench</h1>')
    script = b'const message="local fixture";\n' * 6000
    name = 'index-aB_123-9.js'
    (assets / name).write_bytes(script)
    (assets / 'plain.js').write_bytes(script)
    (frontend / 'logo.svg').write_text('<svg/>')
    app = create_app({
        'DATABASE_URL': f'sqlite:///{tmp_path}/transport.db',
        'UPLOAD_DIR': str(tmp_path / 'uploads'),
        'SESSION_SECRET': 'local-transport-test' * 3,
        'APP_ENV': 'development', 'DEMO_MODE': 'true',
        'LARK_LIVE_READ_ENABLED': 'false',
        'LARK_APP_ID': '', 'LARK_APP_SECRET': '', 'LARK_ALLOWED_TENANTS': '',
        'FRONTEND_DIST': str(frontend),
    })
    try:
        with TestClient(app) as client:
            for path in ('/', '/index.html', '/projects/deep-link'):
                response = client.get(path)
                assert response.status_code == 200
                assert response.headers['cache-control'] == 'no-cache'
                assert 'immutable' not in response.headers['cache-control']
            url = f'/assets/{name}'
            for encoding in ('identity', 'gzip'):
                response = client.get(url, headers={'Accept-Encoding': encoding})
                assert response.status_code == 200 and response.content == script
                assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
                assert response.headers.get('content-encoding') == ('gzip' if encoding == 'gzip' else None)
                assert 'Accept-Encoding' in response.headers['vary']
            unchanged = client.get(url, headers={'If-None-Match': response.headers['etag']})
            assert unchanged.status_code == 304 and unchanged.content == b''
            assert unchanged.headers['cache-control'] == 'public, max-age=31536000, immutable'
            partial = client.get(url, headers={'Range': 'bytes=0-20', 'Accept-Encoding': 'identity'})
            assert partial.status_code == 206 and partial.content == script[:21]
            assert 'immutable' in partial.headers['cache-control']
            for path in ('/assets/plain.js', '/logo.svg', '/assets/missing-12345678.js'):
                assert 'immutable' not in client.get(path).headers.get('cache-control', '')
            client.get('/api/session')
            plain = client.get('/api/workspace', headers={'Accept-Encoding': 'identity'})
            zipped = client.get('/api/workspace', headers={'Accept-Encoding': 'gzip'})
            assert plain.status_code == zipped.status_code == 200
            assert zipped.headers['cache-control'] == 'no-store'
            assert zipped.headers['content-encoding'] == 'gzip'
            assert 'content-encoding' not in plain.headers
            assert int(zipped.headers['content-length']) < len(zipped.content)
            assert zipped.json().keys() == plain.json().keys()
    finally:
        app.state.engine.dispose()
