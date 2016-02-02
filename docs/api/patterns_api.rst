.. currentmodule:: lymph.patterns

Pattern API
===========

.. currentmodule:: lymph.patterns.serial_events

.. decorator:: serial_event(*event_types, partition_count=12, key=None)

    :param event_types: event types that should be partitioned
    :param partition_count: number of queues that should be used to partition the events
    :param key: a function that maps :class:`Events <lymph.core.events.Event>` to string keys.
        This function should have two arguments in its signature: the instance of
        current :class:`Interface <lymph.Interface>` and instance of the handled 
        :class:`Event <lymph.core.events.Event>` object.
    
    This event handler redistributes events into ``partition_count`` queues. 
    These queues are then partitioned over all service instances and consumed sequentially, 
    i.e. at most one event per queue at a time.
    
    .. image:: /_static/serial_event.svg
