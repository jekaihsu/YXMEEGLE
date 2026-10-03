"""Run defect reproductions against isolated synthetic data, never production."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--related', action='store_true', help='Also run the eight related backend test modules.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = root / '.runtime' / ('review3-reproductions-' + uuid.uuid4().hex[:12])
    output.mkdir(parents=True)
    blocked = ('LARK_', 'BACKUP_', 'RESTORE_', 'ZEABUR_', 'PYTEST_')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(blocked) and k not in
           ('DATABASE_URL', 'SESSION_SECRET', 'UPLOAD_DIR', 'PUBLIC_ORIGIN')}
    env.update(APP_ENV='development', DEMO_MODE='true',
               DATABASE_URL='sqlite:///' + (output / 'bootstrap.db').as_posix(),
               UPLOAD_DIR=str(output / 'uploads'),
               SESSION_SECRET='synthetic-review-only-not-real-secret',
               PYTHONIOENCODING='utf-8', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    files = ['docs/review3/reproductions/test_' + name + '.py'
             for name in ('core', 'permissions', 'jobs')]
    if args.related:
        files += ['backend/test_' + name + '.py' for name in (
            'operations', 'scope_delivery_identity', 'public_case_http_boundaries',
            'company_admin_admission', 'project_concurrency', 'worker_reliability',
            'source_identity', 'sop_contract_integration')]
    command = [sys.executable, '-X', 'utf8', '-m', 'pytest', *files,
               '-q', '--tb=short', '--disable-warnings', '--junitxml=' + str(output / 'pytest.xml')]
    started = time.monotonic()
    with (output / 'pytest.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    record = dict(files=files, exit_code=result.returncode,
                  elapsed_seconds=round(time.monotonic() - started, 2),
                  purpose='Passing new reproductions assert that current defects exist, not that fixes pass.')
    (output / 'result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print((output / 'pytest.log').read_text(encoding='utf-8'))
    print('Local evidence:', output.relative_to(root).as_posix())
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
