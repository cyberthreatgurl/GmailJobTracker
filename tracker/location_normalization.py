"""Utilities for canonical city/state normalization used in company location features."""

import re

_STATE_ABBR_TO_NAME = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "dc": "district of columbia",
}

_STATE_NAME_TO_ABBR = {name: abbr for abbr, name in _STATE_ABBR_TO_NAME.items()}

_CITY_TOKEN_ALIASES = {
    "dalgren": "dahlgren",
}


def _collapse_spaces(value):
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value):
    text = (value or "").lower().replace(".", " ")
    text = re.sub(r"[^a-z0-9,\s-]", " ", text)
    text = text.replace("-", " ")
    text = _collapse_spaces(text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


def _normalize_city_tokens(city_text):
    city_clean = _collapse_spaces(re.sub(r"[^a-z0-9\s]", " ", city_text or ""))
    tokens = []
    for token in city_clean.split(" "):
        tokens.append(_CITY_TOKEN_ALIASES.get(token, token))
    return _collapse_spaces(" ".join(tokens))


def _extract_state_abbr(fragment):
    cleaned = _collapse_spaces(re.sub(r"[^a-z\s]", " ", (fragment or "").lower()))
    if not cleaned:
        return ""

    parts = cleaned.split(" ")
    if len(parts) >= 2:
        candidate = f"{parts[0]} {parts[1]}"
        if candidate in _STATE_NAME_TO_ABBR:
            return _STATE_NAME_TO_ABBR[candidate]

    first = parts[0]
    if first in _STATE_NAME_TO_ABBR:
        return _STATE_NAME_TO_ABBR[first]
    if first in _STATE_ABBR_TO_NAME:
        return first
    return ""


def canonicalize_city_key(value):
    """Return canonical city key for dedupe/search.

    Examples:
    - 'Dahlgren, VA' -> 'dahlgren, va'
    - 'Dahlgren, Virginia' -> 'dahlgren, va'
    - 'Dalgren, Virginia' -> 'dahlgren, va'
    """
    normalized = _normalize_text(value)
    if not normalized:
        return ""

    city_part = normalized
    state_abbr = ""

    if "," in normalized:
        city_part, tail = normalized.split(",", 1)
        state_abbr = _extract_state_abbr(tail)
    else:
        words = normalized.split(" ")
        if len(words) >= 3:
            tail_two = " ".join(words[-2:])
            two_word_state = _extract_state_abbr(tail_two)
            if two_word_state:
                city_part = " ".join(words[:-2])
                state_abbr = two_word_state
            else:
                one_word_state = _extract_state_abbr(words[-1])
                if one_word_state:
                    city_part = " ".join(words[:-1])
                    state_abbr = one_word_state
        elif len(words) == 2:
            one_word_state = _extract_state_abbr(words[-1])
            if one_word_state:
                city_part = words[0]
                state_abbr = one_word_state

    city_norm = _normalize_city_tokens(city_part)
    if not city_norm:
        return state_abbr
    if state_abbr:
        return f"{city_norm}, {state_abbr}"
    return city_norm
