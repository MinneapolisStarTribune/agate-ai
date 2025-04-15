import json
import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## CORE FUNCTION ##########

def _review_locations(payload):
    """
    Core logic for reviewing locations.
    This function can be called independently for testing or used by the Celery task.
    Currently just passes through the payload without modification.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Unmodified payload
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping review")
        return payload
        
    logging.info(f"Reviewing {len(locations)} locations for {url}")
    
    # For now, just pass through the payload
    logging.info("Review payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="review_locations", bind=True, max_retries=3)
def _review_locations_task(self, payload):
    """
    Celery task wrapper for reviewing locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Payload with review results
    """
    try:
        url = payload.get('url')
        
        try:
            return _review_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location review failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for review: {str(e)}")
        post_slack_log_message('Error reviewing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in review: {err}")
        post_slack_log_message('Error reviewing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
