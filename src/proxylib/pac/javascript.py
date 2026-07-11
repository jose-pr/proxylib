"""Runs a PAC script as real JavaScript via a pluggable engine (``dukpy`` or
``quickjs`` -- see :mod:`proxylib.pac.engines`), exposing every ``PAC``
static/class method (and any subclass adds) into the JS global scope so
``FindProxyForURL`` can call them.
"""

from __future__ import annotations

from abc import ABCMeta
from typing import Callable, Dict, List, Optional, OrderedDict, Sequence

from .engines import get_engine_class

__all__ = ["JSContext"]


class JSContextMeta(ABCMeta):
    """Collects every alpha-leading attribute (methods) of a class and its
    bases into ``_JSCONTEXT``, the set of functions exported into the JS engine.
    """

    def __new__(
        metaclass: "type[JSContext]",
        cls_name: str,
        base_classes: Sequence[object],
        cls_builder: "OrderedDict[str, object]",
    ):
        jsContext: "Dict[str, object]" = cls_builder.pop("_JSCONTEXT", {})
        exclude: "List[str]" = cls_builder.get("_JSCONTEXT_EXCLUDE", [])
        for key, val in cls_builder.items():
            if key[0].isalpha():
                jsContext.setdefault(key, val)

        for cls in reversed(base_classes):
            exclude.extend(getattr(cls, "_JSCONTEXT_EXCLUDE", []))
            if hasattr(cls, "_JSCONTEXT"):
                update: dict = cls._JSCONTEXT
            else:
                update = {
                    key: getattr(cls, key) for key in dir(cls) if key[0].isalpha()
                }
            for key, val in update.items():
                jsContext.setdefault(key, staticmethod(val))

        return type.__new__(
            metaclass,
            cls_name,
            base_classes,
            {
                **{
                    key: val
                    for key, val in cls_builder.items()
                    if not (key[0].isalpha() and key not in exclude)
                },
                "_JSCONTEXT": {
                    key: val
                    for key, val in jsContext.items()
                    if (key[0].isalpha() and key not in exclude)
                },
            },
        )


class JSContext(metaclass=JSContextMeta):
    """Base class that boots a JS engine with ``_JSCONTEXT`` exported, then evals ``js``.

    The engine itself is pluggable (see :mod:`proxylib.pac.engines`) --
    this class only depends on the small :class:`~proxylib.pac.engines.base.JSEngine`
    interface (``export_function``/``eval``/``call``), not on any specific
    engine's API.
    """

    def __init__(self, js: str, overrides: "Optional[Dict[str, Callable]]" = None) -> None:
        context: dict = object.__getattribute__(self, "_JSCONTEXT")
        if overrides:
            context = dict(context)
            # Wrapped as staticmethod so the binding loop below treats them
            # exactly like the class's own PAC utility functions (unwrapped
            # via val.__func__, no `self` bound) -- overrides are plain
            # standalone callables (e.g. `lambda host: "10.0.0.1"`), not
            # instance methods, so val.__get__(self) below would wrongly
            # bind `self` as an implicit first argument otherwise.
            context.update({key: staticmethod(fn) for key, fn in overrides.items()})
            # Stored per-instance, not mutated on the shared class-level
            # _JSCONTEXT, so overrides from one instance don't leak into
            # another's -- __getattribute__ below picks this up too, so an
            # override key that isn't one of the base PAC methods is still
            # recognized as exported.
            object.__setattr__(self, "_JSCONTEXT", context)
        engine_cls = get_engine_class()
        if engine_cls is None:
            raise ImportError(
                "No PAC JS engine is installed -- install one of the optional "
                "extras: proxylib[jspac] (dukpy) or proxylib[quickjs]."
            )
        engine = engine_cls()
        for key, val in context.items():
            if isinstance(val, staticmethod):
                val = val.__func__
            elif isinstance(val, classmethod):
                val = val.__get__(self.__class__)
            elif isinstance(val, property):
                raise NotImplementedError("JSContext does not support property exports yet")
            else:
                val = val.__get__(self)

            engine.export_function(key, val)
        engine.eval(js)

        # Pre-bind one callable per exported name now, instead of allocating
        # a fresh closure on every attribute access. Each one still calls
        # engine.call(key, ...), which resolves `key` fresh in the JS
        # engine's *global scope* at call time (not at bind time) -- that's
        # what actually implements "JS override wins": if `js` redefined
        # `key`, the engine resolves to that redefinition regardless of
        # when this Python-side wrapper was created. A naive
        # `object.__setattr__(self, key, jsFunction)` here would never be
        # reached, though -- __getattribute__ below checks membership in
        # `context` *before* ever falling through to instance-attribute
        # lookup, so the bound callables live in their own dict instead.
        bound: "Dict[str, object]" = {}
        for key in context:

            def _make_js_function(key=key):
                def jsFunction(*args):
                    return engine.call(key, *args)

                return jsFunction

            bound[key] = _make_js_function()

        object.__setattr__(self, "_jsengine", engine)
        object.__setattr__(self, "_bound_js_functions", bound)

    def __getattribute__(self, name: str):
        context: dict = object.__getattribute__(self, "_JSCONTEXT")
        if name in context:
            bound: dict = object.__getattribute__(self, "_bound_js_functions")
            return bound[name]
        else:
            return object.__getattribute__(self, name)
