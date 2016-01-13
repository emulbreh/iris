import json

from lymph.client import Client
from lymph.cli.base import Command
from lymph.core import trace


class EmitCommand(Command):
    """
    Usage: lymph emit <event-type> [<body>] [options]

    Emits an event in the event system

    Options:
      --trace-id=<trace_id>        Use the given trace_id.

    {COMMON_OPTIONS}
    """

    short_description = 'Emits an event in the event system'

    def run(self):
        event_type = self.args.get('<event-type>')
        body = json.loads(self.args.get('<body>'))

        client = Client.from_config(self.config)
        with trace.context(self.args.get('--trace-id')):
            client.emit(event_type, body)
