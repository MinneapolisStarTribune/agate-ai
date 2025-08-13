from celery import chain
from worker.tasks.people.review.review import _review_people_task
from worker.tasks.people.review.finalize import _finalize_people_task

def _people_review_chain():
    """
    Creates a Celery chain for people review and finalization.
    """
    return chain(
        _review_people_task.s(),
        _finalize_people_task.s()
    )