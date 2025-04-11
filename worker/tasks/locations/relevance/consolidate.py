import logging, traceback, json
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _consolidate_locations(payload):
    """
    Core logic for filtering out non-relevant locations and cleaning up metadata.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with filtered locations and cleaned metadata
        
    Raises:
        Exception: If location consolidation fails
    """
    logging.info("Starting location consolidation")
    url = payload.get('url', '')
    locations = payload.get('locations', [])
    
    if not locations:
        logging.info("No locations to consolidate")
        return payload
        
    # Filter out non-relevant locations and remove metadata attributes
    filtered_locations = []
    for location in locations:
        if location.get('relevant', True):  # Keep locations if 'relevant' is True or not specified
            # Create a clean copy of the location without metadata
            clean_location = location.copy()
            clean_location.pop('relevant', None)
            clean_location.pop('notes', None)
            filtered_locations.append(clean_location)
    
    logging.info(f"Filtered {len(locations)} locations down to {len(filtered_locations)} relevant locations")
    logging.info("Consolidated location payload: %s" % json.dumps(filtered_locations, indent=2))
    
    # Update payload with filtered locations
    payload['locations'] = filtered_locations
    
    return payload

########## TASKS ##########

@celery.task(name="consolidate_locations", bind=True, max_retries=3)
def _consolidate_locations_task(self, payload):
    """
    Celery task wrapper for location consolidation.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with filtered locations and cleaned metadata
    """
    try:
        url = payload.get('url', '')
        
        try:
            return _consolidate_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location consolidation failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location consolidation: {str(e)}")
        post_slack_log_message('Error consolidating locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location consolidation: {err}")
        post_slack_log_message('Error consolidating locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
