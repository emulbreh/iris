.. currentmodule:: lymph.core.trace


Trace API
=========

.. function:: context(trace_id=None)

    Returns a context manager that will set the trace id. 
    If ``trace_id`` is None, a new random id will be generated.
    

.. function:: get_id()

    Returns the current trace id.

