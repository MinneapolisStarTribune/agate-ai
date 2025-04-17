import requests, json, logging, traceback, os
from conf.settings import GEOCODE_EARTH_API_KEY, GEOCODIO_API_KEY
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
from utils.geocode import pelias_geocode_search, pelias_geocode_structured, geocodio_geocode

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

## Checking and validation

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
        
    # Get the validation prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/check-candidates.txt'), 'r') as f:
            base_prompt = f.read()
            
        # Combine base prompt with template structure
        template = f"""{base_prompt}

Respond ONLY with the number or "none", no other text.

Text to geocode: {{original_text}}
Original context: {{original_context}}

Candidates:
{{formatted_candidates}}

Your response (just the number or "none"):"""
            
    except FileNotFoundError:
        logging.error("Check candidates prompt not found")
        raise
        
    llm = ChatOpenAI(model="gpt-4.1")
    
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
        # Initialize geocode dict if it doesn't exist
        if 'geocode' not in item:
            item['geocode'] = {}
            
        geocode_type = item["geocode"].get("geocode")            
        
        if geocode_type == "search":
            geocode_text = item["geocode"].get("text")
            original_text = item.get("original_text", "")

            logging.info(f"\nProcessing location (search):")
            logging.info(f"Text to geocode: {geocode_text}")
            logging.info(f"Original context: {original_text}")
            
            results = pelias_geocode_search(geocode_text)
            
        elif geocode_type == "structured":
            address_obj = {
                "address": item["geocode"].get("address"),
                "locality": item["geocode"].get("locality"),
                "county": item["geocode"].get("county"),
                "region": item["geocode"].get("region"),
                "postalcode": item["geocode"].get("postalcode")
            }
            original_text = item.get("original_text", "")
            
            results = pelias_geocode_structured(address_obj)

        elif geocode_type == "geocodio":
            geocode_text = item["geocode"].get("text")
            original_text = item.get("original_text", "")

            results = geocodio_geocode(geocode_text)
        else:
            item["geocode"]["results"] = {}
            continue

        if results:
            best_match = check_candidates(
                geocode_text if geocode_type in ["search", "geocodio"] else json.dumps(address_obj),
                original_text,
                results
            )
            if best_match:
                item["geocode"]["results"] = best_match
            else:
                item["geocode"]["results"] = {}

            # Further bespoke cleanup to results. For example, no neighborhoods for street_roads
            if item["type"] == "street_road":
                item["geocode"]["results"]["boundaries"]["neighborhood"] = {
                    "id": None,
                    "name": None
                }
        else:
            logging.info('no results')
            item["geocode"]["results"] = {}
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