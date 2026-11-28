import re


_HEADING = re.compile(
    r"^[ \t]*(Глава[ \t]+(?:\d+|[IVXLCDM]+|первая|вторая|третья|четв[её]ртая|"
    r"пятая|шестая|седьмая|восьмая|девятая|десятая)\b[^\n]*)$",
    re.MULTILINE | re.IGNORECASE,
)


def story_sections(text: str) -> list[tuple[str, list[str]]]:
    """Keep introductory text separate so it never consumes a chapter illustration."""
    pieces = _HEADING.split(text.replace("\r\n", "\n").replace("\r", "\n").strip())
    sections = []
    for title, body in zip(["", *pieces[1::2]], pieces[::2]):
        paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n", body) if part.strip()]
        if title or paragraphs:
            sections.append((title.strip(), paragraphs))
    return sections


def require_four_chapters(text: str) -> None:
    chapters = [(title, body) for title, body in story_sections(text) if title]
    expected = ("1|I|первая", "2|II|вторая", "3|III|третья", "4|IV|четв[её]ртая")
    if len(chapters) != len(expected) or any(
        not body or not re.match(rf"Глава[ \t]+(?:{number})\b", title, re.IGNORECASE)
        for (title, body), number in zip(chapters, expected)
    ):
        raise ValueError("Four nonempty chapters in reading order are required before illustration")
