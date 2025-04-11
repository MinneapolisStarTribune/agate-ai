from celery import chain
from worker.tasks.locations.geocode.prep import _prep_locations_task
from worker.tasks.locations.geocode.geocode import _geocode_locations_task
from worker.tasks.locations.geocode.review import validate_locations_task

def _geocoding_chain():
    """
    Creates a Celery chain for location geocoding and consolidation.
    
    The chain consists of:
    1. _prep_locations: Prepares locations for geocoding by structuring addresses
    2. _geocode_locations: Geocodes the prepared locations using Pelias API
    3. validate_locations_task: Validates geocoded locations using LLM
    
    Returns:
        Celery chain object that can be connected to other tasks
    """
    return chain(
        _prep_locations_task.s(),
        _geocode_locations_task.s(),
        validate_locations_task.s()
    )
