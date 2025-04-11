from celery import chain
from worker.tasks.locations.relevance.classify import _classify_locations_task
from worker.tasks.locations.relevance.consolidate import _consolidate_locations_task

def _relevance_classification_chain():
    """
    Creates a Celery chain for location relevance classification and consolidation.
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _classify_locations_task.s(),
        _consolidate_locations_task.s()
    )
