#!/usr/bin/env python3
"""執行指定唯讀guard；輸出先沿用既有薪酬遮蔽器再附加至11號報告。"""
from datetime import datetime
import re
import subprocess
import sys

import db
import router
from privacy import hr_mask
from make_report import REPORT, MARKER


def mask_output(value):
    lines=[]
    for line in value.splitlines():
        prefix=re.match(r'\[(?:PASS|FAIL) CORR-\d{2}[^\]]*\]',line)
        masked=hr_mask(line)
        if prefix:
            masked=re.sub(r'^\[[^\]]*\]',lambda _m:prefix[0],masked,count=1)
        lines.append(masked)
    return '\n'.join(lines)+('\n' if value.endswith('\n') else '')


def main():
    command=['python3','/workspace/pstack_verify/preflight_guard.py']
    started=datetime.now(router.TZ).isoformat()
    process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    stdout,stderr=mask_output(process.stdout),mask_output(process.stderr)
    record={'command':command,'phase':'R30_INTEGRATION','started_at':started,'finished_at':datetime.now(router.TZ).isoformat(),
            'returncode':process.returncode,'passed':process.returncode==0,'stdout':stdout,'stderr':stderr,
            'scope_note':'已檢視guard與v3_role_matrix_guard；只有Lark list/get與ledger唯讀檢查，沒有Gmail/Lark寫入。全域guard不替代本機總機驗收。'}
    record['corr01_to09']={f'CORR-{i:02d}':{'passed':bool(re.search(r'\[PASS CORR-'+f'{i:02d}'+r'(?:\]|[a-z -])',process.stdout)) and not bool(re.search(r'\[FAIL CORR-'+f'{i:02d}'+r'(?:\]|[a-z -])',process.stdout))} for i in range(1,10)}
    record['requested_corr01_to09_passed']=all(
        re.search(r'\[PASS CORR-'+f'{i:02d}'+r'(?:\]|[a-z -])',process.stdout)
        and not re.search(r'\[FAIL CORR-'+f'{i:02d}'+r'(?:\]|[a-z -])',process.stdout)
        for i in range(1,10))
    db.dump(db.ROOT/'preflight_result.json',record)
    (db.ROOT/'preflight_output.txt').write_text(stdout+('\n[stderr]\n'+stderr if stderr else ''),encoding='utf-8')
    with REPORT.open('a',encoding='utf-8') as report:
        report.write(MARKER+'\nR30 整合；命令：`'+' '.join(command)+'`。開始：'+started+'；結束：'+record['finished_at']+'。\n\n退出碼：**'+str(process.returncode)+'**。'+record['scope_note']+'\n\n薪酬金額如有出現已遮蔽為[MASKED_HR_PRIVATE]。\n\n```text\n'+stdout+('\n[stderr]\n'+stderr if stderr else '')+'\n```\n')
    print('preflight_guard退出碼：'+str(process.returncode))
    return process.returncode


if __name__=='__main__':
    sys.exit(main())
