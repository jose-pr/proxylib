import pytest

import proxylib
from proxylib.exceptions import (
    MissingExtraError,
    NoReachableProxyError,
    PACError,
    ProxylibError,
    ProxyParseError,
)


@pytest.mark.parametrize(
    "exc, bases",
    [
        (ProxyParseError, (ProxylibError, ValueError)),
        (PACError, (ProxylibError,)),
        (NoReachableProxyError, (ProxylibError, LookupError)),
        (MissingExtraError, (ProxylibError, ImportError)),
    ],
)
def test_exception_bases(exc, bases):
    assert all(issubclass(exc, base) for base in bases)


def test_no_exception_is_a_keyerror():
    # KeyError means "no opinion" in the ProxyMap contract.
    for name in proxylib.exceptions.__all__:
        assert not issubclass(getattr(proxylib.exceptions, name), KeyError)


def test_missing_extra_error_names_the_install_line():
    assert 'pip install "proxylib[pac]"' in str(MissingExtraError("PAC", name="quickjs", extra="pac"))
    assert "pip install requests" in str(MissingExtraError("ProxyMapAdapter", name="requests"))
