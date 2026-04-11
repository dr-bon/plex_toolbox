from __future__ import annotations  # Until Python 3.14

import re

REGEX_PATTERNS_TV = [
    re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<ep>\d{1,2})\b"),  # S01E02
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<ep>\d{2})\b"),  # 1x02
    re.compile(r"(?i)\bSeason[ ._-]?(?P<season>\d{1,2}).*?\bEp(?:isode)?[ ._-]?(?P<ep>\d{1,3})\b"),
]

REGEX_PATTERN_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
