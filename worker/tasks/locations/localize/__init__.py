from celery import chain
from worker.tasks.locations.localize.localize import _localize_locations_task

def _localization_chain():
    """
    Creates a Celery chain for location localization.
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _localize_locations_task.s()
    )
