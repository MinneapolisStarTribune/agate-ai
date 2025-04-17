from celery import chain
from worker.tasks.base.scrape import _scrape_article_task
from worker.tasks.base.classify import _classify_article_task

def _base_chain():
    """
    Creates a Celery chain for base article processing.
    
    The chain consists of:
    1. _scrape_article_task: Scrapes the article content from the URL
    2. _classify_article_task: Classifies the article type for location extraction
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _scrape_article_task.s(),
        _classify_article_task.s()
    )
