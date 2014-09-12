import hashlib
import logging
import collections

import lymph
import gevent

from lymph.core.declarations import declaration
from lymph.core.events import Event
from lymph.core.interfaces import Component


logger = logging.getLogger(__name__)


def serial_event(*event_types, **kwargs):
    def decorator(func):
        @declaration()
        def factory(interface):
            return SerialEventHandler(interface, func, event_types, **kwargs)
        return factory
    return decorator


class SerialEventHandler(Component):
    def __init__(self, interface, func, event_types, key=None, partition_count=12):
        self.zk = interface.container.service_registry.client
        self.interface = interface
        self.partition_count = partition_count
        self.key_func = key
        self.consumer_func = func
        self.consumers = collections.OrderedDict()

        def _consume(interface, event):
            self.consumer_func(self.interface, Event.deserialize(event['event']))

        for i in range(partition_count):
            queue = self.get_queue_name(i)
            e = lymph.event(queue, queue_name=queue, sequential=True, active=False)(_consume)
            handler = e.install(interface)
            self.consumers[handler] = interface.container.subscribe(handler, consume=False)
        self.partition = set()
        lymph.event(*event_types)(self.push).install(interface)

    def on_start(self):
        self.start()

    def get_queue_name(self, index):
        return '%s.%s' % (self.consumer_func.__name__, index)

    def push(self, interface, event):
        key = str(self.key_func(event))
        index = int(hashlib.md5(key).hexdigest(), 16) % self.partition_count
        logger.debug('PUBLISH %s %s', self.get_queue_name(index), event)
        self.interface.emit(self.get_queue_name(index), {'event': event.serialize()})

    def start(self):
        self.interface.container.spawn(self.loop)

    def loop(self):
        while True:
            logger.info('starting partitioner')
            partitioner = self.zk.SetPartitioner(
                path='/lymph/serializer',
                set=self.consumers.keys(),
                time_boundary=1,
            )
            while True:
                if partitioner.failed:
                    logger.error('partitioning failed')
                    break
                elif partitioner.release:
                    self.release_partition()
                    partitioner.release_set()
                elif partitioner.acquired:
                    self.update_partition(set(partitioner))
                    gevent.sleep(1)
                elif partitioner.allocating:
                    partitioner.wait_for_acquire()

    def release_partition(self):
        for handler in self.partition:
            self.stop_consuming(handler)
        self.partition = set()

    def update_partition(self, partition):
        for queue in self.partition - partition:
            self.stop_consuming(queue)
        for queue in partition - self.partition:
            self.start_consuming(queue)
        if partition != self.partition:
            logger.info('partition: %s', ', '.join(h.queue_name for h in partition))
        self.partition = partition

    def start_consuming(self, handler):
        logger.debug("SUBSCRIBE %s %s %s", self.interface.container.identity[:10], handler.queue_name, id(self.consumers[handler]))
        self.consumers[handler].start()

    def stop_consuming(self, handler):
        logger.debug("UNSUBSCRIBE %s %s %s", self.interface.container.identity[:10], handler.queue_name, id(self.consumers[handler]))
        self.consumers[handler].stop()