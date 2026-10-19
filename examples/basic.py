"""What proxy would this machine use? Prints the decision for a few URLs, and
how the OS settings read. Makes no request.

    python examples/basic.py https://example.com/ http://intranet/
"""

import sys

from proxylib import auto_proxy, lookup, system_config


def main(urls):
    print("OS settings:", system_config())
    proxymap = auto_proxy()
    try:
        for url in urls:
            answer = lookup(proxymap, url)
            print(url, "->", ", ".join(proxy.url if proxy else "DIRECT" for proxy in answer))
    finally:
        proxymap.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["https://example.com/"])
