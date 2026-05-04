import re

_WS_RE = re.compile(r"\s+")


def clean(raw_name: str) -> str:
    text = _WS_RE.sub(" ", raw_name).strip()
    if not text:
        return text
    if text.isupper() or text.islower():
        text = text.title()
    return text
