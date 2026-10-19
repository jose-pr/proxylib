import inspect
import typing

import pytest

import proxylib

def _public_callables():
    for name in proxylib.__all__:
        obj = getattr(proxylib, name)
        if inspect.isclass(obj):
            for attr, member in vars(obj).items():
                # Unwrapped first: a staticmethod object is not callable before 3.10.
                member = getattr(member, "__func__", member)
                if callable(member) and (not attr.startswith("_") or attr == "__init__"):
                    yield f"{name}.{attr}", member
        elif inspect.isfunction(obj):
            yield name, obj


@pytest.mark.parametrize("name, func", list(_public_callables()))
def test_public_annotations_resolve_on_every_supported_python(name, func):
    typing.get_type_hints(func)
