import json
import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _process_boundaries(locations):
    """
    Process locations to extract distinct boundaries and restructure the output.
    Organizes boundaries by geographic level and associates places with each boundary.
    Also handles description_new attribute if present.
    
    Args:
        locations (list): List of location dictionaries with geocoding results
        
    Returns:
        dict: Restructured data with boundaries and places
    """
    # Initialize the result structure
    result = {
        "boundaries": {
            "states": [],
            "counties": [],
            "cities": [],
            "neighborhoods": [],
            "regions": []
        },
        "places": []
    }
    
    # Track unique boundaries by ID to avoid duplicates
    seen_boundaries = {
        "states": set(),
        "counties": set(),
        "cities": set(),
        "neighborhoods": set(),
        "regions": set()
    }
    
    # Process each location
    for location in locations:
        geocode = location.get('geocode', {})
        
        # Skip locations with empty geocode objects
        if not geocode or not geocode.get('results'):
            continue
            
        boundaries = geocode.get('results', {}).get('boundaries', {})
        geometry = geocode.get('results', {}).get('geometry', {})
        
        # Process state
        state = boundaries.get('state')
        if state and isinstance(state, dict):
            state_id = state.get('id')
            if state_id and state_id not in seen_boundaries["states"]:
                seen_boundaries["states"].add(state_id)
                result["boundaries"]["states"].append({
                    "id": state_id,
                    "name": state.get('name'),
                    "coordinates": {
                        "lat": geometry.get('coordinates', [])[1] if geometry.get('coordinates') else None,
                        "lng": geometry.get('coordinates', [])[0] if geometry.get('coordinates') else None
                    },
                    "places": []  # Will be populated later
                })
        
        # Process county
        county = boundaries.get('county')
        if county and isinstance(county, dict):
            county_id = county.get('id')
            if county_id and county_id not in seen_boundaries["counties"]:
                seen_boundaries["counties"].add(county_id)
                result["boundaries"]["counties"].append({
                    "id": county_id,
                    "name": county.get('name'),
                    "coordinates": {
                        "lat": geometry.get('coordinates', [])[1] if geometry.get('coordinates') else None,
                        "lng": geometry.get('coordinates', [])[0] if geometry.get('coordinates') else None
                    },
                    "places": []  # Will be populated later
                })
        
        # Process city
        city = boundaries.get('city')
        if city and isinstance(city, dict):
            city_id = city.get('id')
            if city_id and city_id not in seen_boundaries["cities"]:
                seen_boundaries["cities"].add(city_id)
                result["boundaries"]["cities"].append({
                    "id": city_id,
                    "name": city.get('name'),
                    "coordinates": {
                        "lat": geometry.get('coordinates', [])[1] if geometry.get('coordinates') else None,
                        "lng": geometry.get('coordinates', [])[0] if geometry.get('coordinates') else None
                    },
                    "places": []  # Will be populated later
                })
        
        # Process neighborhood
        neighborhood = boundaries.get('neighborhood')
        if neighborhood and isinstance(neighborhood, dict):
            neighborhood_id = neighborhood.get('id')
            if neighborhood_id and neighborhood_id not in seen_boundaries["neighborhoods"]:
                seen_boundaries["neighborhoods"].add(neighborhood_id)
                result["boundaries"]["neighborhoods"].append({
                    "id": neighborhood_id,
                    "name": neighborhood.get('name'),
                    "coordinates": {
                        "lat": geometry.get('coordinates', [])[1] if geometry.get('coordinates') else None,
                        "lng": geometry.get('coordinates', [])[0] if geometry.get('coordinates') else None
                    },
                    "places": []  # Will be populated later
                })
        
        # Process regions
        regions = boundaries.get('regions', [])
        for region in regions:
            if isinstance(region, dict):
                region_id = region.get('id')
                if region_id and region_id not in seen_boundaries["regions"]:
                    seen_boundaries["regions"].add(region_id)
                    result["boundaries"]["regions"].append({
                        "id": region_id,
                        "name": region.get('name'),
                        "coordinates": {
                            "lat": geometry.get('coordinates', [])[1] if geometry.get('coordinates') else None,
                            "lng": geometry.get('coordinates', [])[0] if geometry.get('coordinates') else None
                        },
                        "places": []  # Will be populated later
                    })
        
        # Clean up and add the location to places
        place = location.copy()
        place.pop('valid', None)  # Remove valid attribute
        place.pop('rationale', None)  # Remove rationale attribute
        
        # Handle description_new if present
        if 'description_new' in place:
            place['description'] = place.pop('description_new')
            
        result["places"].append(place)
    
    # Now associate places with their boundaries
    for place in result["places"]:
        geocode = place.get('geocode', {})
        boundaries = geocode.get('results', {}).get('boundaries', {})
        place_id = place.get('id', place.get('location'))  # Use location as fallback ID
        
        # Add place reference to each boundary it belongs to
        if boundaries.get('state', {}).get('id') in seen_boundaries["states"]:
            for state in result["boundaries"]["states"]:
                if state["id"] == boundaries["state"]["id"]:
                    state["places"].append(place_id)
                    
        if boundaries.get('county', {}).get('id') in seen_boundaries["counties"]:
            for county in result["boundaries"]["counties"]:
                if county["id"] == boundaries["county"]["id"]:
                    county["places"].append(place_id)
                    
        if boundaries.get('city', {}).get('id') in seen_boundaries["cities"]:
            for city in result["boundaries"]["cities"]:
                if city["id"] == boundaries["city"]["id"]:
                    city["places"].append(place_id)
                    
        if boundaries.get('neighborhood', {}).get('id') in seen_boundaries["neighborhoods"]:
            for neighborhood in result["boundaries"]["neighborhoods"]:
                if neighborhood["id"] == boundaries["neighborhood"]["id"]:
                    neighborhood["places"].append(place_id)
                    
        # Associate places with regions
        for region in boundaries.get('regions', []):
            if region.get('id') in seen_boundaries["regions"]:
                for boundary_region in result["boundaries"]["regions"]:
                    if boundary_region["id"] == region["id"]:
                        boundary_region["places"].append(place_id)
    
    return result

########## CORE FUNCTION ##########

def _finalize_locations(payload):
    """
    Core logic for finalizing locations by filtering invalid ones and organizing boundaries.
    This function:
    - Removes locations where valid=false
    - Restructures the output format
    - Removes text and story_type attributes
    - Handles description_new attribute if present
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with only valid locations and organized boundaries
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping finalization")
        return payload
        
    logging.info(f"Finalizing {len(locations)} locations for {url}")
    
    # Filter out locations where valid is false
    valid_locations = [
        location for location in locations
        if location.get('valid', False)
    ]
    
    # Log the results
    removed_count = len(locations) - len(valid_locations)
    if removed_count > 0:
        logging.info(f"Removed {removed_count} invalid locations")
        for location in locations:
            if not location.get('valid', False):
                logging.info(f"Invalid location: {location.get('location')} - Reason: {location.get('rationale', 'No rationale provided')}")
    
    # Process boundaries and restructure output
    result = _process_boundaries(valid_locations)
    
    # Update payload with new structure and remove text/story_type
    payload['boundaries'] = result['boundaries']
    payload['places'] = result['places']
    del payload['locations']  # Remove old locations key
    
    logging.info("Finalized locations payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="finalize_locations", bind=True, max_retries=3)
def _finalize_locations_task(self, payload):
    """
    Celery task wrapper for finalizing locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with only valid locations and organized boundaries
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
