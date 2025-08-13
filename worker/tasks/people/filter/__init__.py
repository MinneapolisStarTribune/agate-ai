from celery import chain
from worker.tasks.people.filter.classify import _classify_people_task
from worker.tasks.people.filter.consolidate import _consolidate_people_task

def _people_filter_chain():
    """
    Creates a Celery chain for people relevance classification and consolidation.
    """
    return chain(
        _classify_people_task.s(),
        _consolidate_people_task.s()
    )