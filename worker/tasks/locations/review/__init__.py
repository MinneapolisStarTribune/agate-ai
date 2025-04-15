from celery import chain
from worker.tasks.locations.review.review import _review_locations_task
from worker.tasks.locations.review.finalize import _finalize_locations_task

def _review_chain():
    """
    Creates a Celery chain for location review and finalization.
    
    The chain consists of:
    1. _review_locations_task: Reviews the locations
    2. _finalize_locations_task: Cleans up the payload for final output
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _review_locations_task.s(),
        _finalize_locations_task.s()
    )
