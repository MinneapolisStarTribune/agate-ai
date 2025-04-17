import json
import logging
import traceback
import requests
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from conf.settings import CONTEXT_API_URL
from utils.slack import post_slack_log_message
from utils.geocode import get_state_abbrev

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def get_region_info(county_name, state_abbrev):
    """
    Get region information from the external service for a given county and state.
    
    Args:
        county_name (str): Name of the county
        state_abbrev (str): Two-letter state abbreviation
        
    Returns:
        dict: Region information including match quality and region details
    """
    base_url = CONTEXT_API_URL + "/locations/county"
    query = f"{county_name},{state_abbrev}"
    
    try:
        response = requests.get(f"{base_url}?q={query}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching region info for {query}: {str(e)}")
        return None

########## CORE FUNCTION ##########

def _localize_locations(payload):
    """
    Core logic for adding region information to each place's boundaries.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations array
        
    Returns:
        dict: Updated payload with region information added to each place's boundaries
    """
    locations = payload.get('locations', [])
    
    if not locations:
        logging.info("No locations provided, skipping localization")
        return payload
        
    # Process each location
    for location in locations:
        geocode = location.get('geocode', {})
        results = geocode.get('results', {})
        boundaries = results.get('boundaries', {})
        
        # Initialize regions in boundaries if it doesn't exist
        if 'regions' not in boundaries:
            boundaries['regions'] = []
            
        # Get county and state information
        county = boundaries.get('county', {})
        state = boundaries.get('state', {})
        
        if county.get('name') and state.get('name'):
            state_abbrev = get_state_abbrev(state['name'])
            if state_abbrev:
                region_info = get_region_info(county['name'], state_abbrev)
                
                if region_info and region_info.get('regions'):
                    # Add all regions found
                    boundaries['regions'] = [
                        {
                            'id': region.get('id'),
                            'name': region.get('name')
                        }
                        for region in region_info['regions']
                    ]
                    
        # Update the location with modified boundaries
        results['boundaries'] = boundaries
        geocode['results'] = results
        location['geocode'] = geocode
    
    # Update payload with modified locations
    payload['locations'] = locations
    
    logging.info("Localized locations payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="localize_locations", bind=True, max_retries=3)
def _localize_locations_task(self, payload):
    """
    Celery task wrapper for adding region information.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations array
        
    Returns:
        dict: Updated payload with region information
    """
    try:
        url = payload.get('url')
        
        try:
            return _localize_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location localization failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for localization: {str(e)}")
        post_slack_log_message('Error localizing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in localization: {err}")
        post_slack_log_message('Error localizing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
