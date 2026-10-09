"""Self-checks used by `--smoke-test`.

This is the only module in the package allowed to import `socket`, and it does so only to
*block* connections (tests/test_security.py enforces that).
"""

from __future__ import annotations

import socket
from typing import Any


class NetworkTripwire:
    """Block and record every outbound Python-level socket connection in this process.

    Proves the app makes no network calls at runtime (CLAUDE.md §4.2). Native code that
    opened sockets directly would bypass it; the audit's process-level probe covers that
    (docs/SECURITY_AUDIT.md).
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def install(self) -> NetworkTripwire:
        tripwire = self

        def connect(sock: socket.socket, address: Any) -> None:
            tripwire.attempts.append(f"connect {address!r}")
            raise OSError("network blocked by Nodwell's smoke-test tripwire")

        def connect_ex(sock: socket.socket, address: Any) -> int:
            tripwire.attempts.append(f"connect_ex {address!r}")
            return 1

        def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
            tripwire.attempts.append(f"create_connection {address!r}")
            raise OSError("network blocked by Nodwell's smoke-test tripwire")

        socket.socket.connect = connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
        socket.create_connection = create_connection
        return self
