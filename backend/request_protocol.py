"""Timestamp bytes when uvicorn's transport delivers a new HTTP message.

This includes parser/task/worker queueing, not kernel or proxy time before the
transport callback can run. Event-loop lag is reported separately.
"""
from time import perf_counter
from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol


class TimedHttpToolsProtocol(HttpToolsProtocol):
    def data_received(self, data):
        self._received_at = perf_counter()
        super().data_received(data)

    def on_message_begin(self):
        super().on_message_begin()
        self.scope['request_received_at'] = self._received_at


if __name__ == '__main__':
    import uvicorn
    from uvicorn.config import HTTP_PROTOCOLS
    HTTP_PROTOCOLS['httptools'] = 'backend.request_protocol:TimedHttpToolsProtocol'
    uvicorn.main()
