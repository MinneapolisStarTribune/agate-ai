import logging
from celery import Celery

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

@celery.task(name="consolidate_people")
def _consolidate_people_task(payload):
    """
    Consolidate duplicate person names by exact match (case-insensitive).
    """
    people = payload.get('people', [])
    seen = set()
    unique = []
    for name in people:
        key = name.strip().lower() if isinstance(name, str) else None
        if key and key not in seen:
            seen.add(key)
            unique.append(name)
    payload['people'] = unique
    logging.info(f"Consolidated people list: {unique}")
    return payload