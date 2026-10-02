"""Run a Playwright CLI code file without PowerShell rewriting JavaScript quotes."""
import argparse
from pathlib import Path
import subprocess
import sys
import re
sys.stdout.reconfigure(encoding='utf-8')

def public_output(value):
    # CLI appends all tabs, including unrelated user OAuth callbacks. Return
    # only the requested operation's result/error, never the tab inventory.
    value=re.split(r'^### (?:Ran Playwright code|Open tabs|Page)\b',value,maxsplit=1,flags=re.M)[0]
    return re.sub(r'([?&](?:access_token|refresh_token|code|state)=)[^\s&"<>]+',r'\1[REDACTED]',value,flags=re.I)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('session')
    parser.add_argument('file')
    args = parser.parse_args()
    code = Path(args.file).read_text(encoding='utf-8')
    cli = next((Path.home()/'AppData/Local/npm-cache/_npx').glob('*/node_modules/@playwright/cli/playwright-cli.js'))
    result = subprocess.run(['node', str(cli), '-s='+args.session, 'run-code', code], capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(public_output(result.stdout))
    print(public_output(result.stderr))
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
