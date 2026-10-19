"""The ``importpatch`` entry point of ``proxylib[patch]``: installs proxylib's
integration for a client (``requests``, ``urllib.request``) as soon as the
client is imported, in any program of the environment.

Disable it in ``pyimportpatch.cfg`` with ``proxylib.integrations.autopatch =
false`` under the client's section, or everywhere with
``PROXYLIB_AUTO_PATCH=0``.
"""

from __future__ import annotations

from types import ModuleType

__all__ = ("importpatch",)


def importpatch(name: str, module: ModuleType) -> None:
    """Called by ``importpatch`` once module ``name`` has been imported."""
    from .. import patching

    patching._on_import(name)
