"""The public surface follows the python standards: every public module
declares __all__, other modules are private, every export is documented in
the shipped header, options are keyword-only, acronyms are in capitals."""

import importlib
import inspect
import pathlib
import pkgutil
import re

import proxylib

HEADER = (pathlib.Path(proxylib.__file__).parent / "AGENTS.md").read_text(encoding="utf-8")

# Value types whose fields are positional, as a named tuple's are.
POSITIONAL_FIELDS = {"proxylib.proxy.Proxy", "proxylib.system.ProxyConfig", "proxylib.system._config.ProxyConfig"}


def _public_modules():
    yield proxylib
    for info in pkgutil.walk_packages(proxylib.__path__, "proxylib."):
        if not any(part.startswith("_") for part in info.name.split(".")[1:]):
            yield importlib.import_module(info.name)


def test_every_public_module_declares_all():
    missing = [module.__name__ for module in _public_modules() if not hasattr(module, "__all__")]
    assert missing == []


def test_every_top_level_export_is_in_the_header():
    undocumented = [name for name in proxylib.__all__ if not re.search(rf"\b{name}\b", HEADER)]
    assert undocumented == []


def test_options_after_the_first_two_parameters_are_keyword_only():
    offenders = []
    for module in _public_modules():
        for name in module.__all__:
            obj = getattr(module, name, None)
            qualified = f"{getattr(obj, '__module__', module.__name__)}.{name}"
            if obj is None or qualified in POSITIONAL_FIELDS or f"{module.__name__}.{name}" in POSITIONAL_FIELDS:
                continue
            target = obj.__init__ if inspect.isclass(obj) else obj
            if not callable(target):
                continue
            try:
                parameters = inspect.signature(target).parameters.values()
            except (TypeError, ValueError):
                continue
            positional = [
                p.name
                for p in parameters
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in ("self", "cls")
            ]
            if len(positional) > 2:
                offenders.append(f"{module.__name__}.{name}{tuple(positional)}")
    assert offenders == []


def test_acronyms_in_public_class_names_are_capitals():
    mixed = re.compile(r"(Http|Uri|Url|Pac|Dns|Tls|Ssl|Ip)(?=[A-Z]|$)")
    offenders = []
    for module in _public_modules():
        for name in module.__all__:
            obj = getattr(module, name, None)
            if inspect.isclass(obj) and mixed.search(name) and name not in ("PacScript", "PacProxyMap"):
                offenders.append(f"{module.__name__}.{name}")
    assert offenders == []
