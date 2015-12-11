import logging

import gevent

from kazoo.exceptions import KazooException
from kazoo.handlers.gevent import SequentialGeventHandler

from lymph.core.declarations import Declaration
from lymph.core.components import Component


logger = logging.getLogger(__name__)


class LeaderJob(Component):
    def __init__(self, interface, zkclient, func):
        super(LeaderJob, self).__init__()
        self.zk = zkclient
        self.interface = interface
        self.func = func
        self.running = False

    def on_start(self):
        super(LeaderJob, self).on_start()
        self.running = True
        self.spawn(self.run)

    def on_stop(self):
        super(LeaderJob, self).on_stop()
        self.running = False

    def run(self):
        lock = self.zk.Lock('/elections-%s-%s' % (self.interface.name, self.interface.version), self.interface.id)
        while self.running:
            try:
                with lock:
                    logger.info('became leader identity=%s', self.interface.container.identity)
                    while True:
                        self.func(self.interface)
            except KazooException:
                logger.debug('election failed', exc_info=True)
            gevent.sleep(0)


def leader():
    def decorator(func):
        def factory(interface):
            zk = interface.config.root.get_instance('components.Leader.zkclient', handler=SequentialGeventHandler())
            return LeaderJob(interface, zk, func)
        return Declaration(factory)
    return decorator
