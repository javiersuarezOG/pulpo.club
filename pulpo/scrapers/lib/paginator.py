"""URL pagination — handles ``?page=N`` and ``/page/N/`` shapes.

The two patterns across the 11 existing scrapers cover ~95% of real-world
pagination. WordPress (citymax, santizo) and most catalog plugins use
``/page/N/``; query-string portals (encuentra24, realtor) use
``?page=N``. The paginator yields response objects from a caller-provided
fetch function and stops on:

  - empty page (heuristic: response body lacks the expected anchor)
  - max_pages reached
  - fetch returns None / raises

It does NOT parse listings — callers extract their own cards from each
yielded response.

Stop-on-empty heuristic: the caller passes ``stop_signal`` — a substring
or compiled regex that must appear in a non-empty page's body. When the
substring goes missing, the page is treated as empty and pagination
stops. This avoids over-paging into 404-equivalent "no results" pages.
"""
from __future__ import annotations

import re
from typing import Callable, Iterator, Optional, Union


PageNumberPattern = Union[str, re.Pattern]


def _build_page_url(
    base_url: str,
    page: int,
    *,
    page_param: Optional[str] = None,
    url_pattern: Optional[str] = None,
) -> str:
    """Construct a per-page URL from the base + page number.

    - ``page_param``: query-string shape. ``page_param="page"`` produces
      ``{base_url}?page=2`` (or ``&page=2`` if ``?`` already present).
    - ``url_pattern``: format string with ``{page}`` placeholder, e.g.
      ``"https://example.test/listings/page/{page}/"``.

    Exactly one of ``page_param`` or ``url_pattern`` must be supplied.
    """
    if (page_param is None) == (url_pattern is None):
        raise ValueError("paginate(): supply exactly one of page_param or url_pattern")
    if url_pattern is not None:
        return url_pattern.format(page=page)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{page_param}={page}"


def paginate(
    fetch: Callable[[str], Optional[object]],
    base_url: str,
    *,
    page_param: Optional[str] = None,
    url_pattern: Optional[str] = None,
    start: int = 1,
    max_pages: int = 50,
    stop_signal: Optional[PageNumberPattern] = None,
) -> Iterator[tuple[int, object]]:
    """Yield ``(page_number, response)`` tuples until empty or max reached.

    Args:
        fetch: callable taking the per-page URL and returning a response
            object whose ``.text`` is the HTML body. Returns None on
            non-fatal HTTP errors so pagination stops cleanly.
        base_url: the page-1 / no-page-suffix URL.
        page_param: query-string parameter name (e.g. ``"page"``).
            Mutually exclusive with ``url_pattern``.
        url_pattern: ``{page}``-formatted URL template (e.g.
            ``"https://example.test/listings/page/{page}/"``).
            Mutually exclusive with ``page_param``.
        start: first page number (default 1).
        max_pages: hard ceiling on pages walked. Defends against infinite
            loops when stop_signal isn't supplied or the site is broken.
            Caller is expected to set this based on the source's expected
            inventory (a 942-listing source with 24 listings per page
            needs max_pages>=40).
        stop_signal: optional substring or compiled regex. When the
            response body LACKS this signal, the page is treated as
            empty and pagination stops. When None, the only stop
            conditions are ``fetch`` returning None and ``max_pages``.

    Yields ``(page_number, response)`` for each non-empty page. Caller
    extracts records from each response.
    """
    for page in range(start, start + max_pages):
        url = _build_page_url(
            base_url, page,
            page_param=page_param,
            url_pattern=url_pattern,
        )
        resp = fetch(url)
        if resp is None:
            return
        body = getattr(resp, "text", None) or ""
        if stop_signal is not None and not _has_signal(body, stop_signal):
            return
        yield page, resp


def _has_signal(body: str, signal: PageNumberPattern) -> bool:
    if isinstance(signal, re.Pattern):
        return signal.search(body) is not None
    return signal in body
