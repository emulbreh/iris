.. currentmodule:: lymph.core.container


Core API
========


.. class:: ServiceContainer

    .. classmethod:: from_config(config, **kwargs)

    .. method:: start()

    .. method:: stop()

    .. method:: send_message(address, msg)

        :param address: the address for this message; either a ZeroMQ endpoint a service name
        :param msg: the :class:`lymph.core.messages.Message` object that will be sent
        :return: :class:`lymph.core.channels.ReplyChannel`

    .. method:: lookup(address)

        :param address: an lymph address
        :return: :class:`lymph.core.services.Service` or :class:`lymph.core.services.ServiceInstance`


.. currentmodule:: lymph.core.channels

.. class:: ReplyChannel()

    .. method:: reply(body)

        :param body: a JSON serializable data structure

    .. method:: ack()

        acknowledges the request message


.. class:: RequestChannel()

    .. method:: get(timeout=1)

        :return: :class:`lymph.core.messages.Message`

        returns the next reply message from this channel. Blocks until the reply
        is available. Raises :class:`Timeout <lymph.exceptions.Timeout>` after ``timeout`` seconds.


.. currentmodule:: lymph.core.messages

.. class:: Message

    .. attribute:: id

    .. attribute:: type

    .. attribute:: subject

    .. attribute:: body

    .. attribute:: packed_body


.. currentmodule:: lymph.core.events

.. class:: Event

    .. attribute:: type

        the event type / name

    .. attribute:: body

        dictionary with the payload of the message

    .. attribute:: source

        id of the event source service

    .. method:: __getitem__(name)

        gets an event parameter from the body


.. currentmodule:: lymph.core.services


.. class:: Service()

    Normally created by :meth:`ServiceContainer.lookup() <lymph.core.container.ServiceContainer.lookup()>`.
    Service objects represent lymph services.

    .. method:: __iter__()

        Yields all known :class:`instances <ServiceInstance>` of this service.

    .. method:: __len__()

        Returns the number of known instances of this service.


.. class:: ServiceInstance()

    Describes a single service instance.
    Normally created by :meth:`ServiceContainer.lookup() <lymph.core.container.ServiceContainer.lookup()>`

    .. attribute:: identity

        The identity string of this service instance

    .. attribute:: endpoint

        The rpc endpoint of this service instance


.. currentmodule:: lymph.core.connections

.. class:: Connection

    .. attribute:: endpoint
    
        The rpc endpoint this connection is to.


.. currentmodule:: lymph.core.interfaces

.. class:: Proxy(container, address, namespace=None, timeout=1)

    .. method:: __getattr__(self, name)

        Returns a callable that will execute the RPC method with the given name.

