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

def _consolidate_geocoded_locations(payload):
    """
    Core logic for consolidating geocoded locations by removing invalid ones.
    This function filters out locations where validated=false and removes validation metadata.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with only validated locations, validation metadata removed
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping consolidation")
        return payload
        
    logging.info(f"Consolidating {len(locations)} locations for {url}")
    
    # Filter out locations where validated is false
    validated_locations = [
        location for location in locations
        if location.get('geocode', {}).get('validated', False)
    ]
    
    # Log the results
    removed_count = len(locations) - len(validated_locations)
    if removed_count > 0:
        logging.info(f"Removed {removed_count} invalid locations")
        for location in locations:
            if not location.get('geocode', {}).get('validated', False):
                logging.info(f"Invalid location: {location.get('location')} - Reason: {location.get('geocode', {}).get('rationale', 'No rationale provided')}")
    
    # Clean up validation metadata from remaining locations
    for location in validated_locations:
        if 'geocode' in location:
            geocode = location['geocode']
            # Create a clean copy without validation metadata
            geocode_clean = geocode.copy()
            geocode_clean.pop('validated', None)
            geocode_clean.pop('rationale', None)
            location['geocode'] = geocode_clean
    
    # Update the payload with filtered and cleaned locations
    payload['locations'] = validated_locations
    
    logging.info("Consolidated locations payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="consolidate_geocoded_locations", bind=True, max_retries=3)
def _consolidate_geocoded_locations_task(self, payload):
    """
    Celery task wrapper for consolidating geocoded locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with only validated locations
    """
    try:
        url = payload.get('url')
        
        try:
            return _consolidate_geocoded_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location consolidation failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for consolidation: {str(e)}")
        post_slack_log_message('Error consolidating locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in consolidation: {err}")
        post_slack_log_message('Error consolidating locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
