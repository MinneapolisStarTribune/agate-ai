import json, logging, os, traceback
import usaddress
from collections import defaultdict
from dateutil.parser import parse as date_parse
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from geocodio import GeocodioClient
from geocodio.exceptions import GeocodioDataError
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from dotenv import load_dotenv
from utils.llm import get_json_openai
from utils.slack import post_slack_log_message
from worker.tasks.base import _classify_story
from conf.settings import CELERY_BROKER_URL, CELERY_RESULT_BACKEND,\
    CELERY_QUEUE_NAME, CELERY_BROKER_TRANSPORT_OPTIONS, AZURE_NER_ENDPOINT, AZURE_KEY, GEOCODIO_API_KEY,\
    AZURE_STORAGE_CONTAINER_NAME, AZURE_STORAGE_ACCOUNT_NAME, CONTEXT_API_URL
import requests
import hashlib
from duckduckgo_search import DDGS
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
import time

logging.basicConfig(level=logging.INFO)

load_dotenv()

########## SETTINGS AND SERVICES ##########

# Queue settings. TODO: CLEAN THIS UP FOR ONLY ONE INIT.
celery = Celery(__name__)
celery.conf.broker_url = CELERY_BROKER_URL
celery.conf.result_backend = CELERY_RESULT_BACKEND
celery.conf.task_default_queue = CELERY_QUEUE_NAME
celery.conf.broker_transport_options = CELERY_BROKER_TRANSPORT_OPTIONS

# Initialize the Azure NER client
AZURE_NER_CLIENT = TextAnalyticsClient(
    endpoint=AZURE_NER_ENDPOINT, 
    credential=AzureKeyCredential(AZURE_KEY)
)

# Initialize Geocodio client
GEOCODIO_CLIENT = GeocodioClient(key=GEOCODIO_API_KEY)

# Initialize Azure Blob Storage client
AZURE_BLOB_SERVICE_CLIENT = BlobServiceClient.from_connection_string(
    os.getenv('AZURE_STORAGE_CONNECTION_STRING'))
AZURE_STORAGE_CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME')

########## EXTRACTION HELPER FUNCTIONS ##########

def process_spans(locations):
    """
    Process span locations to extract additional context and details using LLM.
    A span is a road segment between two points, like "I-35 between Pine City and Hinckley"
    
    Args:
        locations (list): List of location dictionaries
        
    Returns:
        list: Updated list of locations with processed spans
    """
    spans = [loc for loc in locations if loc.get('type') == 'span']
    non_spans = [loc for loc in locations if loc.get('type') != 'span']
    
    if not spans:
        return locations
        
    # Load the roads_spans prompt
    try:
        with open('utils/prompts/location_extraction/roads_spans.txt', 'r') as f:
            prompt = f.read()
    except FileNotFoundError:
        logging.error("Could not find roads_spans.txt prompt")
        return locations
        
    processed_spans = []
    for span in spans:
        try:
            logging.info(f'Processing span {span["location"]}...')
            
            # Get processed data from LLM
            processed_data = get_json_openai(prompt, span, force_object=False)
            logging.info(f"LLM processed data for {span}: {processed_data}")
            
            # Handle case where LLM returns an array of spans
            if isinstance(processed_data, list):
                # Unroll the array and add each span
                for new_span in processed_data:
                    new_span_obj = {
                        'original_text': new_span['original_text'],
                        'location': new_span['location'],
                        'type': new_span['type'],
                        'importance': new_span['importance'],
                        'nature': new_span['nature'],
                        'description': new_span.get('description', '')
                    }
                    processed_spans.append(new_span_obj)
            else:
                # Single span case - just add processed data
                span['processed_data'] = processed_data
                processed_spans.append(span)
            
        except Exception as e:
            logging.error(f"Error processing span {span}: {str(e)}")
            raise
    
    # Combine and return processed spans with non-spans
    return non_spans + processed_spans

########## GEOCODING HELPER FUNCTIONS ##########

def check_geocode(location_str, candidates):
    """
    Check if a location is properly geocoded using LLM validation.
    
    Args:
        location_str (str): Original location string
        candidates (list): List of candidate geocoding results
        
    Returns:
        dict: Validation result containing validated status and selected/suggested location
    """
    try:
        # Load the geocoding validation prompt
        with open('utils/prompts/geocode.txt', 'r') as f:
            prompt = f.read()

        user_prompt = f"\n\nHere is the location string: {location_str}\n\nAnd here are the candidates: {candidates}"
        
        # Get validation result from LLM
        result = get_json_openai(prompt, user_prompt, force_object=True)
        logging.info(f"Geocoding validation result for {location_str}: {result}")
        return result
        
    except Exception as e:
        logging.error(f"Error validating geocoding for {location_str}: {str(e)}")
        return {"validated": False}

def create_geography_object(result):
    """
    Create a standardized geography object from a geocoding result.
    
    Args:
        result (dict): Geocoding result from Geocodio
        
    Returns:
        dict: Standardized geography object
    """
    return {
        'formatted_address': result.get('formatted_address'),
        'lat': result['location'].get('lat'),
        'lng': result['location'].get('lng'),
        'accuracy': result.get('accuracy'),
        'accuracy_type': result.get('accuracy_type'),
    }

def extract_best_address(query, search_results, max_retries=3):
    """
    Extract the best matching address from search results using LLM.
    Includes retry logic with 3-second delay between attempts.
    
    Args:
        query (str): Original search query
        search_results (list): List of search result dictionaries
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        str: Best matching address or "No address found"
    """
    llm = ChatOpenAI()
    
    template = """Given the following search query and multiple search results, identify and return the single most accurate 
    physical address that best answers the query. Format the address in a standard US format.

    If no address is available, or you are not fully confident in the address, return "No address found"

    Query: {query}
    
    Search Results:
    {formatted_results}
    
    Return only the best matching address with no additional text:"""
    
    # Format all results into a numbered list
    formatted_results = "\n\n".join([
        f"Result {i+1}:\n"
        f"Title: {result['title']}\n"
        f"Content: {result['body']}"
        for i, result in enumerate(search_results)
    ])
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Attempting to extract address (attempt {attempt + 1}/{max_retries})")
            result = chain.invoke({
                "query": query,
                "formatted_results": formatted_results
            })
            return result.content
        except Exception as e:
            logging.error(f"Error extracting address (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logging.info("Waiting 3 seconds before retrying...")
                time.sleep(3)
            else:
                logging.error("Max retries exceeded for address extraction")
                return "No address found"

def search_duckduckgo(query, max_results=5, max_retries=3):
    """
    Search DuckDuckGo for location information with retry logic.
    
    Args:
        query (str): Search query
        max_results (int): Maximum number of results to return
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        str: Best matching address or "No address found"
    """
    logging.info(f"Named place found. Searching DuckDuckGo for {query}")
    
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                
                if not results:
                    logging.warning(f"No results found for query: {query}")
                    return "No address found"
                
                # Extract best address with retry logic
                best_address = extract_best_address(query, results)
                return best_address
                
        except Exception as e:
            logging.error(f"Error searching DuckDuckGo (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logging.info("Waiting 3 seconds before retrying...")
                time.sleep(3)
            else:
                logging.error("Max retries exceeded for DuckDuckGo search")
                return "No address found"

def try_direct_geocoding(client, location_str, location_type):
    """
    Attempt direct geocoding of a location string.
    
    Args:
        client: Geocodio client instance
        location_str (str): Location string to geocode
        location_type (str): Type of location
        
    Returns:
        tuple: (geography dict or None, error message or None)
    """
    try:
        if location_type == 'place':
            query = f'What is the address of {location_str}?'
            search_result = search_duckduckgo(query)
            if search_result != "No address found":
                logging.info(f"Address found: {search_result}")
                location_str = search_result
            else:
                logging.info(f"No address found for {location_str}")
        
        result = client.geocode(location_str)

        if not result or not result.get('results'):
            return None, "No results found"
            
        candidates = result['results']
        first_result = candidates[0]
        
        # If geocoder is certain, use result directly
        if first_result.get('accuracy') == 1:
            return create_geography_object(first_result), None
            
        # Otherwise validate with LLM
        validation = check_geocode(location_str, candidates)
        if validation.get('validated'):
            return create_geography_object(validation['candidate']), None
        elif validation.get('suggested_location'):
            # Try geocoding the suggested location
            new_result = client.geocode(validation['suggested_location'])
            if new_result and new_result.get('results'):
                general_result = new_result['results'][0]
                if general_result.get('accuracy', 0) >= 0.9:
                    return create_geography_object(general_result), None
                else:
                    return create_geography_object({
                        'formatted_address': validation['suggested_location'],
                        'location': {
                            'lat': None,
                            'lng': None
                        },
                        'accuracy': None,
                        'accuracy_type': validation['suggested_location_type']
                    }), None
                    
        return None, "Failed validation"
        
    except GeocodioDataError as e:
        return None, str(e)
    except Exception as e:
        logging.error(f"Error in direct geocoding for {location_str}: {str(e)}")
        return None, str(e)

def try_city_state_fallback(client, location_str):
    """
    Attempt to geocode by extracting and looking up city/state.
    
    Args:
        client: Geocodio client instance
        location_str (str): Location string to geocode
        
    Returns:
        dict or None: Geography object if successful, None otherwise
    """
    try:
        # Try parsing with Geocodio first
        components = client.parse(location_str).get('address_components', {})
        if components.get('city') and components.get('state'):
            city_str = f"{components['city']}, {components['state']}"
        else:
            # Fallback to usaddress parser
            components = usaddress.tag(location_str)
            if 'PlaceName' in components[0] and 'StateName' in components[0]:
                city_str = f"{components[0]['PlaceName']}, {components[0]['StateName']}"
                
        result = client.geocode(city_str)
        if result and result.get('results'):
            return create_geography_object(result['results'][0])
        else:
            suggestion = check_geocode(location_str, None)
            if suggestion.get('suggested_location'):
                # Try geocoding the suggested location
                new_result = client.geocode(suggestion['suggested_location'])
                if new_result and new_result.get('results'):
                    general_result = new_result['results'][0]
                    if general_result.get('accuracy', 0) >= 0.9:
                        return create_geography_object(general_result)
                
                # If geocoding fails or accuracy is low, return suggested location
                return create_geography_object({
                    'formatted_address': suggestion['suggested_location'],
                    'location': {
                        'lat': None,
                        'lng': None
                    },
                    'accuracy': None,
                    'accuracy_type': suggestion.get('suggested_location_type', None)
                })
            
    except (GeocodioDataError, Exception) as e:
        logging.warning(f"City/state fallback failed for {location_str}: {str(e)}")
        
    return None

def set_context_level(location):
    """
    Set the context level based on geocoding accuracy type.
    
    Args:
        location (dict): Location object with geography data
        
    Returns:
        str: Determined context level
    """
    accuracy_level = location.get('geography', {}).get('accuracy_type', '').lower()
    
    if accuracy_level in ['rooftop', 'point', 'intersection', 'range_interpolation', 'nearest_rooftop_match']:
        return 'boundary'
    elif accuracy_level in ['street_center', 'place', 'city']:
        if location.get('type') == 'neighborhood':
            return 'neighborhood'
        else:
            return 'city'
    elif accuracy_level == 'county':
        return 'county'
    else:
        return 'state'

########## CONTEXT HELPER FUNCTIONS ##########

def lookup_context(location_type, location_name, context_level=''):
    """
    Get context data for a location based on its type.
    
    Args:
        location_type (str): Type of location (state, county, city, etc.)
        location_name (str): Name of the location
        context_level (str): Context level from geocoding
        
    Returns:
        dict: Context data if successful, None if not
    """
    endpoint_map = {
        'state': 'state',
        'county': 'county',
        'city': 'city',
        'neighborhood': 'neighborhood',
        'region_state': 'city'  # region_state uses city endpoint
    }
    
    if location_type not in endpoint_map:
        return None
        
    endpoint = endpoint_map[location_type]
    logging.info(f"Looking up {endpoint} context for: {location_name}")
    
    try:
        response = requests.get(
            CONTEXT_API_URL + f"locations/{endpoint}",
            params={'q': location_name}
        )
        response.raise_for_status()
        context_data = response.json()
        
        # Special handling for city and region_state types
        if location_type in ['city', 'region_state']:
            if not context_data or context_data.get('match_quality', 0) <= 0.6:
                logging.info(f"Low match quality for {location_type} context: {location_name}")
                return None
                
        return context_data
        
    except Exception as e:
        logging.error(f"Error getting context for {location_type} {location_name}: {str(e)}")
        return None

def get_boundary_context(lat, lng, context_level):
    """
    Get boundary context data for a location with coordinates.
    
    Args:
        lat (float): Latitude
        lng (float): Longitude
        context_level (str): Level of context to get
        
    Returns:
        dict: Boundary context data if successful, None if not
    """
    # Set include parameter based on context level
    include_map = {
        'boundary': 'region,state,county,city,neighborhood',
        'neighborhood': 'region,state,county,city,neighborhood',
        'city': 'region,state,county,city',
        'county': 'region,state,county',
        'state': 'region,state'
    }
    
    params = {
        'lat': lat,
        'lng': lng,
        'include': include_map.get(context_level, 'state')
    }
    
    try:
        response = requests.get(
            CONTEXT_API_URL + "locations/boundary",
            params=params
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error getting boundary context for coordinates ({lat}, {lng}): {str(e)}")
        return None

def process_location_context(location):
    """
    Process context for a single location.
    
    Args:
        location (dict): Location dictionary to process
        
    Returns:
        dict: Updated location with context data
    """
    try:
        location_type = location.get('type', '').lower()
        context_level = location.get('context_level', '').lower()
        location_name = location.get('geography', {}).get('formatted_address', '') or location.get('location', '')
        
        # Initialize geography dict if it doesn't exist
        if not location.get('geography'):
            location['geography'] = {}

        # Dumb hack to deal with named neighborhoods for now
        if location_type == 'neighborhood':
            location_name = location.get('location')
            location['geography'] = {}

        # Handle locations without coordinates
        if not location['geography'].get('lat') or not location['geography'].get('lng'):
            context_data = lookup_context(location_type, location_name)
            if context_data:
                location['geography']['boundaries'] = context_data
        else:
            # Handle locations with coordinates
            logging.info(f"Coordinates found for {location_name}, processing with /boundary")
            boundary_data = get_boundary_context(
                location['geography']['lat'],
                location['geography']['lng'],
                context_level
            )
            if boundary_data:
                location['geography']['boundaries'] = boundary_data
                
    except Exception as e:
        logging.error(f"Error processing context for location {location_name}: {str(e)}")
        
    return location

########## CONSOLIDATION HELPER FUNCTIONS ##########

def initialize_boundaries(locations):
    """
    Initialize boundary containers and collect all unique boundaries from locations.
    
    Args:
        locations (list): List of location dictionaries
        
    Returns:
        dict: Consolidated boundaries with their metadata
    """
    consolidated = {
        "states": defaultdict(lambda: {"places": set()}),  # Changed to set
        "regions": defaultdict(lambda: {"places": set()}),  # Changed to set
        "counties": defaultdict(lambda: {"places": set()}),  # Changed to set
        "cities": defaultdict(lambda: {"places": set()}),  # Changed to set
        "neighborhoods": defaultdict(lambda: {"places": set()}),  # Changed to set
        "places": []
    }

    for loc in locations:
        geography = loc.get('geography', {})
        boundaries = geography.get('boundaries', {})
        
        # Process state boundary
        state = boundaries.get('state')
        if state:
            state_id = state['id'] if isinstance(state, dict) else state
            if state_id not in consolidated['states']:
                consolidated['states'][state_id] = {
                    "id": state_id,
                    "places": set(),  # Changed to set
                    "name": state['name'] if isinstance(state, dict) else None,
                    "centroid": state.get('centroid', {}) if isinstance(state, dict) else {}
                }
        
        # Process county boundary
        county = boundaries.get('county')
        if county:
            county_id = county['id'] if isinstance(county, dict) else county
            if county_id not in consolidated['counties']:
                consolidated['counties'][county_id] = {
                    "id": county_id,
                    "places": set(),  # Changed to set
                    "name": county['name'] if isinstance(county, dict) else None,
                    "centroid": county.get('centroid', {}) if isinstance(county, dict) else {}
                }
        
        # Process city boundary
        city = boundaries.get('city')
        if city:
            city_id = city['id'] if isinstance(city, dict) else city
            if city_id not in consolidated['cities']:
                consolidated['cities'][city_id] = {
                    "id": city_id,
                    "places": set(),  # Changed to set
                    "name": city['name'] if isinstance(city, dict) else None,
                    "centroid": city.get('centroid', {}) if isinstance(city, dict) else {}
                }
        
        # Process neighborhood boundary
        neighborhood = boundaries.get('neighborhood')
        if neighborhood:
            neighborhood_id = neighborhood['id'] if isinstance(neighborhood, dict) else neighborhood
            if neighborhood_id not in consolidated['neighborhoods']:
                consolidated['neighborhoods'][neighborhood_id] = {
                    "id": neighborhood_id,
                    "places": set(),  # Changed to set
                    "name": neighborhood['name'] if isinstance(neighborhood, dict) else None,
                    "centroid": neighborhood.get('centroid', {}) if isinstance(neighborhood, dict) else {}
                }
        
        # Process regions
        regions = boundaries.get('regions')
        if regions:
            if isinstance(regions, list):
                for region in regions:
                    region_id = region['id'] if isinstance(region, dict) else region
                    if region_id not in consolidated['regions']:
                        consolidated['regions'][region_id] = {
                            "id": region_id,
                            "places": set(),  # Changed to set
                            "name": region['name'] if isinstance(region, dict) else None,
                            "centroid": region.get('centroid', {}) if isinstance(region, dict) else {}
                        }
            else:
                region_id = regions['id'] if isinstance(regions, dict) else regions
                if region_id not in consolidated['regions']:
                    consolidated['regions'][region_id] = {
                        "id": region_id,
                        "places": set(),  # Changed to set
                        "name": regions['name'] if isinstance(regions, dict) else None,
                        "centroid": regions.get('centroid', {}) if isinstance(regions, dict) else {}
                    }
    
    return consolidated

def associate_places(locations, consolidated):
    """
    Process all places and associate them with their boundaries.
    Handles deduplication of places with the same ID by:
    1. Combining descriptions into a single string
    2. Preserving primary importance/nature over secondary
    3. Using first primary if multiple primaries exist
    
    Args:
        locations (list): List of location dictionaries
        consolidated (dict): Dictionary containing initialized boundaries
        
    Returns:
        dict: Updated consolidated structure with places associated to boundaries
    """
    # Dictionary to track unique places by ID
    unique_places = {}
    
    for loc in locations:
        # Generate place_id from coordinates if available, otherwise use location name
        if loc.get('geography', {}).get('lat') and loc.get('geography', {}).get('lng'):
            coord_str = f"{loc['geography']['lat']}{loc['geography']['lng']}"
            place_id = hashlib.md5(coord_str.encode()).hexdigest()
        else:
            place_id = hashlib.md5(loc['location'].encode()).hexdigest()
            
        # Create or update place object
        if place_id in unique_places:
            existing_place = unique_places[place_id]
            
            # Combine descriptions if they exist and are different
            existing_desc = existing_place.get('description', '')
            new_desc = loc.get('description', '')
            if new_desc and new_desc != existing_desc:
                if existing_desc:
                    existing_place['description'] = f"{existing_desc}; {new_desc}"
                else:
                    existing_place['description'] = new_desc
            
            # Handle importance and nature
            existing_importance = existing_place.get('importance', '')
            new_importance = loc.get('importance', '')
            
            # If new item is primary and existing is not, use new importance/nature
            if new_importance == 'primary' and existing_importance != 'primary':
                existing_place['importance'] = new_importance
                existing_place['nature'] = loc.get('nature', '')
            # If both are primary, keep the first one (already stored)
            # If neither is primary or existing is primary, keep existing
            
        else:
            # Create new place object
            unique_places[place_id] = {
                "id": place_id,
                "original_text": loc.get('original_text', ''),
                "location": loc.get('location', ''),
                "type": loc.get('type', ''),
                "importance": loc.get('importance', ''),
                "nature": loc.get('nature', ''),
                "description": loc.get('description', ''),
                "geography": loc.get('geography', {}),
                "context_level": loc.get('context_level', '')
            }
        
        # Get boundaries from geography
        boundaries = loc.get('geography', {}).get('boundaries', {})
        
        # Associate with boundaries using sets for uniqueness
        state = boundaries.get('state')
        if state:
            state_id = state['id'] if isinstance(state, dict) else state
            if state_id in consolidated['states']:
                consolidated['states'][state_id]['places'].add(place_id)
        
        county = boundaries.get('county')
        if county:
            county_id = county['id'] if isinstance(county, dict) else county
            if county_id in consolidated['counties']:
                consolidated['counties'][county_id]['places'].add(place_id)
        
        city = boundaries.get('city')
        if city:
            city_id = city['id'] if isinstance(city, dict) else city
            if city_id in consolidated['cities']:
                consolidated['cities'][city_id]['places'].add(place_id)
        
        neighborhood = boundaries.get('neighborhood')
        if neighborhood:
            neighborhood_id = neighborhood['id'] if isinstance(neighborhood, dict) else neighborhood
            if neighborhood_id in consolidated['neighborhoods']:
                consolidated['neighborhoods'][neighborhood_id]['places'].add(place_id)
        
        regions = boundaries.get('regions')
        if regions:
            if isinstance(regions, list):
                for region in regions:
                    region_id = region['id'] if isinstance(region, dict) else region
                    if region_id in consolidated['regions']:
                        consolidated['regions'][region_id]['places'].add(place_id)
            else:
                region_id = regions['id'] if isinstance(regions, dict) else regions
                if region_id in consolidated['regions']:
                    consolidated['regions'][region_id]['places'].add(place_id)
    
    # Update consolidated places with deduplicated list
    consolidated['places'] = list(unique_places.values())
    
    # Convert sets to lists before returning
    for boundary_type in ['states', 'regions', 'counties', 'cities', 'neighborhoods']:
        for boundary in consolidated[boundary_type].values():
            boundary['places'] = list(boundary['places'])
    
    return consolidated

def clean_places(consolidated):
    """
    Clean up the consolidated structure and format it for output.
    Remove boundaries from places and convert defaultdicts to lists.
    
    Args:
        consolidated (dict): Dictionary containing places and boundaries
        
    Returns:
        dict: Final cleaned and formatted result
    """
    result = {
        "locations": {
            "states": list(consolidated['states'].values()),
            "regions": list(consolidated['regions'].values()),
            "counties": list(consolidated['counties'].values()),
            "cities": list(consolidated['cities'].values()),
            "neighborhoods": list(consolidated['neighborhoods'].values()),
            "places": []
        }
    }

    # Process places to remove boundaries before adding to result
    for place in consolidated['places']:
        place_copy = place.copy()
        if 'geography' in place_copy:
            geography_copy = place_copy['geography'].copy()
            if 'boundaries' in geography_copy:
                del geography_copy['boundaries']
            place_copy['geography'] = geography_copy
        result['locations']['places'].append(place_copy)

    return result

def consolidate_geographies(locations):
    """
    Consolidates redundant geographies from a list of locations into a structured hierarchy.
    Each unique geography is included once, with combined metadata and associated places.
    
    Args:
        locations (list): List of location dictionaries
        
    Returns:
        dict: Structured hierarchy of consolidated geographies
    """
    # Step 1: Initialize and collect boundaries
    consolidated = initialize_boundaries(locations)
    
    # Step 2: Process and associate places with boundaries
    consolidated = associate_places(locations, consolidated)
    
    # Step 3: Clean up and format the final result
    result = clean_places(consolidated)
    
    return result

def process_consolidated_geographies(consolidated):
    """
    Processes consolidated geographies to create a structure with:
    1. boundaries: Dictionary of distinct geographic boundaries organized by type
    2. places: All specific places mentioned, unmodified from input
    """
    result = {
        "boundaries": {
            "states": [],
            "regions": [],
            "counties": [],
            "cities": [],
            "neighborhoods": []
        },
        "places": consolidated["locations"]["places"]
    }
    
    # Map plural to singular for type names
    type_mapping = {
        "states": "state",
        "counties": "county",
        "cities": "city",
        "neighborhoods": "neighborhood",
        "regions": "region"
    }
    
    # Process all boundary types
    for boundary_type in ["states", "counties", "cities", "neighborhoods", "regions"]:
        boundaries = consolidated["locations"].get(boundary_type, [])
        if not boundaries:
            logging.info(f"No {boundary_type} found in consolidated data")
            continue
            
        for boundary in boundaries:
            if isinstance(boundary, dict):
                boundary_id = boundary.get('id')
                boundary_name = boundary.get('name', '')
                centroid = boundary.get('centroid', {})
                places = boundary.get('places', [])
                
                if boundary_id:  # Only add if we have an ID
                    boundary_obj = {
                        "id": boundary_id,
                        "name": boundary_name,
                        "type": type_mapping[boundary_type],
                        "geography": {
                            "lat": centroid.get("lat"),
                            "lng": centroid.get("lon", centroid.get("lng"))  # Try both lon and lng
                        },
                        "places": places
                    }
                    result["boundaries"][boundary_type].append(boundary_obj)
                    logging.info(f"Added {boundary_type} boundary: {boundary_id}")
            else:
                logging.warning(f"Skipping non-dict boundary in {boundary_type}")
    
    # Ensure all boundary arrays exist even if empty
    for boundary_type in result["boundaries"]:
        if result["boundaries"][boundary_type] is None:
            result["boundaries"][boundary_type] = []
            
    return result

########## EDITORIAL REVIEW HELPER FUNCTIONS ##########

def review_locations(locations, text, headline):
    """
    Performs a final editorial review of extracted locations to filter out incorrect or out-of-place entries.
    
    Args:
        locations (list): List of location dictionaries to review
        text (str): The article text for context
        headline (str): The article headline for context
        
    Returns:
        tuple: (filtered_locations, review_results)
            - filtered_locations (list): Filtered list of locations with accurate and relevant entries
            - review_results (dict): Full results of the review with decisions and rationales
    """
    try:
        # Load the editorial review prompt
        try:
            with open('utils/prompts/editorial_review.txt', 'r') as f:
                prompt = f.read()
        except FileNotFoundError:
            logging.error("Editorial review prompt not found, creating default prompt")
            prompt = """You are a discerning news editor reviewing locations extracted from a news article. 
Your job is to identify and remove any locations that:
1. Are incorrect or don't exist
2. Are out of place or irrelevant to the story
3. Would confuse readers or diminish their trust in the product
4. Are mentioned only in passing and not relevant to the main story
5. Are ambiguous or could be confused with other places

For each location, determine if it should be KEPT or REMOVED. Return a JSON object with your decisions:
{
  "decisions": [
    {
      "location": "The location string",
      "decision": "KEEP or REMOVE",
      "reason": "Brief explanation of your decision"
    }
  ]
}"""
        
        # Prepare context for LLM
        context = {
            "headline": headline,
            "text": text,
            "locations": locations
        }
        
        # Get decisions from LLM
        results = get_json_openai(prompt, context, force_object=True)
        logging.info(f"Editorial review decisions: {results}")
        
        # Filter locations based on decisions
        if not results or "decisions" not in results:
            logging.error("Invalid response from editorial review")
            return locations, {"decisions": []}
            
        filtered_locations = []
        for location in locations:
            location_str = location.get("location", "")
            # Find the corresponding decision
            decision = next((d for d in results["decisions"] if d.get("location") == location_str), None)
            
            if not decision:
                # If no decision found, keep the location
                filtered_locations.append(location)
                logging.info(f"No editorial decision found for '{location_str}', keeping it")
                
                # Add implicit KEEP decision for this location
                if "decisions" in results:
                    results["decisions"].append({
                        "location": location_str,
                        "decision": "KEEP",
                        "reason": "No explicit decision was made, so location was kept by default"
                    })
                continue
                
            if decision.get("decision") == "KEEP":
                filtered_locations.append(location)
                logging.info(f"Keeping location '{location_str}': {decision.get('reason')}")
            else:
                logging.info(f"Removing location '{location_str}': {decision.get('reason')}")
                
        return filtered_locations, results
        
    except Exception as e:
        logging.error(f"Error in editorial review: {str(e)}")
        return locations, {"decisions": []}  # Return original locations if review fails

########## PRIVATE TASK FUNCTIONS ##########

@celery.task(name="extract_locations", bind=True, max_retries=3)
def _extract_locations(self, payload):
    """
    Extracts locations from a story using LLM.
    Uses base prompt plus story-type-specific prompt if available.
    """
    try:
        story_type = payload.get('story_type', {}).get('category')
        text = payload.get('text')
        url = payload.get('url')
        
        if not text:
            logging.info("No text provided, skipping location extraction")
            return payload
            
        # Get the base prompt
        try:
            with open('utils/prompts/location_extraction/base.txt', 'r') as f:
                prompt = f.read()
        except FileNotFoundError:
            logging.error("Base location prompt not found")
            return payload
            
        # Try to get story-type-specific prompt
        try:
            type_prompt_path = f'utils/prompts/location_extraction/_{story_type}.txt'
            with open(type_prompt_path, 'r') as f:
                prompt += "\n\n" + f.read()
        except FileNotFoundError:
            # If no specific prompt exists, use default
            prompt += "\n\nHere is the text of the article:"
            
        try:
            # Clean text and construct user prompt
            cleaned_text = text.replace('\n', ' ')
            user_prompt = f"{cleaned_text}"
            
            # Pass to LLM for location extraction
            locations = get_json_openai(prompt, user_prompt, force_object=True)
            logging.info(f"Extracted locations: {locations}")
            
            # Add locations to payload
            payload['locations'] = locations.get('locations')

            # Check if any spans exist in the locations
            if payload.get('locations') and any(loc.get('type') == 'span' for loc in payload['locations']):
                payload['locations'] = process_spans(payload['locations'])

            payload['url'] = url
            # Preserve output_filename
            payload['output_filename'] = payload.get('output_filename')
            logging.info("Extracted locations payload: %s" % json.dumps(payload, indent=2))
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location extraction failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location extraction: {str(e)}")
        post_slack_log_message('Error extracting locations %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location extraction: {err}")
        post_slack_log_message('Error extracting locations %s' % url, {
            'error_message':  str(err.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload


@celery.task(name="geocode", bind=True, max_retries=3)
def _geocode(self, payload):
    """
    Geocodes the locations using Geocodio API.
    """
    try:
        locations = payload.get('locations', [])
        url = payload.get('url')
        
        if not locations:
            logging.info("No locations to geocode")
            return payload
            
        # Define valid location types for geocoding
        geocodable_types = ['place', 'address_intersection', 'neighborhood', 'city', 'street_road', 'county']
        
        geocoded_locations = []
        for location in locations:
            if location.get('type') not in geocodable_types:
                geocoded_locations.append(location)
                continue
            
            try:
                location_str = location['location']
                logging.info(f"Geocoding location: {location_str}")
                
                # Try direct geocoding first
                geography, error = try_direct_geocoding(GEOCODIO_CLIENT, location_str, location.get('type'))

                # If direct geocoding fails, try city/state fallback
                if not geography:
                    logging.info(f"Direct geocoding failed ({error}), trying city/state fallback")
                    geography = try_city_state_fallback(GEOCODIO_CLIENT, location_str)
                
                # Update location with geocoding results
                if geography:
                    location['geography'] = geography
                    location['context_level'] = set_context_level(location)
                else:
                    location['geography'] = {}
                    location['context_level'] = 'state'  # Default to state level if geocoding fails
                    
            except Exception as e:
                logging.error(f"Error processing location {location_str}: {str(e)}")
                location['geography'] = {}
                location['context_level'] = 'state'
                
            geocoded_locations.append(location)
        
        # Update payload with geocoded locations
        payload['locations'] = geocoded_locations
        # Preserve output_filename
        payload['output_filename'] = payload.get('output_filename')
        logging.info("Geocoding payload: %s" % json.dumps(payload, indent=2))

        return payload
        
    except MaxRetriesExceededError as max_retries_err:
        logging.error(f"Max retries exceeded for geocoding: {str(max_retries_err)}")
        post_slack_log_message('Error geocoding locations %s (max retries exceeded)' % url, {
            'error_message': str(max_retries_err),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload

    except Exception as e:
        backoff = 2 ** self.request.retries
        logging.error(f"Geocoding failed, retrying in {backoff} seconds. Error: {str(e)}")
        raise self.retry(exc=e, countdown=backoff)


@celery.task(name="context", bind=True, max_retries=3)
def _context(self, payload):
    """
    Canonicalize and contextualize locations.
    """
    try:
        logging.info("Contextualizing locations")
        locations = payload.get('locations', [])
        url = payload.get('url')

        if not locations:
            logging.info("No locations to contextualize")
            return payload

        contextualized_locations = []
        
        for location in locations:
            try:
                processed_location = process_location_context(location)
                contextualized_locations.append(processed_location)
            except Exception as e:
                logging.error(f"Error processing location {location.get('location', '')}: {str(e)}")
                contextualized_locations.append(location)  # Keep original if processing fails

        # Update payload with contextualized locations
        payload['locations'] = contextualized_locations
        # Preserve output_filename
        payload['output_filename'] = payload.get('output_filename')

        logging.info("Context payload: %s" % json.dumps(payload, indent=2))
        return payload

    except MaxRetriesExceededError as max_retries_err:
        logging.error(f"Max retries exceeded for context: {str(max_retries_err)}")
        post_slack_log_message('Error getting context for locations %s (max retries exceeded)' % url, {
            'error_message': str(max_retries_err),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload

    except Exception as e:
        backoff = 2 ** self.request.retries
        logging.error(f"Context failed, retrying in {backoff} seconds. Error: {str(e)}")
        raise self.retry(exc=e, countdown=backoff)


@celery.task(name="consolidate", bind=True, max_retries=3)
def _consolidate(self, payload):
    """
    Cross-checks the locations against the article text.
    """
    try:
        locations = payload.get('locations', [])
        text = payload.get('text', '')
        url = payload.get('url')

        if not locations:
            logging.info("No locations provided, skipping consolidation")
            return payload

        try:
            # First consolidate the geographies
            consolidated = consolidate_geographies(locations)
            
            # Then process the consolidated geographies
            result = process_consolidated_geographies(consolidated)

            logging.info("Consolidated result: %s" % json.dumps(result, indent=2))

            # Update payload with consolidated results
            payload['locations'] = result
            payload['output_filename'] = payload.get('output_filename')
            return payload
        
        except Exception as e:
            logging.error(f"Error consolidating locations: {str(e)}")
            return payload
    
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for consolidation: {str(e)}")
        post_slack_log_message('Error consolidating locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload  
    
    except Exception as e:
        logging.error(f"Error in consolidation: {e}")
        post_slack_log_message('Error consolidating locations %s' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload


@celery.task(name="save_to_azure", bind=True, max_retries=3)
def _save_to_azure(self, payload):
    """
    Saves the payload to Azure Blob Storage.
    """
    try:
        logging.info('Saving to Azure:')
        logging.info(json.dumps(payload, indent=2))

        logging.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        # Get task ID and URL from the request
        task_id = self.request.id
        url = payload.get('url')
        
        try:
            # Get container client
            container_client = AZURE_BLOB_SERVICE_CLIENT.get_container_client(
                AZURE_STORAGE_CONTAINER_NAME)
            
            # Get output filename from payload
            blob_name = payload.get('output_filename')
            logging.info(f"Payload contents: {json.dumps(payload, indent=2)}")
            logging.info(f"Container name: {AZURE_STORAGE_CONTAINER_NAME}, Blob name: {blob_name}")
            
            if not blob_name:
                raise ValueError("Missing output_filename in payload")
                          
            # Convert payload to JSON string
            json_data = json.dumps(payload, indent=2)
            
            # Upload to blob storage
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(
                json_data, 
                overwrite=True,
                content_type='application/json'
            )
            
            # Construct the blob URL
            storage_account = AZURE_STORAGE_ACCOUNT_NAME
            container_name = AZURE_STORAGE_CONTAINER_NAME
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_name}"
            
            logging.info(f"Successfully saved payload to blob: {blob_name}")
            # post_slack_log_message(f"Successfully processed locations!", {
            #     'agate_update_msg': "View the payload below:",
            #     'storage_url': blob_url,
            #     'headline': payload.get('headline', ''),
            #     'article_url': payload.get('url', '')
            # }, 'create_success')

            return payload
            
        except Exception as e:
            # Calculate backoff time: 2^retry_count seconds
            backoff = 2 ** self.request.retries
            logging.error(f"Save to Azure failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for Azure save: {str(e)}")
        post_slack_log_message('Error saving to Azure %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as e:
        logging.error(f"Error in saving to Azure: {e}")
        post_slack_log_message('Error saving to Azure %s' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload