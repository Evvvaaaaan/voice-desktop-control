import re
from urllib.parse import quote_plus


FastPathAction = tuple[str, dict, str]

_OPEN_RE = re.compile(
    r"^(?P<target>.+?)\s*(?:앱\s*)?"
    r"(?:열어\s*줘|열어주세요|열어|켜\s*줘|켜|실행해\s*줘|실행)$",
    re.IGNORECASE,
)
_EN_OPEN_RE = re.compile(r"^(?:open|launch|start)\s+(?P<target>.+)$", re.IGNORECASE)
_SEARCH_RE = re.compile(
    r"^(?:(?:구글|google)(?:에서)?\s*)?"
    r"(?P<query>.+?)\s*검색(?:해\s*줘|해줘|해|)$",
    re.IGNORECASE,
)

_COMPOSITE_MARKERS = (" 열고 ", " 하고 ", " 그리고 ", " 다음 ", " 후 ")

_APP_ALIASES = (
    (("크롬", "구글 크롬", "chrome", "google chrome", "그롬", "크름"), "Google Chrome", "크롬"),
    (("사파리", "safari", "사파레"), "Safari", "사파리"),
    (("파인더", "finder"), "Finder", "파인더"),
    (("터미널", "terminal"), "Terminal", "터미널"),
    (("메모", "노트", "notes"), "Notes", "메모"),
    (("캘린더", "calendar"), "Calendar", "캘린더"),
    (("메일", "mail"), "Mail", "메일"),
    (("설정", "시스템 설정", "system settings"), "System Settings", "설정"),
)

_SITE_ALIASES = (
    (("지메일", "쥐메일", "gmail", "g메일"), "https://mail.google.com", "지메일"),
    (("유튜브", "youtube"), "https://www.youtube.com", "유튜브"),
    (("네이버", "naver"), "https://www.naver.com", "네이버"),
    (("구글", "google"), "https://www.google.com", "구글"),
)


def parse_fast_path(command: str) -> FastPathAction | None:
    text = _normalize(command)
    if not text:
        return None

    target = _open_target(text)
    if target and not _looks_composite(text):
        if target.startswith(("http://", "https://")):
            return "open_url", {"url": target}, "페이지를 열었어요."

        site = _lookup(_SITE_ALIASES, target)
        if site:
            url, label = site
            return "open_url", {"url": url}, f"{label}을 열었어요."

        app = _lookup(_APP_ALIASES, target)
        if app:
            app_name, label = app
            return "launch_app", {"app": app_name}, f"{label}을 열었어요."

    query = _search_query(text)
    if query and not _looks_composite(query):
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        return "open_url", {"url": url}, f"{query} 검색을 열었어요."

    return None


def _normalize(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().strip(".,!?。！？")).lower()


def _open_target(text: str) -> str | None:
    match = _OPEN_RE.match(text) or _EN_OPEN_RE.match(text)
    if not match:
        return None
    return match.group("target").strip()


def _search_query(text: str) -> str | None:
    match = _SEARCH_RE.match(text)
    if not match:
        return None
    return match.group("query").strip()


def _lookup(aliases, target: str):
    squashed = target.replace(" ", "")
    for names, *value in aliases:
        for name in names:
            if target == name or squashed == name.replace(" ", ""):
                return tuple(value)
    return None


def _looks_composite(text: str) -> bool:
    padded = f" {text} "
    return any(marker in padded for marker in _COMPOSITE_MARKERS)
