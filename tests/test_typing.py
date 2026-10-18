import inspect
import typing

import pytest

import proxylib

# first_working_proxy names Proxy only for type checkers: proxy.py imports
# netutils, so netutils cannot import proxy at run time.
_UNRESOLVABLE = {"first_working_proxy"}


def _public_callables():
    for name in proxylib.__all__ if hasattr(proxylib, "__all__") else dir(proxylib):
        obj = getattr(proxylib, name, None)
        if name.startswith("_") or obj is None or name in _UNRESOLVABLE:
            continue
        if inspect.isclass(obj):
            for attr, member in vars(obj).items():
                # Unwrapped first: a staticmethod object is not callable before 3.10.
                member = getattr(member, "__func__", member)
                if callable(member) and (not attr.startswith("_") or attr == "__init__"):
                    yield f"{name}.{attr}", member
        elif callable(obj):
            yield name, obj


@pytest.mark.parametrize("name, func", list(_public_callables()))
def test_public_annotations_resolve_on_every_supported_python(name, func):
    typing.get_type_hints(func)
