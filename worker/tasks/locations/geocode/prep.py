import json
import os
import usaddress
import logging
import time
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from duckduckgo_search import DDGS
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _extract_best_address(query, search_results, max_retries=3):
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

def _search_duckduckgo(query, max_results=5, max_retries=3):
    """
    Search DuckDuckGo for location information with retry logic.
    
    Args:
        query (str): Search query
        max_results (int): Maximum number of results to return
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        list: Search results or empty list if search fails
    """
    logging.info(f"Searching DuckDuckGo for: {query}")
    
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                
                if not results:
                    logging.warning(f"No results found for query: {query}")
                    return []
                    
                return results
                
        except Exception as e:
            logging.error(f"Error searching DuckDuckGo (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logging.info("Waiting 3 seconds before retrying...")
                time.sleep(3)
            else:
                logging.error("Max retries exceeded for DuckDuckGo search")
                return []

def _check_if_addressable(location_str):
    """
    Use LLM to determine if a location is likely to have a physical address.
    
    Args:
        location_str (str): Location string to check
        
    Returns:
        bool: True if location is likely addressable, False otherwise
    """
    llm = ChatOpenAI()
    
    template = """Determine if the following location is likely a building or landmark with a physical street address. 
    This might include:
    - Businesses
    - Landmarks
    - Buildings
    - Schools
    - Parks
    - Specific facilities or venues
    
    This would NOT include:
    - General regions or areas
    - Cities, counties or administrative divisions
    - Natural features like lakes or forests
    - Abstract concepts or non-physical locations
    
    Location: {location}
    
    Return ONLY "addressable" or "not addressable":"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    try:
        result = chain.invoke({"location": location_str})
        return result.content.strip().lower() == "addressable"
    except Exception as e:
        logging.error(f"Error checking if location is addressable: {str(e)}")
        return False

########## COMPONENT FUNCTIONS ##########

## Places and addresses

def prep_place(location):
    """
    Prepare a place location for geocoding by first checking if it's likely to have an address
    then searching for and extracting its address if it is.
    """
    try:
        # Get the location string
        loc_str = location.get('location', '')
        if not loc_str:
            return None
            
        # First check if location is likely to have an address
        is_addressable = _check_if_addressable(loc_str)
        logging.info(f"Location '{loc_str}' addressable check result: {is_addressable}")
        
        if is_addressable:
            logging.info(f"Location '{loc_str}' is likely to have an address")
            
            # Search for the location
            query = f"What is the address of {loc_str}?"
            search_results = _search_duckduckgo(query)
            
            if search_results:
                # Extract the best address from search results
                best_address = _extract_best_address(query, search_results)
                logging.info(f"Best address found for '{loc_str}': {best_address}")
                
                if best_address and best_address != "No address found":
                    return {
                        'geocode': "search",
                        'text': best_address
                    }
            
            # If we couldn't find a specific address, fall back to search
            logging.info(f"No specific address found for '{loc_str}', falling back to original text")
            return {
                'geocode': "search",
                'text': location['location']
            }
        else:
            logging.info(f"Location '{loc_str}' is not likely to have an address")
            return {
                'geocode': "search",
                'text': location['location']
            }
            
    except Exception as e:
        logging.error(f"Error in prep_place: {str(e)}")
        return None

def prep_street_road(location):
    """
    Parse a street/road location using usaddress, extract city and state,
    and put the rest in the address field.
    """
    try:
        loc_str = location.get('location', '')
        if not loc_str:
            return None
            
        # Try parsing with usaddress
        try:
            tagged_address, address_type = usaddress.tag(loc_str)
            logging.info(f"\nParsed components for '{loc_str}':")
            logging.info(f"Address type: {address_type}")
            for component, value in tagged_address.items():
                logging.info(f"{component}: {value}")
            
            # Extract city and state if available
            city = tagged_address.get('PlaceName', '')
            state = tagged_address.get('StateName', '')
            
            if city and state:
                # Remove city and state from original string to get address part
                address_part = loc_str
                if city in address_part:
                    address_part = address_part.replace(city, '').strip()
                if state in address_part:
                    address_part = address_part.replace(state, '').strip()
                # Clean up any remaining commas or extra spaces
                address_part = address_part.strip(' ,')
                
                return {
                    'geocode': "structured",
                    'text': location['location'],
                    'address': address_part,
                    'locality': city,
                    'region': state
                }
            else:
                logging.info("Missing required components (city or state)")
                return {
                    'geocode': "search",
                    'text': location['location']
                }
                
        except (usaddress.RepeatedLabelError, ValueError) as e:
            logging.error(f"Could not parse address '{loc_str}': {str(e)}")
            return {
                'geocode': "search",
                'text': location['location']
            }
            
    except Exception as e:
        logging.error(f"Error in prep_street_road: {str(e)}")
        return None

def prep_span(location):
    """
    Process a span location (road segment between points) using LLM.
    Example: "I-35 between Pine City and Hinckley"
    """
    try:
        loc_str = location.get('location', '')
        if not loc_str:
            return None
            
        # Load the roads_spans prompt from local directory
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'roads-spans.txt')
            with open(prompt_path, 'r') as f:
                system_prompt = f.read()
                # Escape JSON examples by doubling curly braces
                system_prompt = system_prompt.replace('{', '{{').replace('}', '}}')
        except FileNotFoundError:
            logging.error("Could not find roads-spans.txt prompt")
            return {
                'geocode': "none",
                'text': location['location']
            }
            
        logging.info(f'Processing span: {loc_str}')
        
        # Set up LLM chain
        llm = ChatOpenAI()
        # Use single braces for our actual template variable
        template = system_prompt + "\n\nHere is the string:\n\n{input}"
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | llm

        # Process with LLM
        try:
            result = chain.invoke({
                "input": loc_str
            })
            processed_data = json.loads(result.content)
            logging.info(f"LLM processed data: {processed_data}")
            
            # Handle case where LLM returns an array of spans
            if isinstance(processed_data, list):

                # Create objects for each part of the span, based on the input object
                spans = []
                for span_data in processed_data:
                    new_span = location.copy()  # Copy all attributes from input
                    new_span['location'] = span_data['parsed_string']  # Replace location with parsed_string
                    new_span['type'] = span_data['type']  # Replace type with LLM output type
                    
                    new_span['geocode'] = {
                        'geocode': "search",
                        'text': new_span['location']
                    }

                    spans.append(new_span)
                return spans
            else:
                # Single object case - shouldn't happen with our prompt but handle anyway
                new_location = location.copy()
                new_location['location'] = processed_data['parsed_string']
                new_location['type'] = processed_data['type']
                return new_location
                
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding LLM response: {str(e)}")
            return {
                'geocode': "none",
                'text': location['location']
            }
            
    except Exception as e:
        logging.error(f"Error processing span {loc_str}: {str(e)}")
        return {
            'geocode': "none",
            'text': location['location']
        }

def prep_address_intersection(location):
    """
    Prep an address_intersection location for geocoding by returning the original text.
    """
    return {
        'geocode': "search",
        'text': location['location']
    }

## Administrative divisions

def prep_neighborhood(location):
    """
    Prep a neighborhood location for geocoding by returning the original text.
    """
    return {
        'geocode': "search",
        'text': location['location']
    }

def prep_city(location):
    """
    Prep a city location for geocoding by returning the original text.
    """
    return {
        'geocode': "search",
        'text': location['location']
    }

def prep_county(location):
    """
    Prep a county location for geocoding by returning the original text.
    """
    return {
        'geocode': "search",
        'text': location['location']
    }

def prep_state(location):
    """
    Prep a state location for geocoding by returning the original text.
    """
    return {
        'geocode': "structured",
        'region': location['location']
    }

## Regions

def prep_region_city(location):
    """
    Prep a region_city location for geocoding by returning the original text.
    """
    return {
        'geocode': "none",
        'text': location['location']
    }

def prep_region_state(location):
    """
    Prep a region_state location for geocoding by returning the original text.
    """
    return {
        'geocode': "none",
        'text': location['location']
    }

def prep_region_national(location):
    """
    Prep a region_national location for geocoding by returning the original text.
    """
    return {
        'geocode': "none",
        'text': location['location']
    }

########## CORE FUNCTION ##########

def _prep_locations(payload):
    """
    Core logic for processing locations through geocoding pipeline.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with prepared locations
        
    Raises:
        Exception: If location preparation fails
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping geocoding prep")
        return payload
        
    # Create a new list for processed results
    processed_data = []
    
    # First process spans because they can create new records
    for i, location in enumerate(locations):
        if location.get('type') == 'span':
            processed_spans = prep_span(location)
            
            if processed_spans:
                if isinstance(processed_spans, list):
                    # Each span already has its geocode set in prep_span
                    processed_data.extend(processed_spans)
                else:
                    # Single span case
                    processed_data.append(processed_spans)
        else:
            # Keep non-span locations as is
            processed_data.append(location)

    # Process all locations through appropriate prep functions
    for location in processed_data:
        # Skip if location already has geocode set (like from span processing)
        if location.get('geocode'):
            continue
            
        if location.get('type') == 'region_state':
            location['geocode'] = prep_region_state(location)
        elif location.get('type') == 'region_city':
            location['geocode'] = prep_region_city(location)
        elif location.get('type') == 'region_national':
            location['geocode'] = prep_region_national(location)
        elif location.get('type') == 'place':
            location['geocode'] = prep_place(location)
        elif location.get('type') == 'street_road':
            location['geocode'] = prep_street_road(location)
        elif location.get('type') == 'address_intersection':
            location['geocode'] = prep_address_intersection(location)
        elif location.get('type') == 'neighborhood':
            location['geocode'] = prep_neighborhood(location)
        elif location.get('type') == 'city':
            location['geocode'] = prep_city(location)
        elif location.get('type') == 'county':
            location['geocode'] = prep_county(location)
        elif location.get('type') == 'state':
            location['geocode'] = prep_state(location)

    # Update payload with processed locations
    payload['locations'] = processed_data
    logging.info("Prepped locations payload: %s" % json.dumps(payload, indent=2))
    return payload

########## TASKS ##########

@celery.task(name="prep_locations", bind=True, max_retries=3)
def _prep_locations_task(self, payload):
    """
    Celery task wrapper for location preparation.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with prepared locations
    """
    try:
        url = payload.get('url')
        
        try:
            return _prep_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location preparation failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location preparation: {str(e)}")
        post_slack_log_message('Error preparing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location preparation: {err}")
        post_slack_log_message('Error preparing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload