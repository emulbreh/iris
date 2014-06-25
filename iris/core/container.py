import errno
import json
import gevent
import gevent.queue
import gevent.pool
import hashlib
import logging
import random
import os
import six
import sys
import zmq.green as zmq

from iris.exceptions import RegistrationFailure, SocketNotCreated
from iris.core.connection import Connection
from iris.core.channels import RequestChannel, ReplyChannel
from iris.core.events import Event
from iris.core.messages import Message
from iris.core.monitoring import Monitor
from iris.core.services import ServiceInstance
from iris.core.interfaces import DefaultInterface
from iris.core.plugins import Hook
from iris.core import trace


logger = logging.getLogger(__name__)


def create_container(config):
    registry = config.create_instance('registry')
    event_system = config.create_instance('event_system')
    container = config.create_instance(
        'container',
        default_class='iris.core.container:ServiceContainer',
        registry=registry,
        events=event_system,
    )
    return container


class ServiceContainer(object):
    def __init__(self, ip='127.0.0.1', port=None, registry=None, logger=None, events=None, node_endpoint=None, log_endpoint=None):
        self.zctx = zmq.Context.instance()
        self.ip = ip
        self.port = port
        self.node_endpoint = node_endpoint
        self.log_endpoint = log_endpoint
        self.endpoint = None
        self.bound = False

        self.recv_loop_greenlet = None
        self.channels = {}
        self.connections = {}
        self.pool = trace.Group()
        self.service_registry = registry
        self.event_system = events

        self.bind()
        self.identity = hashlib.md5(self.endpoint.encode('utf-8')).hexdigest()
        self.installed_services = {}
        self.installed_plugins = []
        self.error_hook = Hook()

        self.monitor = Monitor(self)

        self.install(DefaultInterface)
        registry.install(self)
        if events:
            events.install(self)

    def spawn(self, func, *args, **kwargs):
        return self.pool.spawn(func, *args, **kwargs)

    @classmethod
    def from_config(cls, config, **explicit_kwargs):
        kwargs = dict(config)
        kwargs.pop('class', None)
        kwargs.setdefault('node_endpoint', os.environ.get('IRIS_NODE'))
        for key, value in six.iteritems(explicit_kwargs):
            if value is not None:
                kwargs[key] = value
        return cls(**kwargs)

    def install(self, cls, **kwargs):
        obj = cls(self, **kwargs)
        self.installed_services[obj.service_type] = obj
        return obj

    def install_plugin(self, cls, **kwargs):
        plugin = cls(self, **kwargs)
        self.installed_plugins.append(plugin)

    def stats(self):
        hub = gevent.get_hub()
        threadpool, loop = hub.threadpool, hub.loop
        s = {
            'endpoint': self.endpoint,
            'identity': self.identity,
            'greenlets': len(self.pool),
            'gevent': {
                'threadpool': {
                    'size': threadpool.size,
                    'maxsize': threadpool.maxsize,
                },
                'active': loop.activecnt,
                'pending': loop.pendingcnt,
                'iteration': loop.iteration,
                'depth': loop.depth,
            },
            'connections': [c.stats() for c in self.connections.values()],
        }
        for name, interface in six.iteritems(self.installed_services):
            s[name] = interface.stats()
        return s

    def get_shared_socket_fd(self, port):
        fds = json.loads(os.environ.get('IRIS_SHARED_SOCKET_FDS', '{}'))
        try:
            return fds[str(port)]
        except KeyError:
            raise SocketNotCreated

    def bind(self, max_retries=2, retry_delay=0):
        if self.bound:
            raise TypeError('this container is already bound (endpoint=%s)', self.endpoint)
        self.send_sock = self.zctx.socket(zmq.ROUTER)
        self.recv_sock = self.zctx.socket(zmq.ROUTER)
        port = self.port
        retries = 0
        while True:
            if not self.port:
                port = random.randint(35536, 65536)
            try:
                self.endpoint = 'tcp://%s:%s' % (self.ip, port)
                endpoint = self.endpoint.encode('utf-8')
                self.recv_sock.setsockopt(zmq.IDENTITY, endpoint)
                self.send_sock.setsockopt(zmq.IDENTITY, endpoint)
                self.recv_sock.bind(self.endpoint)
            except zmq.ZMQError as e:
                if e.errno != errno.EADDRINUSE or retries >= max_retries:
                    raise
                logger.info('failed to bind to port %s (errno=%s), trying again.', port, e.errno)
                retries += 1
                if retry_delay:
                    gevent.sleep(retry_delay)
                continue
            else:
                self.port = port
                self.bound = True
                break

    def close_sockets(self):
        self.recv_sock.close()
        self.send_sock.close()

    @property
    def service_types(self):
        return self.installed_services.keys()

    def subscribe(self, event_type):
        self.event_system.subscribe(self, event_type)

    def start(self, register=True):
        self.running = True
        logger.info('starting %s at %s (pid=%s)', ', '.join(self.service_types), self.endpoint, os.getpid())
        self.recv_loop_greenlet = self.spawn(self.recv_loop)
        self.monitor.start()
        self.service_registry.on_start()
        self.event_system.on_start()

        for service in six.itervalues(self.installed_services):
            service.on_start()
            service.configure({})

        if register:
            for service_type, service in six.iteritems(self.installed_services):
                if not service.register_with_coordinator:
                    continue
                try:
                    self.service_registry.register(self, service_type)
                except RegistrationFailure:
                    logger.info("registration failed %s, %s", service_type, service)
                    self.stop()

        for interface in six.itervalues(self.installed_services):
            for pattern, handler in type(interface).event_dispatcher:
                self.subscribe(pattern)

    def stop(self):
        self.running = False
        for service in six.itervalues(self.installed_services):
            service.on_stop()
        self.event_system.on_stop()
        self.service_registry.on_stop()
        self.monitor.stop()
        for connection in list(self.connections.values()):
            connection.close()
        self.recv_loop_greenlet.kill()
        self.pool.kill()
        self.close_sockets()

    def join(self):
        self.pool.join()
        self.recv_loop_greenlet.join()

    def connect(self, endpoint):
        if endpoint not in self.connections:
            logger.debug("connect(%s)", endpoint)
            self.connections[endpoint] = Connection(self, endpoint)
            self.send_sock.connect(endpoint)
            for service in six.itervalues(self.installed_services):
                service.on_connect(endpoint)
            gevent.sleep(0.02)
        return self.connections[endpoint]

    def disconnect(self, endpoint, socket=False):
        try:
            connection = self.connections[endpoint]
        except KeyError:
            return
        del self.connections[endpoint]
        connection.close()
        logger.debug("disconnect(%s)", endpoint)
        if socket:
            self.send_sock.disconnect(endpoint)
        for service in six.itervalues(self.installed_services):
            service.on_disconnect(endpoint)

    def lookup(self, address):
        if address.startswith('iris://'):
            service_type = address[7:]
            return self.service_registry.get(self, service_type)
        return ServiceInstance(self, address)

    def discover(self):
        return self.service_registry.discover(self)

    def send_message(self, address, msg):
        if not self.running:
            logger.info('cannot send message (container not started): %s', msg)
            return
        service = self.lookup(address)
        try:
            connection = service.connect()
        except Exception:
            return
        self.send_sock.send(connection.endpoint.encode('utf-8'), flags=zmq.SNDMORE)
        self.send_sock.send_multipart(msg.pack_frames())
        logger.debug('-> %s to %s %r', msg, connection.endpoint, msg.headers)
        connection.on_send(msg)

    def prepare_headers(self, headers):
        headers = headers or {}
        headers.setdefault('trace_id', trace.get_id())
        return headers

    def send_request(self, address, subject, body, headers=None):
        msg = Message(
            msg_type=Message.REQ,
            subject=subject,
            body=body,
            source=self.endpoint,
            headers=self.prepare_headers(headers),
        )
        reply_channel = ReplyChannel(msg, self)
        self.channels[msg.id] = reply_channel
        self.send_message(address, msg)
        return reply_channel

    def send_reply(self, msg, body, msg_type=Message.REP, headers=None):
        reply_msg = Message(
            msg_type=msg_type,
            subject=msg.id,
            body=body,
            source=self.endpoint,
            headers=self.prepare_headers(headers),
        )
        self.send_message(msg.source, reply_msg)
        return reply_msg

    def dispatch_request(self, msg):
        channel = RequestChannel(msg, self)
        service_name, func_name = msg.subject.rsplit('.', 1)
        try:
            service = self.installed_services[service_name]
        except KeyError:
            logger.warning('unsupported service type: %s', service_name)
            return
        try:
            service.handle_request(func_name, channel)
        except Exception:
            logger.exception('')
            exc_info = sys.exc_info()
            try:
                self.error_hook(exc_info)
            except:
                logger.exception('error hook failure')
            finally:
                del exc_info
            try:
                channel.nack(True)
            except:
                logger.exception('failed to send automatic NACK')

    def recv_message(self, msg):
        trace.set_id(msg.headers.get('trace_id'))
        logger.debug('<- %s %r', msg, msg.headers)
        connection = self.connect(msg.source)
        connection.on_recv(msg)
        if msg.is_request():
            self.spawn(self.dispatch_request, msg)
        elif msg.is_reply():
            try:
                channel = self.channels[msg.subject]
            except KeyError:
                logger.debug('reply to unknown subject: %s (msg-id=%s)', msg.subject, msg.id)
                return
            channel.recv(msg)
        else:
            logger.warning('unknown message type: %s (msg-id=%s)', msg.type, msg.id)

    def recv_loop(self):
        while True:
            frames = self.recv_sock.recv_multipart()
            try:
                msg = Message.unpack_frames(frames)
            except ValueError as e:
                msg_id = frames[1] if len(frames) >= 2 else None
                logger.warning('bad message format %s: %r (msg-id=%s)', e, (frames), msg_id)
                continue
            self.recv_message(msg)

    def emit_event(self, event_type, payload):
        event = Event(event_type, payload, source=self.identity)
        self.event_system.emit(self, event)

    def handle_event(self, event):
        if not event.evt_type:
            logger.warning("dropping event without type: %r", event)
            return
        self.spawn(self.dispatch_event, event)

    def dispatch_event(self, event):
        handled = False
        for interface in six.itervalues(self.installed_services):
            if interface.dispatch_event(event):
                handled = True
        if not handled:
            logger.warning("unhandled event: %r", event)

    def ping(self, address):
        return self.send_request(address, 'iris.ping', {'payload': ''})
