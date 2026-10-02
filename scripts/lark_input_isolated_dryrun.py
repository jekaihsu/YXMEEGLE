"""Prepare isolated CLI config and inspect identity/create dry-run; never create.

Config layout and env isolation verified against official CLI v1.0.85 source.
No global config/profile mutation, subprocess shell, or credential output.
"""
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP='cli_aa3cab98b2789e17'
PRIVATE=ROOT/'.runtime/lark-input-cli'
CLI=Path(os.environ['APPDATA'])/'npm/node_modules/@larksuite/cli/bin/lark-cli.exe'


def main():
    ignored=subprocess.run(['git','-c',f'safe.directory={ROOT.as_posix()}','check-ignore',str(PRIVATE/'config.json')],cwd=ROOT,capture_output=True)
    if ignored.returncode:raise SystemExit('Refusing non-ignored credential directory')
    config=json.loads((ROOT/'.runtime/lark-existing.json').read_text(encoding='utf-8'))
    if config.get('LARK_APP_ID')!=APP or not config.get('LARK_APP_SECRET'):
        raise SystemExit('Dedicated app credential mismatch')
    env=dict(os.environ,LARKSUITE_CLI_CONFIG_DIR=str(PRIVATE))
    # Do not silently change an agent context or use its credential extension.
    markers=('OPENCLAW_HOME','OPENCLAW_STATE_DIR','OPENCLAW_CONFIG_PATH','OPENCLAW_SERVICE_MARKER',
             'OPENCLAW_SERVICE_VERSION','OPENCLAW_GATEWAY_PORT','OPENCLAW_SHELL',
             'HERMES_HOME','HERMES_GATEWAY_TOKEN','HERMES_SESSION_KEY')
    if any(env.get(k) for k in markers) or any(env.get(k)=='1' for k in ('OPENCLAW_CLI','HERMES_QUIET','HERMES_EXEC_ASK','LARK_CHANNEL')):
        raise SystemExit('Agent credential context present; explicit isolation review required')
    for key in ('LARKSUITE_CLI_PROFILE',):env.pop(key,None)
    PRIVATE.mkdir(parents=True,exist_ok=True)
    path=PRIVATE/'config.json'
    if path.exists():
        prior=json.loads(path.read_text(encoding='utf-8'))
        if any(a.get('appId')!=APP for a in prior.get('apps',[])):
            raise SystemExit('Existing isolated config belongs to a different app')
    local={'currentApp':'workbench-input','apps':[{'name':'workbench-input','appId':APP,
        'appSecret':config['LARK_APP_SECRET'],'brand':'lark','defaultAs':'bot','users':[]}]}
    path.write_text(json.dumps(local),encoding='utf-8');path.chmod(0o600)
    def run(args):
        out=subprocess.run([str(CLI),'--profile','workbench-input',*args],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
        if out.returncode:
            # Error text can contain sensitive provider context; do not print it.
            raise SystemExit(f'Isolated CLI failed ({args[0]}); exit {out.returncode}; no credentials printed')
        return out.stdout
    identity=json.loads(run(['whoami','--as','bot']))
    encoded=json.dumps(identity)
    if APP not in encoded:raise SystemExit('Effective app identity not confirmed')
    spec=json.loads((ROOT/'docs/INPUT_BASE_CREATE_COMMAND_20260929.json').read_text(encoding='utf-8'))
    output=run(['base','+base-create','--as','bot','--name',spec['name'],'--table-name',spec['table_name'],
         '--time-zone','Asia/Taipei','--fields',json.dumps(spec['fields'],ensure_ascii=False),'--json','--dry-run'])
    # Dry-run has no authorization headers, but redact defensively before storing.
    for secret in (config['LARK_APP_SECRET'],):output=output.replace(secret,'[REDACTED]')
    (PRIVATE/'base-create-dryrun.json').write_text(output,encoding='utf-8')
    print(json.dumps({'ok':True,'app_id':APP,'profile':'workbench-input','config_directory':str(PRIVATE),
        'dry_run_only':True,'remote_created':False,'receipt':str(PRIVATE/'base-create-dryrun.json')}))


if __name__=='__main__':main()
