import requests
import logging

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

def lookup_entity(name):
    """
    Lookup a person entity in WikiData by name.
    Returns a dict with id, label, description, and match info, or None if not found.
    """
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "format": "json",
        "limit": 1
    }
    try:
        response = requests.get(WIKIDATA_API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        results = data.get("search", [])
        if not results:
            return None
        entry = results[0]
        return {
            "id": entry.get("id"),
            "label": entry.get("label"),
            "description": entry.get("description"),
            "match": entry.get("match")
        }
    except Exception as e:
        logging.error(f"Error querying WikiData for '{name}': {e}")
        return None