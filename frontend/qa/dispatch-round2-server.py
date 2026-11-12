"""Run the real dispatch dev server with a pre-write timeout for recovery QA."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('dispatch_dev', ROOT / 'scripts/dev_dispatch_fake_server.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
dev.FAULTS += ('timeout_before_landing',)
original_seed = dev.seed_lark


def seed_lark(fake, today):
    from backend.test_dispatch_publish_fake import TASKS
    original_seed(fake, today)
    fake.add(TASKS, 'recObligationQA', {'標題': 'QA 父義務', '任務種類': '義務', '專案編號': 'SYN-001'})
    fake.tables[TASKS]['recLegacy']['父義務'] = ['recObligationQA']


dev.seed_lark = seed_lark
original_call = dev.Faults.__call__


def fault_call(self, request):
    parts = request.url.path.split('/')
    task = len(parts) > 7 and parts[7] == self.tasks
    write = task and ((request.method == 'POST' and parts[8:] == ['records'])
                      or (request.method == 'PUT' and len(parts) == 10))
    if write and self._take('timeout_before_landing'):
        import httpx
        raise httpx.ReadTimeout('QA timeout before the write landed', request=request)
    return original_call(self, request)


dev.Faults.__call__ = fault_call
if __name__ == '__main__':
    dev.main()
