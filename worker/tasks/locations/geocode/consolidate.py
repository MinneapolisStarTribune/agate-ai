import json
import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
from utils.geocode import pelias_geocode_search, get_city_state

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _process_boundaries(locations):
    """
    Process locations to extract distinct boundaries and restructure the output.
    Removes validation metadata from places, filters out places with empty geocoding,
    and organizes them by boundary. Each boundary includes coordinates.
    
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
            "neighborhoods": []
        },
        "places": []
    }
    
    # Track unique boundaries by ID to avoid duplicates
    seen_boundaries = {
        "states": set(),
        "counties": set(),
        "cities": set(),
        "neighborhoods": set()
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
        
        # Clean up and add the location to places
        place = location.copy()
        if 'geocode' in place:
            # Remove validation metadata
            geocode_copy = place['geocode'].copy()
            geocode_copy.pop('validated', None)
            geocode_copy.pop('rationale', None)
            place['geocode'] = geocode_copy
            
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
    
    return result

########## CORE FUNCTION ##########

def _consolidate_geocoded_locations(payload):
    """
    Core logic for consolidating geocoded locations.
    Processes validation results and restructures the output format.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with consolidated locations and boundaries
    """
    locations = payload.get('locations', [])
    url = payload.get('url')

    logging.info(f"Consolidating locations for {url}")
    
    if not locations:
        logging.info("No locations provided, skipping consolidation")
        return payload
    
    # Find invalid locations and attempt to get best geography
    logging.info("Calculating fallback locations for items with failed validation ...")
    valid_locations = []
    for item in locations:
        geocode = item.get('geocode', {})
        if geocode.get('validated') == True:
            valid_locations.append(item)
        else:
            location = item.get('location')
            city_state = get_city_state(location)
            
            city = city_state.get('city')
            state = city_state.get('state')

            if city and state:
                results = pelias_geocode_search(f"{city}, {state}")
                if results and len(results) > 0:
                    top_result = results[0]
                    if top_result.get('confidence', {}).get('score', 0) >= 0.9:
                        item['geocode']['results'] = top_result
                        item['geocode']['validated'] = True
                        item['geocode']['rationale'] = "Fallback to city-state geocoding"
                valid_locations.append(item)
    
    logging.info(f"Successfully processed {len(valid_locations)} locations")
    
    # Process boundaries and restructure output
    result = _process_boundaries(valid_locations)
    
    # Update payload with new structure
    payload['boundaries'] = result['boundaries']
    payload['places'] = result['places']
    del payload['locations']  # Remove old locations key
    
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
        dict: Updated payload with consolidated locations
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
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in consolidation: {err}")
        post_slack_log_message('Error consolidating locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
