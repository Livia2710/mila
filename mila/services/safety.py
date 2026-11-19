import re
import unicodedata


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", plain).strip()


CRISIS_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bsuicid\w*\b",
        r"\bme matar\b",
        r"\bquero morrer\b",
        r"\bvontade de morrer\b",
        r"\bnao quero (?:mais )?viver\b",
        r"\bacabar com (?:a )?minha vida\b",
        r"\btirar (?:a )?minha vida\b",
        r"\bme machucar\b",
        r"\bme ferir\b",
        r"\bme cortar\b",
        r"\bautolesao\b",
        r"\bautomutilacao\b",
        r"\bmelhor sem mim\b",
        r"\bnao quero (?:mais )?acordar\b",
        r"\bqueria (?:sumir|desaparecer)\b",
    )
)
GREETING_PATTERN = re.compile(
    r"^(?:oi+|ola+|bom dia|boa tarde|boa noite|e ai|tudo bem|obrigad[oa])(?: tudo bem)?$"
)
EMOJI_OR_SYMBOLS_PATTERN = re.compile(r"^[\W_]+$", re.UNICODE)


def is_crisis(text: str) -> bool:
    normalized = normalize(text)
    return any(pattern.search(normalized) for pattern in CRISIS_PATTERNS)


def is_simple_greeting(text: str) -> bool:
    normalized = normalize(text)
    normalized = "".join(
        char for char in normalized
        if unicodedata.category(char)[0] in {"L", "N"} or char.isspace()
    )
    return bool(GREETING_PATTERN.fullmatch(re.sub(r"\s+", " ", normalized).strip()))


def is_only_symbols(text: str) -> bool:
    return bool(text.strip()) and bool(EMOJI_OR_SYMBOLS_PATTERN.fullmatch(text.strip()))


def is_short_followup(text: str) -> bool:
    return len(normalize(text).split()) < 8

