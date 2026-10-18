"""The helper process a PAC script runs in.

A script that never returns can only be stopped by ending its process: dukpy
holds the GIL while it runs and cannot be interrupted, and quickjs's time
limit forbids calls into the Python PAC builtins. The parent
(``script._Runner``) talks to this process over stdin/stdout with
length-prefixed pickles: ``("init", engine, source, functions, memory)`` and
``("call", url, host)``, each answered with ``("ok", value)`` or
``("err", message)``; the helper says ``("ok", "ready")`` once started.
"""

from __future__ import annotations

import pickle
import struct
import sys
from typing import Any, BinaryIO, Optional

_HEADER = struct.Struct(">I")


def write_frame(stream: BinaryIO, message: Any) -> None:
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(data)) + data)
    stream.flush()


def read_frame(stream: BinaryIO) -> "Optional[Any]":
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        return None
    (size,) = _HEADER.unpack(header)
    data = stream.read(size)
    if len(data) < size:
        return None
    return pickle.loads(data)


def main() -> None:
    requests, replies = sys.stdin.buffer, sys.stdout.buffer
    # Anything the script's Python callbacks print must not corrupt the pipe.
    sys.stdout = sys.stderr
    from . import engines
    from ._functions import functions as builtins

    engine = None
    write_frame(replies, ("ok", "ready"))
    while True:
        try:
            message = read_frame(requests)
        except Exception as exc:  # e.g. a function= the helper cannot import
            write_frame(replies, ("err", f"{type(exc).__name__}: {exc}"))
            continue
        if message is None:
            return
        try:
            if message[0] == "init":
                _, engine_name, source, extra, memory = message
                engine = engines._load(engine_name)()
                engine.set_memory_limit(memory)
                for name, func in {**builtins, **extra}.items():
                    engine.export_function(name, func)
                engine.eval(source)
                if engine.eval("typeof FindProxyForURL") != "function":
                    raise ValueError("the script defines no FindProxyForURL function")
                write_frame(replies, ("ok", None))
            elif message[0] == "call":
                _, url, host = message
                write_frame(replies, ("ok", engine.call("FindProxyForURL", url, host)))
            else:
                return
        except Exception as exc:
            write_frame(replies, ("err", f"{type(exc).__name__}: {exc}"))
