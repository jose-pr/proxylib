"""proxylib's ``importpatch`` entry point: installs proxylib's integration for
a client (``requests``, ``urllib.request``, ``httpx``, ``aiohttp``, pip's
vendored ``pip._vendor.requests``) as soon
as it is imported, in any program of the environment, as
``PROXYLIB_IMPORTPATCH`` and ``PROXYLIB_AUTOPROXY`` say (see
:mod:`proxylib.patching`).

Disable it per client in ``pyimportpatch.cfg`` with
``proxylib.integrations.autopatch = false`` under the client's section, or
everywhere with ``PROXYLIB_IMPORTPATCH=0``.
"""

from __future__ import annotations

from types import ModuleType

__all__ = ("importpatch",)


def importpatch(name: str, module: ModuleType) -> None:
    """Called by ``importpatch`` once module ``name`` has been imported."""
    from .. import patching

    patching._on_import(name)
