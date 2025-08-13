from celery import chain
from worker.tasks.people.extract.extract import _extract_people_task
from worker.tasks.people.extract.review import review_people_task

def _people_extraction_chain():
    """
    Creates a Celery chain for people extraction and optional review.
    """
    return chain(
        _extract_people_task.s(),
        review_people_task.s()
    )