"""Fetch the raw text behind a `delegate` reference ourselves.

A reference is a public URL, a file under the configured public root, or a search query. The
caller never supplies the text the model sees, so content that reaches Contributor came from
the public internet or a public folder, not from a Claude or GPT turn.

Public means reachable without credentials: URLs must be http(s), carry no userinfo, and
resolve only to public addresses (checked again on every redirect hop); files must sit
under the public root, outside dot-directories, after symlinks are resolved.
"""
import ipaddress
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_000_000          # what we download per URL
MAX_FILE_BYTES = 500_000
MAX_CHARS = 60_000             # what one source contributes to a prompt
MAX_REDIRECTS = 3
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml")


class SourceError(Exception):
    """A reference could not be turned into public text."""


class Fetcher(Protocol):
    async def url(self, url: str) -> str: ...
    def file(self, path: str) -> str: ...
    async def search(self, query: str) -> str: ...


def is_url(ref: str) -> bool:
    return ref.lower().startswith(("http://", "https://"))


def _public_address(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_global and not a.is_multicast


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def check_public_url(url: str, resolver: Callable[[str], list[str]] = _resolve) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SourceError("only http(s) URLs are accepted")
    if parts.username or parts.password:
        raise SourceError("URLs with credentials are not public")
    host = parts.hostname
    if host.lower() == "localhost" or host.lower().endswith((".local", ".internal", ".localhost")):
        raise SourceError("URL does not point at a public host")
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addrs = resolver(host)
        except OSError as e:
            raise SourceError(f"cannot resolve {host}") from e
    if not addrs or not all(_public_address(a) for a in addrs):
        raise SourceError("URL does not point at a public host")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line)


class PublicFetcher:
    def __init__(self, public_root: str | Path | None = None,
                 search_fn: Callable[[str], Awaitable[str]] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 resolver: Callable[[str], list[str]] = _resolve) -> None:
        self.root = Path(public_root).resolve() if public_root else None
        self.search_fn = search_fn
        self.transport = transport
        self.resolver = resolver

    async def url(self, url: str) -> str:
        async with httpx.AsyncClient(transport=self.transport, timeout=20, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                check_public_url(url, self.resolver)
                async with client.stream("GET", url, headers={"accept": "text/html,text/plain,*/*;q=0.5"}) as r:
                    if r.is_redirect and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        raise SourceError(f"fetch failed with status {r.status_code}")
                    ctype = r.headers.get("content-type", "text/plain").split(";")[0].strip().lower()
                    if not ctype.startswith(TEXT_TYPES):
                        raise SourceError(f"unsupported content type {ctype}")
                    body = b""
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) >= MAX_BYTES:
                            break
                text = body[:MAX_BYTES].decode("utf-8", errors="replace")
                if "html" in ctype:
                    text = html_to_text(text)
                return text[:MAX_CHARS]
        raise SourceError("too many redirects")

    def file(self, path: str) -> str:
        if self.root is None:
            raise SourceError("no public root configured (set CM_PUBLIC_ROOT)")
        try:
            target = (self.root / path).resolve(strict=True)
            rel = target.relative_to(self.root)
        except (OSError, ValueError):
            raise SourceError("file is not under the public root") from None
        if any(part.startswith(".") for part in rel.parts):
            raise SourceError("hidden files are not public")
        if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
            raise SourceError("not a regular file within the size limit")
        try:
            return target.read_text(encoding="utf-8")[:MAX_CHARS]
        except UnicodeDecodeError:
            raise SourceError("file is not UTF-8 text") from None

    async def search(self, query: str) -> str:
        if self.search_fn is None:
            raise SourceError("no search backend configured")
        return (await self.search_fn(query))[:MAX_CHARS]
