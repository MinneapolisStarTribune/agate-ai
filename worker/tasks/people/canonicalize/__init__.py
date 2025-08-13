from celery import chain
from worker.tasks.people.canonicalize.canonicalize import _canonicalize_people_task

def _people_canonicalize_chain():
    """
    Creates a Celery chain for people canonicalization via WikiData.
    """
    return chain(
        _canonicalize_people_task.s()
    )