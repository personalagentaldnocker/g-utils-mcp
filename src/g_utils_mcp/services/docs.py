def text_insert(text: str, index: int = 1, tab_id: str | None = None) -> dict:
    """Build a typed Docs edit; indexes use Google's UTF-16 code-unit convention."""
    location: dict = {"index": index}
    if tab_id:
        location["tabId"] = tab_id
    return {"insertText": {"location": location, "text": text}}
