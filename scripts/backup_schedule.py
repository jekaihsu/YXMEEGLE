"""Daily immutable backup with 30-day / 12-month retention.

Run with --once from a scheduler, or as a separate service. BACKUP_DIR must be
an independently protected mounted destination, outside the upload directory.
No remote source documents are deleted by this script.
"""
import argparse
import os
import time
import json
import secrets
import shutil
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from .backup_restore import backup, engine_for, validate_archive
except ImportError:
    from backup_restore import backup, engine_for, validate_archive
try:
    from .backup_publish import publish
except ImportError:
    from backup_publish import publish


def snapshot_stats(paths):
    return {p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in paths if p.is_file() and not p.is_symlink()}


def local_retention(destination,clock):
    # Only invoked after today's archive has been fully verified, even when
    # remote backup fails. Never remove uncertain remote checkpoints here.
    cutoff=(clock-timedelta(days=29)).date()
    month=(clock.year*12+clock.month-1-11)
    oldest=f'{month//12:04d}-{month%12+1:02d}'
    for path in destination.glob('yx-*.zip'):
        if path.is_symlink() or not path.resolve().is_relative_to(destination):continue
        try:
            expired=(path.name.startswith('yx-daily-') and datetime.strptime(path.stem[9:],'%Y-%m-%d').date()<cutoff) or (
                path.name.startswith('yx-monthly-') and datetime.strptime(path.stem[11:],'%Y-%m') and path.stem[11:]<oldest)
        except ValueError:continue
        if expired:path.unlink()

def tick(clock=None):
    clock=clock or datetime.now(timezone(timedelta(hours=8)))
    destination=Path(os.environ['BACKUP_DIR']).resolve()
    uploads=Path(os.getenv('UPLOAD_DIR','./data/uploads')).resolve()
    if destination==uploads or destination.is_relative_to(uploads): raise ValueError('Backup destination must be separate from uploads')
    destination.mkdir(parents=True,exist_ok=True)
    daily=destination/f'yx-daily-{clock:%Y-%m-%d}.zip'
    monthly=destination/f'yx-monthly-{clock:%Y-%m}.zip'
    cfg_hash=hashlib.sha256(json.dumps({k:v for k,v in os.environ.items() if k.startswith('BACKUP_')},sort_keys=True).encode()).hexdigest()
    try:
        prior=json.loads((destination/'status.json').read_text())
        age=(clock-datetime.fromisoformat(prior.get('last_full_checked_at',prior['last_checked_at']))).total_seconds()
        if (prior['status']=='ok' and prior.get('config_hash')==cfg_hash and prior.get('daily')==daily.name
                and prior.get('monthly')==monthly.name and len(prior.get('snapshot_stats',{}))==2
                and prior['snapshot_stats']==snapshot_stats((daily,monthly)) and 0<=age<86400):
            from scripts.backup_offsite import atomic_json
            prior['last_checked_at']=clock.isoformat()  # Cheap scheduler heartbeat, not new remote verification.
            atomic_json(destination/'status.json',prior)
            return
        if (prior['status']=='error' and prior.get('config_hash')==cfg_hash
                and prior.get('daily')==daily.name and 0<=age<900):
            return  # Bounded failure retry; never renew a failed verification.
    except (OSError,ValueError,KeyError,TypeError):pass
    # A failed/uncertain bundle is retained for reconciliation, but cannot grow
    # without bound by generating a new snapshot every day.
    minimum=int(os.getenv('BACKUP_MIN_FREE_BYTES',str(512*1024*1024)))
    maximum=int(os.getenv('BACKUP_MAX_LOCAL_BYTES',str(20*1024*1024*1024)))
    used=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file() and not p.is_symlink())
    if not daily.exists() and (shutil.disk_usage(destination).free<minimum or used>=maximum):
        from scripts.backup_offsite import atomic_json
        atomic_json(destination/'status.json',{'status':'error','last_checked_at':clock.isoformat(),'offsite':{'status':'capacity_blocked','encrypted':True}})
        raise ValueError('Backup capacity limit reached; reconcile retained bundles')
    engine=engine_for(os.environ['DATABASE_URL'])
    try:
        daily=destination/f'yx-daily-{clock:%Y-%m-%d}.zip'
        if daily.exists():
            try: validate_archive(daily)
            except Exception:
                daily.rename(daily.with_name(daily.name+'.invalid-'+secrets.token_hex(4)))
        if not daily.exists(): backup(engine,uploads,daily)
        daily_manifest=validate_archive(daily)
        monthly=destination/f'yx-monthly-{clock:%Y-%m}.zip'
        if monthly.exists():
            try: validate_archive(monthly)
            except Exception:
                monthly.rename(monthly.with_name(monthly.name+'.invalid-'+secrets.token_hex(4)))
        if not monthly.exists():
            temporary=monthly.with_name(monthly.name+'.partial-'+secrets.token_hex(4))
            try:
                with daily.open('rb') as source,temporary.open('xb') as target:
                    shutil.copyfileobj(source,target); target.flush(); os.fsync(target.fileno())
                validate_archive(temporary); publish(temporary,monthly)
            finally: temporary.unlink(missing_ok=True)
        offsite={'status':'not_configured','encrypted':False}
        if os.getenv('BACKUP_OFFSITE_ENABLED')=='true':
            try:
                from .backup_offsite import replicate,prune,settings,backup_adapter
            except ImportError:
                from backup_offsite import replicate,prune,settings,backup_adapter
            adapter=None
            try:
                settings(os.environ)  # Validate before acquiring any credentials.
                adapter=backup_adapter(dict(os.environ))
                copies=[replicate(path,destination/'.offsite',os.environ,adapter) for path in (daily,monthly)]
                prune(destination/'.offsite',os.environ,adapter,clock)
                offsite={'status':'verified','encrypted':True,'last_verified_at':copies[-1]['verified_at']}
            except Exception:
                # Record failure immediately; a previous green status is not
                # evidence that this offsite copy succeeded.
                failed=destination/('status.json.partial-'+secrets.token_hex(4))
                failed.write_text(json.dumps({'status':'error','last_success_at':daily_manifest['created_at'],
                    'last_checked_at':clock.isoformat(),'last_full_checked_at':clock.isoformat(),'config_hash':cfg_hash,
                    'daily':daily.name,'offsite':{'status':'error','encrypted':True}}),encoding='utf-8')
                failed.replace(destination/'status.json')
                local_retention(destination,clock)
                raise
            finally:
                if adapter is not None:adapter.client.close()
        local_retention(destination,clock)
        status=destination/'status.json'; temporary=destination/('status.json.partial-'+secrets.token_hex(4))
        temporary.write_text(json.dumps({'status':'ok','last_success_at':daily_manifest['created_at'],'last_checked_at':clock.isoformat(),'last_full_checked_at':clock.isoformat(),'daily':daily.name,'monthly':monthly.name,'offsite':offsite,'config_hash':cfg_hash,'snapshot_stats':snapshot_stats((daily,monthly))}),encoding='utf-8')
        temporary.replace(status)
    finally: engine.dispose()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    while True:
        try: tick()
        except Exception as exc:
            print(json.dumps({'component':'backup','status':'error','error_type':type(exc).__name__}),flush=True)
            if args.once: raise
        if args.once:break
        time.sleep(60)
