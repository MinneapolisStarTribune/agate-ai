from celery import chain
from worker.tasks.locations.review.review import _validate_locations_task as _review_locations_task
from worker.tasks.locations.review.finalize import _finalize_locations_task

def _review_chain():
    """
    Creates a Celery chain for location review and finalization.

    The chain consists of:
    1. _finalize_locations_task: Cleans up the payload for final output

    Note: Validation is already performed in the geocoding chain,
    so we only need finalization here.

    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _finalize_locations_task.s()
    )
