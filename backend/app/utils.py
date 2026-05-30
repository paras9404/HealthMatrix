import re


def slugify(text: str, max_len: int = 240) -> str:
    """Lower-cased, hyphenated, ASCII-safe slug. Returns 'unknown' for empty input."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "unknown"


def unique_slug(model, base_slug: str, slug_field: str = "slug",
                exclude_id: int = None, max_len: int = 240) -> str:
    """Return a slug not currently in use on `model`. Appends -2, -3, ... if needed.
    `exclude_id` lets the row currently being updated keep its existing slug."""
    base = (base_slug or "")[:max_len] or "unknown"
    candidate = base
    n = 2
    while True:
        q = model.query.filter(getattr(model, slug_field) == candidate)
        if exclude_id is not None:
            q = q.filter(model.id != exclude_id)
        if q.first() is None:
            return candidate
        suffix = f"-{n}"
        candidate = base[: max_len - len(suffix)] + suffix
        n += 1
