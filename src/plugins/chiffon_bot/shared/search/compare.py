from rapidfuzz import fuzz, process


def fuzzy_matching_by_song_name(choice: list[str], string: str) -> list:
    return process.extract(string, choice, scorer=fuzz.ratio, limit=5)
