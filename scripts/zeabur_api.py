"""Use the authenticated local Zeabur account without exposing its token.

Request and response paths must be inside .runtime. This utility never prints
response values, because service environment values can contain credentials.
"""
import argparse
import json
from pathlib import Path
import httpx
import yaml
try:
    from .release_env_guard import validate_request
except ImportError:
    from release_env_guard import validate_request

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    runtime=(ROOT/'.runtime').resolve();runtime.mkdir(exist_ok=True)
    request=Path(args.request).resolve();output=Path(args.output).resolve()
    if not request.is_relative_to(runtime) or not output.is_relative_to(runtime):
        raise SystemExit('Only ignored .runtime request/response paths are accepted')
    payload=json.loads(request.read_text(encoding='utf-8'))
    try: validate_request(payload)
    except ValueError as exc: raise SystemExit(str(exc)) from None
    settings=yaml.safe_load((Path.home()/'.config/zeabur/cli.yaml').read_text(encoding='utf-8'))
    token=settings.get('token')
    if not token:raise SystemExit('Zeabur CLI is not authenticated')
    with httpx.Client(timeout=60) as client:
        response=client.post('https://api.zeabur.com/graphql',headers={'Authorization':'Bearer '+token},json=payload)
        result=response.json()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'http':response.status_code,'ok':not bool(result.get('errors')),
                      'result_keys':list((result.get('data') or {}).keys()),'response_file':str(output.relative_to(ROOT))}))

if __name__=='__main__':main()
