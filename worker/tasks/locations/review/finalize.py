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

def _finalize_locations(payload):
    """
    Core logic for finalizing locations by cleaning up the payload.
    This function removes unnecessary attributes and prepares the final output.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Cleaned payload with unnecessary attributes removed
    """
    url = payload.get('url')
    logging.info(f"Finalizing payload for {url}")
    
    # Create a copy of the payload to modify
    cleaned_payload = payload.copy()
    
    # Remove unnecessary attributes
    cleaned_payload.pop('text', None)
    cleaned_payload.pop('story_type', None)
    
    logging.info("Finalized payload: %s" % json.dumps(cleaned_payload, indent=2))    
    return cleaned_payload

########## TASKS ##########

@celery.task(name="finalize_locations", bind=True, max_retries=3)
def _finalize_locations_task(self, payload):
    """
    Celery task wrapper for finalizing locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Cleaned payload with unnecessary attributes removed
    """
    try:
        url = payload.get('url')
        
        try:
            return _finalize_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location finalization failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for finalization: {str(e)}")
        post_slack_log_message('Error finalizing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in finalization: {err}")
        post_slack_log_message('Error finalizing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
