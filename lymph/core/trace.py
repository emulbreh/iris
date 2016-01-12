import contextlib
import logging
import uuid

import gevent

from lymph.utils.gpool import NonBlockingPool
from lymph.core.plugins import Hook


logger = logging.getLogger(__name__)
enter_trace_hook = Hook()
exit_trace_hook = Hook()


def get_trace(greenlet=None):
    greenlet = greenlet or gevent.getcurrent()
    if not hasattr(greenlet, '_lymph_trace'):
        greenlet._lymph_trace = {}
    return greenlet._lymph_trace


class GreenletWithTrace(gevent.Greenlet):
    def __init__(self, *args, **kwargs):
        super(GreenletWithTrace, self).__init__(*args, **kwargs)
        self._lymph_trace = get_trace().copy()


class Group(NonBlockingPool):
    greenlet_class = GreenletWithTrace


def trace(**kwargs):
    get_trace().update(kwargs)


def set_id(trace_id=None):
    tid = trace_id or uuid.uuid4().hex
    trace(trace_id=tid)
    if trace_id is None:
        logger.debug('starting trace')
    return tid


def get_id():
    return get_trace().get('trace_id')


@contextlib.contextmanager
def from_headers(headers):
    trace(**headers.get('trace', {}))
    if 'trace_id' in headers:  # for backwards compatibility with lymph<=0.14
        set_id(headers['trace_id'])
    trace_id = get_id()
    enter_trace_hook(trace_id)
    yield
    get_trace().clear()
    exit_trace_hook(trace_id)


def get_headers():
    return {
        'trace': get_trace(),
        'trace_id': get_id(),  # for backwards compatibility with lymph<=0.14
    }


class TraceFormatter(logging.Formatter):
    def format(self, record):
        record.trace_id = get_id()
        return super(TraceFormatter, self).format(record)
