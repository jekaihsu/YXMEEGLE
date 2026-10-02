"""Supervise the web and durable worker as one container service.

Unexpected child exit stops the other child and fails this process so the hosting
platform can restart the complete service. Business retries remain in the worker.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def _signal_child(process, force=False):
    if process.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except ProcessLookupError:
        pass


def supervise(commands, *, stop_event=None, shutdown_timeout=10, poll_interval=0.2, readiness=None, startup_timeout=60):
    """Run named argv lists, returning zero only for requested shutdown."""
    stop_event = stop_event if stop_event is not None else threading.Event()
    children = []
    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda _signum, _frame: stop_event.set())
    try:
        if not commands:
            raise ValueError('At least one child service is required')
        for name, command in commands:
            if stop_event.is_set():
                return 0
            options = {'cwd': str(ROOT)}
            if os.name == 'posix':
                options['start_new_session'] = True
            elif os.name == 'nt':
                options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            # No shell interpolation; credentials are inherited through the
            # environment and neither commands nor environment values are logged.
            process = subprocess.Popen(command, **options)
            children.append((name, process))
            print(f'service child started: {name} pid={process.pid}', flush=True)
            check=(readiness or {}).get(name)
            deadline=time.monotonic()+startup_timeout
            while check and not stop_event.is_set():
                code=process.poll()
                if code is not None:
                    print(f'service child exited during startup: {name} status={code}',flush=True)
                    return code if 1 <= code <= 125 else 1
                if check(): break
                if time.monotonic()>=deadline:
                    print(f'service child startup deadline exceeded: {name}',flush=True)
                    return 1
                stop_event.wait(poll_interval)
        while not stop_event.is_set():
            for name, process in children:
                code = process.poll()
                if code is not None:
                    print(f'service child exited unexpectedly: {name} status={code}', flush=True)
                    return code if 1 <= code <= 125 else 1
            stop_event.wait(poll_interval)
        return 0
    except (OSError, ValueError) as exc:
        print(f'service startup failed: {type(exc).__name__}', flush=True)
        return 1
    finally:
        for _, process in children:
            _signal_child(process)
        deadline = time.monotonic() + shutdown_timeout
        for name, process in children:
            try:
                process.wait(timeout=max(0, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                print(f'service child exceeded shutdown deadline: {name}', flush=True)
                _signal_child(process, force=True)
                process.wait(timeout=5)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def web_ready(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as response:
            return response.status==200
    except (urllib.error.URLError,TimeoutError,OSError):
        return False


def drop_runtime_privileges():
    """Enforce the image's UID even when the hosting platform overrides USER."""
    if sys.platform!='linux' or os.getenv('APP_ENV')!='production':
        return
    if os.geteuid()!=0:
        return
    # Drop supplemental groups first; never repair ownership from application
    # startup. A failure aborts before either the web or worker is spawned.
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
    if os.getuid()!=10001 or os.geteuid()!=10001 or os.getgid()!=10001 or os.getegid()!=10001 or os.getgroups():
        raise RuntimeError('Runtime privilege drop did not take effect')


def main():
    try:
        drop_runtime_privileges()
    except (OSError,RuntimeError) as exc:
        print(f'service privilege initialization failed: {type(exc).__name__}',flush=True)
        return 1
    port = os.getenv('PORT', '8080')
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        print('service configuration error: invalid PORT', flush=True)
        return 1
    commands = [
        ('web', [sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '0.0.0.0', '--port', port, '--proxy-headers', '--forwarded-allow-ips='+os.getenv('FORWARDED_ALLOW_IPS','127.0.0.1'), '--no-access-log']),
        ('worker', [sys.executable, str(ROOT/'scripts'/'run_worker.py')]),
    ]
    if os.getenv('BACKUP_DIR'):
        commands.append(('backup',[sys.executable,str(ROOT/'scripts'/'backup_schedule.py')]))
    # Web initializes the schema during import. Wait for its DB-aware health
    # endpoint before starting the worker so an empty database has one creator.
    return supervise(commands,readiness={'web':lambda:web_ready(port)})


if __name__ == '__main__':
    raise SystemExit(main())
