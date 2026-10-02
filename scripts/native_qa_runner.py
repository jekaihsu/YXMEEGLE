"""Repository-local native QA transport runner; no production workspace access."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.native_qa import QARunner, QAStore, QAError, policy, receipt_output
from backend.lark_adapter import application_adapter, RemoteFailure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='QA manifest JSON; no secrets')
    parser.add_argument('--saved-config', help='Optional existing server-config JSON for credentials; never printed')
    parser.add_argument('--db', default=str(ROOT / '.runtime/native-qa/attempts.sqlite'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Validate local configuration only; no network')
    for name in ('prepare', 'create', 'poll', 'status'):
        command = commands.add_parser(name)
        command.add_argument('--run-id', required=True)
        if name == 'create':
            command.add_argument('--allow-create', action='store_true', help='Explicitly authorize one real QA instance POST')
    args = parser.parse_args(argv)

    def load_config():
        manifest = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        credentials = {}
        if args.saved_config:
            raw = json.loads(Path(args.saved_config).read_text(encoding='utf-8-sig'))
            credentials = raw.get('variables', {}).get('data', raw)
        credentials = dict(credentials)
        credentials.update({key: value for key, value in os.environ.items() if key.startswith('LARK_')})
        return manifest, credentials

    try:
        target = Path(args.db).resolve()
        if not target.is_relative_to((ROOT / '.runtime').resolve()) or target.suffix != '.sqlite':
            raise QAError('qa_database_must_be_workspace_runtime_sqlite')
        if target in {Path(args.config).resolve(), Path(args.saved_config).resolve() if args.saved_config else None}:
            raise QAError('qa_database_cannot_replace_configuration')
        manifest, credentials = load_config()
        policy(manifest, credentials)
        if args.command == 'doctor':
            result = {'purpose': 'native_qa_transport_only', 'config_valid': True, 'credentials_configured': True,
                      'network_accessed': False, 'business_apply_allowed': False}
        else:
            store = QAStore(target)
            runner = QARunner(store, load_config, application_adapter)
            if args.command == 'status':
                result = receipt_output(runner.checked_record(args.run_id)[0])
            elif args.command == 'create':
                result = runner.create(args.run_id, allow_create=args.allow_create)
            else:
                result = getattr(runner, args.command)(args.run_id)
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False))
        return 0
    except QAError as exc:
        code = str(exc)
    except RemoteFailure:
        code = 'remote_operation_unverified'
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error):
        code = 'invalid_or_unavailable_qa_configuration_or_storage'
    except Exception:
        # Unexpected transport/library errors must not print exception text,
        # request bodies or credential-bearing traceback locals.
        code = 'unexpected_qa_operation_failure'
    print(json.dumps({'ok': False, 'error': {'code': code}, 'business_apply_allowed': False}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
