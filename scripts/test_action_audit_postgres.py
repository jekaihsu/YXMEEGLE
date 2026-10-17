"""Run audit regression tests with a disposable local PostgreSQL cluster."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlencode


def main():
    for binary in ('initdb', 'pg_ctl'):
        if not shutil.which(binary):
            raise SystemExit(f'{binary} must be on PATH (install PostgreSQL server tools)')
    root = Path(__file__).resolve().parents[1]
    args = sys.argv[1:] or ['backend/test_action_audit_database.py', '-q', '-ra']
    # Use a short path for PostgreSQL's Unix socket length limit on macOS.
    with tempfile.TemporaryDirectory(prefix='yx-audit-', dir='/tmp') as temporary:
        data = str(Path(temporary) / 'data')
        log = str(Path(temporary) / 'postgres.log')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        subprocess.run(['initdb', '-D', data, '-U', 'postgres', '--auth=trust',
                        '--encoding=UTF8', '--no-locale'], check=True,
                       stdout=subprocess.DEVNULL)
        try:
            # Private Unix socket only; trust authentication is never exposed over TCP.
            subprocess.run(['pg_ctl', '-D', data, '-l', log, '-w', 'start',
                            '-o', f"-h '' -k {temporary} -p {port}"], check=True)
            env = dict(os.environ)
            env['ACTION_AUDIT_TEST_POSTGRES_URL'] = (
                'postgresql+psycopg://postgres@/postgres?'
                + urlencode({'host': temporary, 'port': port}))
            print(f'Running pytest with disposable PostgreSQL on port {port}', flush=True)
            return subprocess.run([sys.executable, '-m', 'pytest', *args],
                                  cwd=root, env=env).returncode
        finally:
            if (Path(data) / 'postmaster.pid').exists():
                subprocess.run(['pg_ctl', '-D', data, '-m', 'immediate', '-w', 'stop'],
                               check=True)


if __name__ == '__main__':
    raise SystemExit(main())
