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
    Core logic for adding region information to boundaries.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing boundaries and places
        
    Returns:
        dict: Updated payload with region information added to boundaries
    """
    boundaries = payload.get('boundaries', {})
    
    if not boundaries:
        logging.info("No boundaries provided, skipping localization")
        return payload
        
    # Initialize regions in boundaries if it doesn't exist
    if 'regions' not in boundaries:
        boundaries['regions'] = []
        
    # Track unique regions by ID to avoid duplicates
    seen_region_ids = set()
    
    # Process each county to get its region information
    counties = boundaries.get('counties', [])
    for county in counties:
        county_name = county.get('name')
        # Get state name from the state that contains this county
        state_id = None
        for state in boundaries.get('states', []):
            if any(place_id in state.get('places', []) for place_id in county.get('places', [])):
                state_name = state.get('name')
                if state_name:
                    state_abbrev = get_state_abbrev(state_name)
                    if state_abbrev:
                        region_info = get_region_info(county_name, state_abbrev)
                        
                        if region_info and region_info.get('regions'):
                            for region in region_info['regions']:
                                region_id = region.get('id')
                                if region_id and region_id not in seen_region_ids:
                                    seen_region_ids.add(region_id)
                                    
                                    # Add region to boundaries with the same structure as other boundary types
                                    boundaries['regions'].append({
                                        'id': region_id,
                                        'name': region.get('name'),
                                        'coordinates': {
                                            'lat': county.get('coordinates', {}).get('lat'),
                                            'lng': county.get('coordinates', {}).get('lng')
                                        },
                                        'places': county.get('places', [])  # Associate the same places as the county
                                    })
    
    # Update payload with modified boundaries
    payload['boundaries'] = boundaries
    
    logging.info("Localized locations payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="localize_locations", bind=True, max_retries=3)
def _localize_locations_task(self, payload):
    """
    Celery task wrapper for adding region information.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing boundaries and places
        
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
