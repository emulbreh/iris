

def patch():
    if patch._initialized:
        return
    patch._initialized = True

    import gevent.monkey
    gevent.monkey.patch_all()

    import sys
    if sys.version_info.major < 3:
        _py2_patches()

    _export()
patch._initialized = False


def _export():
    import lymph
    lymph.__version__ = '0.1.0'

    from lymph.exceptions import RpcError, LookupFailure, Timeout
    from lymph.core.decorators import rpc, raw_rpc, event
    from lymph.core.interfaces import Interface
    from lymph.core.declarations import proxy

    for obj in (RpcError, LookupFailure, Timeout, rpc, raw_rpc, event, Interface, proxy):
        setattr(lymph, obj.__name__, obj)


def _py2_patches():
    import monotime  # NOQA
    if sys.version_info.minor == 7 and sys.version_info.micro >= 9:
        _py279_sslwrap_gevent_patches()


def _py279_sslwrap_gevent_patches():
    # See https://github.com/gevent/gevent/issues/477
    # Re-add sslwrap to Python 2.7.9
    import inspect
    __ssl__ = __import__('ssl')

    try:
        _ssl = __ssl__._ssl
    except AttributeError:
        _ssl = __ssl__._ssl2


    def new_sslwrap(sock, server_side=False, keyfile=None, certfile=None, cert_reqs=__ssl__.CERT_NONE, ssl_version=__ssl__.PROTOCOL_SSLv23, ca_certs=None, ciphers=None):
        context = __ssl__.SSLContext(ssl_version)
        context.verify_mode = cert_reqs or __ssl__.CERT_NONE
        if ca_certs:
            context.load_verify_locations(ca_certs)
        if certfile:
            context.load_cert_chain(certfile, keyfile)
        if ciphers:
            context.set_ciphers(ciphers)

        caller_self = inspect.currentframe().f_back.f_locals['self']
        return context._wrap_socket(sock, server_side=server_side, ssl_sock=caller_self)

    if not hasattr(_ssl, 'sslwrap'):
        _ssl.sslwrap = new_sslwrap
