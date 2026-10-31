"""Run audit or AI regression tests with a disposable local PostgreSQL cluster."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlencode
from xml.etree import ElementTree


def main():
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        raise SystemExit('Run PostgreSQL tests as a non-root user')
    ai = '--ai' in sys.argv
    if ai:
        sys.argv.remove('--ai')
    for binary in ('initdb', 'pg_ctl'):
        if not shutil.which(binary):
            raise SystemExit(f'{binary} must be on PATH (install PostgreSQL server tools)')
    root = Path(__file__).resolve().parents[1]
    if ai:
        defaults = [str(p.relative_to(root)) for p in sorted((root / 'backend').glob('test_ai_*.py'))]
        defaults += ['-q', '-ra']
    else:
        defaults = ['backend/test_action_audit_database.py', '-q', '-ra']
    args = sys.argv[1:] or defaults
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
            env['AI_TEST_POSTGRES_URL' if ai else 'ACTION_AUDIT_TEST_POSTGRES_URL'] = (
                'postgresql+psycopg://postgres@/postgres?'
                + urlencode({'host': temporary, 'port': port}))
            print(f'Running pytest with disposable PostgreSQL on port {port}', flush=True)
            report = Path(temporary) / 'pytest.xml'
            reporting = [f'--junitxml={report}'] if ai else []
            result = subprocess.run([sys.executable, '-m', 'pytest', *args, *reporting],
                                    cwd=root, env=env)
            if ai and report.exists():
                cases = ElementTree.parse(report).findall('.//testcase')
                for backend in ('sqlite', 'postgresql', 'other'):
                    selected = [c for c in cases if (backend in c.attrib['name'] if backend != 'other'
                                else not any(b in c.attrib['name'] for b in ('sqlite', 'postgresql')))]
                    failed = sum(c.find('failure') is not None or c.find('error') is not None for c in selected)
                    skipped = sum(c.find('skipped') is not None for c in selected)
                    print(f'{backend}: {len(selected) - failed - skipped} passed, {failed} failed, {skipped} skipped', flush=True)
            return result.returncode
        finally:
            if (Path(data) / 'postmaster.pid').exists():
                subprocess.run(['pg_ctl', '-D', data, '-m', 'immediate', '-w', 'stop'],
                               check=True)


if __name__ == '__main__':
    raise SystemExit(main())
