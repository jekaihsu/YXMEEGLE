"""The cold-open benchmark must fail loudly instead of reporting numbers for a flow that did not fully succeed."""
import threading

import pytest

from scripts import benchmark_cold_open as rig


class Reply:
    def __init__(self, status):
        self.status_code = status
        self.headers = {'server-timing': 'total;dur=1'}


class Client:
    """Answers 200 for every endpoint except the one told to misbehave."""

    def __init__(self, fail=None, how='500', only_in_threads=False):
        self.fail, self.how, self.only_in_threads = fail, how, only_in_threads
        self.calls = 0
        self.names = {path: name for name, path in rig.flow_for('p1').items()}

    def get(self, path):
        self.calls += 1
        name = self.names[path]
        threaded = threading.current_thread() is not threading.main_thread()
        if name == self.fail and (threaded or not self.only_in_threads):
            if self.how == 'raise':
                raise RuntimeError('boom')
            return Reply(int(self.how))
        return Reply(200)


def run(client, flow=None, iterations=2):
    return rig.measure(client, flow or rig.flow_for('p1'), iterations, lambda: 0)


def test_a_flow_where_every_endpoint_succeeds_reports_all_five_in_every_section():
    result = run(Client())
    assert list(result['cold_serial_ms']) == list(rig.ENDPOINTS) == list(result['warm_serial_ms'])
    assert result['cold_burst_wall_ms']['n'] == result['warm_burst_wall_ms']['n'] == 2


@pytest.mark.parametrize('endpoint', rig.ENDPOINTS)
@pytest.mark.parametrize('how', ['500', '404', '302', 'raise'])
def test_any_endpoint_that_errors_fails_the_run_and_is_named(endpoint, how):
    with pytest.raises(rig.BenchmarkFailure, match=endpoint):
        run(Client(fail=endpoint, how=how))


@pytest.mark.parametrize('endpoint', rig.ENDPOINTS)
def test_an_error_only_inside_a_burst_thread_is_not_swallowed(endpoint):
    client = Client(fail=endpoint, how='raise', only_in_threads=True)
    with pytest.raises(rig.BenchmarkFailure, match=endpoint):
        run(client)
    status = Client(fail=endpoint, how='500', only_in_threads=True)
    with pytest.raises(rig.BenchmarkFailure, match='HTTP 500'):
        run(status)


def test_a_burst_needs_exactly_the_five_endpoints():
    flow = rig.flow_for('p1')
    with pytest.raises(rig.BenchmarkFailure, match='exactly'):
        run(Client(), {name: path for name, path in flow.items() if name != 'progress'})
    with pytest.raises(rig.BenchmarkFailure, match='exactly'):
        run(Client(), {**flow, 'extra': flow['project']})


def test_the_command_exits_non_zero_with_a_clear_message_when_an_endpoint_fails(capsys):
    with pytest.raises(SystemExit) as stop:
        rig.main(['1'], build=lambda: (Client(fail='sop-tasks', how='500'), 'p1'))
    assert stop.value.code == 1
    assert 'BENCHMARK FAILED' in capsys.readouterr().err
    rig.main(['1'], build=lambda: (Client(), 'p1'))
    assert 'COLD_OPEN' in capsys.readouterr().out
