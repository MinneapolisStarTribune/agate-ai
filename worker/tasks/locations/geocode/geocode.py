import requests, json, logging, traceback
from conf.settings import GEOCODE_EARTH_API_KEY
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

# Geocoding

def pelias_geocode_search(text):
    """
    Geocode a location using the Pelias Geocode Earth search API.
    """
    query = "https://api.geocode.earth/v1/search?" \
            "api_key="+GEOCODE_EARTH_API_KEY+"&"\
            "text="+text
    try:
        response = requests.get(query).json()

        candidates = []
        for f in response.get('features'):
            candidate = {
                "id": f.get("properties").get("id"),
                "label": f.get("properties").get("label"),
                "geometry": f.get("geometry"),
                "confidence": {
                    "score": f.get("properties").get("confidence"),
                    "match_type": f.get("properties").get("match_type"),
                    "accuracy": f.get("properties").get("accuracy")
                },
                "boundaries": {
                    "city": {
                        "id": f.get("properties").get("locality_gid"),
                        "name": f.get("properties").get("locality"),
                    },
                    "county": { 
                        "id": f.get("properties").get("county_gid"),
                        "name": f.get("properties").get("county"),
                    },
                    "state": {
                        "id": f.get("properties").get("region_gid"),
                        "name": f.get("properties").get("region"),
                    }
                }
            }
            candidates.append(candidate)
        return candidates
    except Exception as e:
        logging.error(f"Error geocoding {text}: {str(e)}")
        return None


def pelias_geocode_structured(address_obj):
    """
    Geocode a location using the Pelias Geocode Earth structured API.
    """
    # Build query parameters
    params = [f"api_key={GEOCODE_EARTH_API_KEY}"]
    
    # Add available components to query
    if address_obj.get('address'):
        params.append(f"address={requests.utils.quote(address_obj['address'])}")
    if address_obj.get('neighborhood'):
        params.append(f"neighbourhood={requests.utils.quote(address_obj['neighborhood'])}")
    if address_obj.get('locality'):
        params.append(f"locality={requests.utils.quote(address_obj['locality'])}")
    if address_obj.get('county'):
        params.append(f"county={requests.utils.quote(address_obj['county'])}")
    if address_obj.get('region'):
        params.append(f"region={requests.utils.quote(address_obj['region'])}")
    if address_obj.get('country'):
        params.append(f"country={requests.utils.quote(address_obj['country'])}")
    if address_obj.get('postalcode'):
        params.append(f"postalcode={requests.utils.quote(address_obj['postalcode'])}")
            
    if len(params) == 1:  # Only API key
        logging.warning("No address components provided for structured geocoding")
        return None
            
    # Construct the query URL
    query = "https://api.geocode.earth/v1/search/structured?" + "&".join(params)
    
    try:
        response = requests.get(query).json()

        candidates = []
        for f in response.get('features'):
            candidate = {
                "id": f.get("properties").get("id"),
                "label": f.get("properties").get("label"),
                "geometry": f.get("geometry"),
                "confidence": {
                    "score": f.get("properties").get("confidence"),
                    "match_type": f.get("properties").get("match_type"),
                    "accuracy": f.get("properties").get("accuracy")
                },
                "boundaries": {
                    "city": {
                        "id": f.get("properties").get("locality_gid"),
                        "name": f.get("properties").get("locality"),
                    },
                    "county": { 
                        "id": f.get("properties").get("county_gid"),
                        "name": f.get("properties").get("county"),
                    },
                    "state": {
                        "id": f.get("properties").get("region_gid"),
                        "name": f.get("properties").get("region"),
                    }
                }
            }
            candidates.append(candidate)
        return candidates
    except Exception as e:
        logging.error(f"Error in structured geocoding: {str(e)}")
        return None

# Checking and validation

def check_candidates(original_text, original_context, candidates, max_retries=3):
    """
    Use LLM to select the best candidate from multiple geocoding results.
    Only uses LLM if there are multiple candidates.
    """
    if not candidates:
        return None
        
    # If there's only one candidate, return it directly
    if len(candidates) == 1:
        logging.info("Single candidate found, returning directly")
        return candidates[0]
        
    llm = ChatOpenAI()
    
    template = """I will provide you an address string, along with its original context and the response of a geocoder that presents 
    several candidates for matching that address string. Please analyze each candidate and determine which one best matches the location.

    Take into account any local knowledge you have about the locations, such as other names for streets or cities, or anything else
    you know about the area.

    If no candidate is a good match, respond with exactly "none". If multiple candidates are a good match, respond with the index
    number (1-based) of the first suitable candidate. Otherwise, respond with the index number (0-based) of the best matching candidate.
    
    Respond ONLY with the number or "none", no other text.

    Text to geocode: {original_text}
    Original context: {original_context}

    Candidates:
    {formatted_candidates}

    Your response (just the number or "none"):"""
    
    # Format candidates into a numbered list with relevant details
    formatted_candidates = "\n\n".join([
        f"Candidate {i+1}:\n"
        f"Label: {c['label']}\n"
        f"City: {c['boundaries']['city']['name'] or 'N/A'}\n"
        f"County: {c['boundaries']['county']['name'] or 'N/A'}\n"
        f"State: {c['boundaries']['state']['name'] or 'N/A'}\n"
        f"Confidence Score: {c['confidence']['score']}\n"
        f"Match Type: {c['confidence']['match_type']}"
        for i, c in enumerate(candidates)
    ])
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Multiple candidates found ({len(candidates)}), checking with LLM (attempt {attempt + 1}/{max_retries})")
            result = chain.invoke({
                "original_text": original_text,
                "original_context": original_context,
                "formatted_candidates": formatted_candidates
            })
            
            response = result.content.strip().lower()
            logging.info(f"LLM response: {response}")
            
            # If there is not a good candidate, return None
            if response == "none":
                return None
                
            # Get the best candidate using the index from the LLM response
            try:
                index = int(response)
                if 0 <= index < len(candidates):
                    return candidates[index]
                else:
                    logging.warning(f"LLM returned invalid index: {index + 1}")
                    return None
            except ValueError:
                logging.warning(f"LLM returned invalid response: {response}")
                return None
                
        except Exception as e:
            logging.error(f"Error checking candidates (attempt {attempt + 1}): {str(e)}")
            if attempt == max_retries - 1:
                return None

########## CORE FUNCTION ##########

def _geocode_locations(payload):
    """
    Core logic for geocoding locations.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with geocoded locations
        
    Raises:
        Exception: If geocoding fails
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping geocoding")
        return payload
        
    for item in locations:
        geocode_type = item.get("geocode", {}).get("geocode")
        
        if geocode_type == "search":
            geocode_text = item.get("geocode", {}).get("text")
            original_text = item.get("original_text", "")

            logging.info(f"\nProcessing location (search):")
            logging.info(f"Text to geocode: {geocode_text}")
            logging.info(f"Original context: {original_text}")
            
            results = pelias_geocode_search(geocode_text)
            
        elif geocode_type == "structured":
            address_obj = {
                "address": item.get("geocode", {}).get("address"),
                "locality": item.get("geocode", {}).get("locality"),
                "county": item.get("geocode", {}).get("county"),
                "region": item.get("geocode", {}).get("region"),
                "postalcode": item.get("geocode", {}).get("postalcode")
            }
            original_text = item.get("original_text", "")
            
            results = pelias_geocode_structured(address_obj)
        else:
            continue
            
        if results:
            best_match = check_candidates(
                geocode_text if geocode_type == "search" else json.dumps(address_obj),
                original_text,
                results
            )
            if best_match:
                item["geocode"]["results"] = best_match
            else:
                item["geocode"]["results"] = None
        else:
            item["geocode"]["results"] = None
            logging.warning("No geocoding results found")

    logging.info("Geocoded locations payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="geocode_locations", bind=True, max_retries=3)
def _geocode_locations_task(self, payload):
    """
    Celery task wrapper for geocoding locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with geocoded locations
    """
    try:
        url = payload.get('url')
        
        try:
            return _geocode_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Geocoding failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for geocoding: {str(e)}")
        post_slack_log_message('Error geocoding locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in geocoding: {err}")
        post_slack_log_message('Error geocoding locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload