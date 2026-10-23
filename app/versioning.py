from difflib import SequenceMatcher
from .parser import ParsedNode

def match_nodes(previous, current):
    """Match nodes by normalized ancestry/title key, with conservative title fallback.

    Exact logical-key matching handles most stable section paths. The fallback is only
    used when a title is unique in both versions; ambiguous duplicates remain unmatched.
    """
    old_by_key = {n.logical_key: n for n in previous}
    new_by_key = {n.logical_key: n for n in current}
    matches = {key: key for key in old_by_key.keys() & new_by_key.keys()}
    old_titles, new_titles = {}, {}
    for n in previous: old_titles.setdefault(n.heading.casefold().strip(), []).append(n)
    for n in current: new_titles.setdefault(n.heading.casefold().strip(), []).append(n)
    for title in old_titles.keys() & new_titles.keys():
        if len(old_titles[title]) == len(new_titles[title]) == 1:
            old, new = old_titles[title][0], new_titles[title][0]
            matches.setdefault(old.logical_key, new.logical_key)
    return matches

def compare_text(old_text: str, new_text: str) -> dict:
    old = old_text or ""
    new = new_text or ""
    ratio = SequenceMatcher(a=old, b=new).ratio()
    old_words, new_words = old.split(), new.split()
    return {
        "changed": old != new,
        "similarity": round(ratio, 3),
        "old_length": len(old),
        "new_length": len(new),
        "summary": "Text changed; review the requirement and its generated tests." if old != new else "No text change detected.",
        "removed_excerpt": old[:180] if old != new else "",
        "added_excerpt": new[:180] if old != new else "",
        "word_count_delta": len(new_words) - len(old_words),
    }
