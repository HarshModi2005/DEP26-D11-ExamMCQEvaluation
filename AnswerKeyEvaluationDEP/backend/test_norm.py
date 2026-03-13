import re

ENTRY_NUMBER_PATTERN = re.compile(r'(\d{4})\s*([A-Za-z]{2,4})\s*(\d{2,5})')

def _normalize_entry_number(raw: str):
    if not raw or raw.lower() in ('unknown', 'none', 'n/a', ''):
        return None

    clean = raw.strip()
    m = ENTRY_NUMBER_PATTERN.search(clean)
    if m:
        year = m.group(1)
        branch = m.group(2).upper()
        number = m.group(3)
        return f"{year}{branch}{number}"

    fallback = re.sub(r'[\s\-_./]', '', clean).upper()
    if len(fallback) >= 6:
        return fallback
    return None

print("2011 AJBL1111 ->", _normalize_entry_number("2011 AJBL1111"))
print("2011ABJL1111 ->", _normalize_entry_number("2011ABJL1111"))
