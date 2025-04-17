import json, os, usaddress, logging, time, traceback
import usaddress
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from utils.slack import post_slack_log_message
from utils.geocode import get_city_state
from utils.search import search_duckduckgo

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
    llm = ChatOpenAI(model="gpt-4.1")
    
    template = """Given the following search query and multiple search results, identify and return the single most accurate 
    physical address that best answers the query. Format the address in a standard US format.

    If no address is available, or you are not fully confident in the address, return "No address found"

    Do not return any linebreaks or other formatting in the output. Simply return the address as a string.

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

def _check_if_addressable(location_str):
    """
    Use LLM to determine if a location is likely to have a physical address.
    
    Args:
        location_str (str): Location string to check
        
    Returns:
        bool: True if location is likely addressable, False otherwise
    """
    llm = ChatOpenAI(model="gpt-4.1-mini")
    
    template = """You will be given a JSON object with details about a location and its context within a news story Determine if it is likely a building or landmark with a physical street address. 

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

    If the location already contains an address, return "has address".
    
    Location: {location}
    
    Return ONLY "addressable", "not addressable", or "has address":"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    try:
        result = chain.invoke({"location": location_str})
        return result.content
    except Exception as e:
        logging.error(f"Error checking if location is addressable: {str(e)}")
        return False

def _parse_address(location_str):
    """
    Use LLM to determine if a location is likely to have a physical address.
    
    Args:
        location_str (str): Location string to check
        
    Returns:
        str: The physical address
    """
    llm = ChatOpenAI(model="gpt-4.1-mini")
    
    template = """The following string contains a physical address, possibly including some additional text, such
    as the name of a place or a business. Extract and return only the physical address, with no additional text.

    Do not include linebreaks or other formatting in the output. Simply return the address as a string.
    
    Here is the string: {location}"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    try:
        result = chain.invoke({"location": location_str})
        return result.content.strip()
    except Exception as e:
        logging.error(f"Error parsing address from location: {str(e)}")
        return False

########## COMPONENT FUNCTIONS ##########

## Places and addresses

def prep_address(location):
    """
    Prep an address location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "search",
            'text': location['location']
        }
    }

def prep_place(location):
    """
    Prepare a place location for geocoding by first checking if it's likely to have an address
    then searching for and extracting its address if it is.
    """
    try:
        # Get the location string
        loc_str = location.get('location', '')
        if not loc_str:
            return {
                'geocode': {
                    'geocode': "search",
                    'text': ""
                }
            }
            
        # First check if location is likely to have an address
        is_addressable = _check_if_addressable(json.dumps(location))
        logging.info(f"Location '{loc_str}' addressable check result: {is_addressable}")
        
        if is_addressable == "addressable":
            logging.info(f"Location '{loc_str}' is likely to have an address")
            
            # Search for the location
            query = f"What is the address of {loc_str}?"
            search_results = search_duckduckgo(query)
            
            if search_results:
                # Extract the best address from search results
                best_address = _extract_best_address(query, search_results)
                logging.info(f"Best address found for '{loc_str}': {best_address}")
                
                if best_address and best_address != "No address found":
                    return {
                        'geocode': {
                            'geocode': "search",
                            'text': best_address
                        }
                    }
            
            # If we couldn't find a specific address, fall back to search
            logging.info(f"No specific address found for '{loc_str}', falling back to original text")
            return {
                'geocode': {
                    'geocode': "search",
                    'text': location['location']
                }
            }
        elif is_addressable == "has address":
            logging.info(f"Location '{loc_str}' already contains an address")

            address = _parse_address(loc_str)
            logging.info(f"Parsed address: {address}")
            
            return {
                'geocode': {
                    'geocode': "search",
                    'text': address
                }
            }
        else:
            logging.info(f"Location '{loc_str}' is not likely to have an address")
            return {
                'geocode': {
                    'geocode': "search",
                    'text': location['location']
                }
            }
            
    except Exception as e:
        logging.error(f"Error in prep_place: {str(e)}")
        return {
            'geocode': {
                'geocode': "search",
                'text': location['location']
            }
        }

def prep_street_road(location):
    """
    Parse a street/road location using usaddress, extract city and state,
    and put the rest in the address field.
    """
    try:
        loc_str = location.get('location', '')
        if not loc_str:
            return {
                'geocode': {
                    'geocode': "search",
                    'text': ""
                }
            }
            
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
                    'geocode': {
                        'geocode': "structured",
                        'text': location['location'],
                        'address': address_part,
                        'locality': city,
                        'region': state
                    }
                }
            else:
                logging.info("Missing required components (city or state)")
                return {
                    'geocode': {
                        'geocode': "search",
                        'text': location['location']
                    }
                }
                
        except (usaddress.RepeatedLabelError, ValueError) as e:
            logging.error(f"Could not parse address '{loc_str}': {str(e)}")
            return {
                'geocode': {
                    'geocode': "search",
                    'text': location['location']
                }
            }
            
    except Exception as e:
        logging.error(f"Error in prep_street_road: {str(e)}")
        return {
            'geocode': {
                'geocode': "search",
                'text': location['location']
            }
        }

def prep_span(location):
    """
    Process a span location (road segment between points) using LLM.
    Example: "I-35 between Pine City and Hinckley"
    """
    try:
        loc_str = location.get('location', '')
        if not loc_str:
            return {
                'geocode': {
                    'geocode': "none",
                    'text': ""
                }
            }
            
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
                'geocode': {
                    'geocode': "none",
                    'text': location['location']
                }
            }
            
        logging.info(f'Processing span: {loc_str}')
        
        # Set up LLM chain
        llm = ChatOpenAI(model="gpt-4.1-mini")
        # Use single braces for our actual template variable
        template = system_prompt + "\n\nHere is the string:\n\n{input}"
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | llm

        # Process with LLM
        try:
            result = chain.invoke({
                "input": loc_str
            })
            
            # Clean the response content by removing markdown code blocks
            content = result.content.strip()
            if content.startswith('```') and content.endswith('```'):
                content = content[3:-3].strip()
            if content.startswith('json'):
                content = content[4:].strip()
                
            processed_data = json.loads(content)
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
                'geocode': {
                    'geocode': "none",
                    'text': location['location']
                }
            }
            
    except Exception as e:
        logging.error(f"Error processing span {loc_str}: {str(e)}")
        return {
            'geocode': {
                'geocode': "none",
                'text': location['location']
            }
        }

def prep_intersection_highway(location):
    """
    Prep an address_intersection location for geocoding by returning the original text.
    """
    city_state = get_city_state(location['location'])

    if city_state:   
        return {
            'geocode': {
                'geocode': "structured",
                'text': location['location'],
                'locality': city_state['city'],
                'region': city_state['state']
            }
        }
    return {
        'geocode': {
            'geocode': "search",
            'text': location['location']
        }
    }

def prep_intersection_road(location):
    """
    Prep a road_intersection location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "geocodio",
            'text': location['location']
        }
    }

## Administrative divisions

def prep_neighborhood(location):
    """
    Prep a neighborhood location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "search",
            'text': location['location']
        }
    }

def prep_city(location):
    """
    Prep a city location for geocoding by returning the original text.
    """
    city_state = get_city_state(location['location'])
    city = city_state.get('city', '')
    state = city_state.get('state', '')

    if city and state:
        return {
            'geocode': {
                'geocode': "structured",
                'text': location['location'],
                'locality': city,
                'region': state
            }
        }
    return {
        'geocode': {
            'geocode': "search",
            'text': location['location']
        }
    }

def prep_county(location):
    """
    Prep a county location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "search",
            'text': location['location']
        }
    }

def prep_state(location):
    """
    Prep a state location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "structured",
            'region': location['location']
        }
    }

## Regions

def prep_region_city(location):
    """
    Prep a region_city location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "none",
            'text': location['location']
        }
    }

def prep_region_state(location):
    """
    Prep a region_state location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "none",
            'text': location['location']
        }
    }

def prep_region_national(location):
    """
    Prep a region_national location for geocoding by returning the original text.
    """
    return {
        'geocode': {
            'geocode': "none",
            'text': location['location']
        }
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
        if location.get('type') == 'region_state':
            result = prep_region_state(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'region_city':
            result = prep_region_city(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'region_national':
            result = prep_region_national(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'address':
            result = prep_address(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'place':
            result = prep_place(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'street_road':
            result = prep_street_road(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'intersection_highway':
            result = prep_intersection_highway(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'intersection_road':
            result = prep_intersection_road(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'neighborhood':
            result = prep_neighborhood(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'city':
            result = prep_city(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'county':
            result = prep_county(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']
        elif location.get('type') == 'state':
            result = prep_state(location)
            if result and 'geocode' in result:
                location['geocode'] = result['geocode']

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