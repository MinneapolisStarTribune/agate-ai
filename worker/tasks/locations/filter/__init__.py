from celery import chain
from worker.tasks.locations.filter.classify import _classify_locations_task
from worker.tasks.locations.filter.consolidate import _consolidate_locations_task

def _filter_chain():
    """
    Creates a Celery chain for location classification and consolidation.
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _classify_locations_task.s(),
        _consolidate_locations_task.s()
    )
