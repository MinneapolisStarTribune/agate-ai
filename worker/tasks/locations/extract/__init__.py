from celery import chain
from worker.tasks.locations.extract.extract import _extract_locations_task
from worker.tasks.locations.extract.review import extract_locations_review_task

def _location_extraction_chain():
    """
    Creates a Celery chain for location extraction, review, and consolidation.
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _extract_locations_task.s(),
        extract_locations_review_task.s()
    )
