from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ParsedWebRequest:
    action: str
    query: str
    youtube_filter: str = ""


_FILLER_WORDS = {
    "find",
    "show",
    "open",
    "search",
    "look",
    "play",
    "watch",
    "latest",
    "newest",
    "the",
    "a",
    "an",
    "for",
    "please",
    "video",
    "videos",
    "it",
    "on",
    "to",
    "and",
    "me",
    "this",
    "that",
    "do",
    "up",
    "youtube",
    "youtu",
    "yt",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _remove_filler_words(text: str) -> str:
    words = [word for word in re.split(r"\s+", _normalize(text)) if word and word not in _FILLER_WORDS]
    return " ".join(words).strip()


def parse_web_request(request_text: str) -> ParsedWebRequest:
    normalized = _normalize(request_text)

    if not normalized:
        return ParsedWebRequest(action="unknown", query="")

    explicit_youtube = any(keyword in normalized for keyword in ("youtube", "youtu.be", "yt"))
    video_intent = any(keyword in normalized for keyword in ("play", "watch", "video", "videos", "song", "music"))
    platform_research_hint = any(
        keyword in normalized for keyword in ("instagram", "insta", "tiktok", "twitter", "x", "reddit", "facebook", "threads")
    )

    if explicit_youtube or (video_intent and not platform_research_hint):
        action = "play_youtube_video" if any(keyword in normalized for keyword in ("play", "watch")) or explicit_youtube else "open_youtube_search"
        cleaned = _remove_filler_words(request_text)
        youtube_filter = "upload_date" if action == "play_youtube_video" and any(keyword in normalized for keyword in ("latest", "newest")) else ""
        return ParsedWebRequest(action=action, query=cleaned, youtube_filter=youtube_filter)

    if any(phrase in normalized for phrase in ("open google", "launch google", "open browser", "open the browser")):
        cleaned = _remove_filler_words(request_text)
        return ParsedWebRequest(action="open_google_search", query=cleaned)

    cleaned = _remove_filler_words(request_text)
    return ParsedWebRequest(action="research_web", query=cleaned)