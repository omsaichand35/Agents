from urllib.parse import quote_plus
from urllib.parse import parse_qs
from urllib.parse import urlparse
from urllib.parse import unquote
from urllib.parse import urljoin
import html
import importlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
import webbrowser

from langchain_core.tools import tool


def _open_url(url: str) -> str:
    webbrowser.open(url)
    return url


def _fetch_text(url: str, timeout: int = 12) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _clean_text(text: str) -> str:
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
    return text


def _normalize_result_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        redirect = query.get("uddg", [""])[0]
        if redirect:
            return unquote(redirect)
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _flatten_related_topics(payload: dict, limit: int = 4) -> list[dict]:
    topics: list[dict] = []

    def _walk(items: list[dict]) -> None:
        for item in items:
            if len(topics) >= limit:
                return
            if "FirstURL" in item and "Text" in item:
                topics.append({
                    "title": _clean_text(item.get("Text", "").split(" - ")[0]),
                    "snippet": _clean_text(item.get("Text", "")),
                    "url": _normalize_result_url(item.get("FirstURL", "")),
                })
            elif "Topics" in item:
                _walk(item.get("Topics", []))

    _walk(payload.get("RelatedTopics", []))
    return topics


def _duckduckgo_instant_answer(query: str) -> tuple[str, list[dict]]:
    url = (
        "https://api.duckduckgo.com/"
        f"?q={quote_plus(query.strip())}&format=json&no_html=1&skip_disambig=1&no_redirect=1"
    )
    try:
        raw = _fetch_text(url)
        payload = json.loads(raw)
    except Exception:
        return "", []

    summary = payload.get("AbstractText") or payload.get("Answer") or payload.get("Definition") or ""
    sources: list[dict] = []

    abstract_url = payload.get("AbstractURL") or payload.get("AbstractSource")
    if summary and abstract_url:
        sources.append({"title": payload.get("Heading") or "Primary source", "snippet": _clean_text(summary), "url": abstract_url})

    related = _flatten_related_topics(payload)
    sources.extend(related)
    return _clean_text(summary), sources


def _duckduckgo_html_search(query: str, limit: int = 5) -> list[dict]:
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query.strip())}"
    try:
        html_text = _fetch_text(search_url)
    except Exception:
        return []

    pattern = re.compile(
        r'(?s)<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'(?:<a[^>]+class="result__snippet"[^>]*>(?P<snippet_a>.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(?P<snippet_div>.*?)</div>)'
    )

    results: list[dict] = []
    for match in pattern.finditer(html_text):
        if len(results) >= limit:
            break
        snippet = match.group("snippet_a") or match.group("snippet_div") or ""
        results.append(
            {
                "title": _clean_text(match.group("title")),
                "snippet": _clean_text(snippet),
                "url": _normalize_result_url(match.group("href")),
            }
        )

    return results


def _format_research_output(query: str, summary: str, sources: list[dict]) -> str:
    lines = [f"Research summary for: {query}"]
    if summary:
        lines.append("")
        lines.append(f"Summary: {summary}")
    else:
        lines.append("")
        lines.append("Summary: I couldn't extract a direct answer, so here are the best sources I found.")

    if sources:
        lines.append("")
        lines.append("Sources:")
        for index, source in enumerate(sources[:5], 1):
            title = source.get("title") or source.get("url") or "Source"
            url = source.get("url") or ""
            snippet = source.get("snippet") or ""
            lines.append(f"{index}. {title} — {url}")
            if snippet:
                lines.append(f"   {snippet}")

    return "\n".join(lines)


def _resolve_youtube_url(query: str, youtube_filter: str = "") -> str | None:
    try:
        yt_dlp = importlib.import_module("yt_dlp")
    except Exception:
        return None

    try:
        if youtube_filter == "upload_date":
            extractor_options = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(extractor_options) as downloader:
                filtered_url = f"https://www.youtube.com/results?search_query={quote_plus(query.strip())}&sp=EgIQAQ%3D%3D"
                result = downloader.extract_info(filtered_url, download=False)
        else:
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as downloader:
                result = downloader.extract_info(f"ytsearch1:{query}", download=False)
    except Exception:
        return None

    entries = result.get("entries") if isinstance(result, dict) else None
    if not entries:
        return None

    first_entry = entries[0] or {}
    if youtube_filter == "upload_date" and first_entry.get("id"):
        return f"https://www.youtube.com/watch?v={first_entry.get('id')}"
    return first_entry.get("webpage_url") or first_entry.get("url") or (
        f"https://www.youtube.com/watch?v={first_entry.get('id')}" if first_entry.get("id") else None
    )


@tool
def open_google_search(query: str) -> str:
    """Opens a Google search for the provided query in the default browser."""
    search_url = f"https://www.google.com/search?q={quote_plus(query.strip())}"
    print(f"[WEB LINK]: Opening Google search for '{query}'.")
    _open_url(search_url)
    return f"SUCCESS: Google search opened: {search_url}"


@tool
def research_web_query(query: str) -> str:
    """Returns a terminal-only web research summary with source links."""
    cleaned_query = query.strip()
    print(f"[RESEARCH]: Searching the web for '{cleaned_query}'.")
    summary, sources = _duckduckgo_instant_answer(cleaned_query)
    if not sources:
        sources = _duckduckgo_html_search(cleaned_query)

    if not sources:
        fallback_url = f"https://duckduckgo.com/?q={quote_plus(cleaned_query)}"
        return _format_research_output(cleaned_query, summary, [{"title": "Search results", "url": fallback_url, "snippet": "Open this if you want more results."}])

    if not summary:
        fallback_snippets = [source.get("snippet", "") for source in sources if source.get("snippet")]
        summary = fallback_snippets[0] if fallback_snippets else ""

    return _format_research_output(cleaned_query, summary, sources)


@tool
def open_youtube_search(query: str) -> str:
    """Opens YouTube search results for the provided query in the default browser."""
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query.strip())}"
    print(f"[WEB LINK]: Opening YouTube search for '{query}'.")
    _open_url(search_url)
    return f"SUCCESS: YouTube search opened: {search_url}"


def open_youtube_filtered_search(query: str, youtube_filter: str) -> str:
    """Opens a filtered YouTube search results page for the provided query."""
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query.strip())}"
    filter_url = f"{search_url}&sp=EgIQAQ%3D%3D" if youtube_filter == "upload_date" else search_url

    print(f"[WEB LINK]: Opening YouTube search for '{query}'.")
    _open_url(search_url)

    if youtube_filter == "upload_date":
        print("[WEB LINK]: Applying YouTube filter for upload date (latest first)...")
        _open_url(filter_url)
        return f"SUCCESS: YouTube search opened and filtered by upload date: {filter_url}"

    return f"SUCCESS: YouTube search opened: {search_url}"


@tool
def play_youtube_video(query: str, youtube_filter: str = "") -> str:
    """Opens the first available YouTube video result for the query when possible."""
    print(f"[WEB LINK]: Attempting to resolve a YouTube video for '{query}'.")
    cleaned_query = query.strip()

    if youtube_filter == "upload_date":
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(cleaned_query)}"
        filter_url = f"{search_url}&sp=EgIQAQ%3D%3D"
        print(f"[WEB LINK]: Opening YouTube search for '{query}'.")
        _open_url(search_url)
        print("[WEB LINK]: Applying YouTube filter for upload date (latest first)...")
        _open_url(filter_url)

    resolved_url = _resolve_youtube_url(cleaned_query, youtube_filter)

    if resolved_url:
        _open_url(resolved_url)
        if youtube_filter == "upload_date":
            return f"SUCCESS: YouTube latest video opened after filtered search: {resolved_url}"
        return f"SUCCESS: YouTube video opened: {resolved_url}"

    fallback_url = f"https://www.youtube.com/results?search_query={quote_plus(cleaned_query)}"
    if youtube_filter == "upload_date":
        fallback_url = f"{fallback_url}&sp=EgIQAQ%3D%3D"
    _open_url(fallback_url)
    if youtube_filter == "upload_date":
        return f"FALLBACK: Could not resolve a direct latest video URL. YouTube filtered search opened: {fallback_url}"
    return f"FALLBACK: Could not resolve a direct video URL. YouTube search opened: {fallback_url}"