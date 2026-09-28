"""Where tools may download from (carry-forward SEC-S2). A page, a search API, a redirect or a model
chooses most of the links a tool follows, so every hop must lead to a public internet address: never
this computer or the local network, or `fetch` becomes a way to read the user's router, NAS or cloud
metadata, and its errors a LAN scanner. Only the link the user typed is let through, on its first hop.

Resolve-then-connect is best effort against DNS rebinding (the name could resolve differently a moment
later, when urllib connects)."""

import http.client
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial

from badshop.engine import assets
from badshop.engine.errors import EngineError
from badshop.tools.runner import is_trusted

LOCAL_HINT = ("badshop only downloads from public internet addresses; to use a picture from this computer "
              "or your own network, save it and import the file")
WEB_LINK = re.compile(r"https?://")  # what makes fetch treat its query as a link (sources.fetch)
NAT64 = ipaddress.IPv6Network("64:ff9b::/96")  # 64:ff9b::a.b.c.d reaches IPv4 a.b.c.d through a translator


def _hosts(url: str) -> list[str]:
    """Every host `url` can mean: the one urllib connects to (Request.host, then HTTPConnection's port
    split) and urlsplit's reading. They differ: urllib percent-decodes the host, so
    `http://%31%32%37.0.0.1/` connects to 127.0.0.1 while urlsplit reads "%31%32%37.0.0.1", which no
    resolver knows; urlsplit drops a `user@` that urllib keeps. Checking both leaves no gap between the
    parsers. Empty when neither finds a host (file:, data:, "http:///x")."""
    hosts = set()
    try:
        netloc = urllib.request.Request(url).host
        if netloc:
            hosts.add(http.client.HTTPConnection(netloc).host)  # no socket until connect()
    except (ValueError, http.client.InvalidURL):  # urllib refuses the link the same way
        pass
    try:
        hosts.add(urllib.parse.urlsplit(url).hostname or "")
    except ValueError:  # an unclosed IPv6 bracket
        pass
    return sorted(h for h in hosts if h)  # not lowercased: an IPv6 zone (fe80::1%ETH0) is case-sensitive


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:  # ::ffff:127.0.0.1 is 127.0.0.1 on a dual-stack socket
        ip = ip.ipv4_mapped
    elif ip.version == 6 and ip in NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFF_FFFF)
    local = (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
             or ip.is_unspecified or (ip.version == 6 and ip.is_site_local))
    return ip.is_global and not local  # is_global also rules out shared space 100.64/10 (CGNAT, Tailscale)


def refuse_private(url: str, trusted: frozenset[str] = frozenset()) -> None:
    """Raise EngineError when `url` leads to this computer or a non-public network: any address either
    reading of its host resolves to that is private, loopback, link-local, reserved, multicast or
    unspecified. A URL in `trusted` (the user typed it) passes; a redirect from it is a new URL and is
    checked. A host that doesn't resolve passes too: the request itself fails the same way."""
    if url in trusted:
        return
    for host in _hosts(url):
        try:
            found = socket.getaddrinfo(host, None, 0, socket.SOCK_STREAM)  # as socket.create_connection asks
        except (OSError, UnicodeError):  # gaierror is an OSError; a label over 63 characters, a UnicodeError
            continue
        for *_, sockaddr in found:
            try:
                public = _public(ipaddress.ip_address(sockaddr[0]))
            except ValueError:  # an address this module can't read is not known to be public
                public = False
            if not public:  # the resolved address stays out of the message: it would answer DNS for a model
                raise EngineError(f"refused {url[:60]}: it points into this computer or the local network",
                                  hint=LOCAL_HINT)


def policy_for(trusted: frozenset[str] = frozenset()) -> Callable[[str], None]:
    """refuse_private with `trusted` bound: the shape assets.URL_POLICY takes."""
    return partial(refuse_private, trusted=frozenset(trusted))


@contextmanager
def guarded(trusted: frozenset[str] = frozenset()) -> Iterator[None]:
    """Install the policy as assets.URL_POLICY for the block, so every download, redirect hop and asset
    fetch is checked, then put back whatever was there. URL_POLICY is process-wide: one tool call runs
    at a time in a process (the session's lock, or the worker's single child)."""
    previous = assets.URL_POLICY
    assets.URL_POLICY = policy_for(trusted)
    try:
        yield
    finally:
        assets.URL_POLICY = previous


def typed_urls(tool: str, params: dict, actor: str) -> frozenset[str]:
    """The links the user typed: a trusted actor's fetch whose query is a web link. Everything else (a
    model's query, og:image, search and API results, redirects, a link found on the clipboard) is
    checked. The session builds each ToolCall with `trusted_urls=typed_urls(step.tool, step.params,
    step.actor)`."""
    query = params.get("query")
    if tool == "fetch" and is_trusted(actor) and isinstance(query, str) and WEB_LINK.match(query):
        return frozenset({query})
    return frozenset()
