import logging

_STANDARD_ATTRS = frozenset({
    'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
    'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
    'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
    'processName', 'process', 'taskName', 'message', 'asctime',
})


class ExtraFormatter(logging.Formatter):
    def __init__(self, format=None, datefmt=None, style='%', **kwargs):
        super().__init__(fmt=format, datefmt=datefmt, style=style, **kwargs)

    def format(self, record):
        base = super().format(record)
        extras = {
            key: value for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS
        }
        if not extras:
            return base
        extra_str = ' '.join(f'{key}={value}' for key, value in sorted(extras.items()))
        return f'{base} | {extra_str}'
