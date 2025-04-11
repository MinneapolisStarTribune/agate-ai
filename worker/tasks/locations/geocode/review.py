import json
import logging
import traceback
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
import time

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _validate_geocoding(original_text, original_context, geocoded_result, max_retries=3):
    """
    Use LLM to validate a geocoded location result.
    
    Args:
        original_text (str): Original location text
        original_context (str): Original context from the article
        geocoded_result (dict): Geocoding result to validate
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        dict: Validation result containing validated status and rationale
    """
    if not geocoded_result:
        return {
            "validated": False,
            "rationale": "No geocoding result to validate"
        }
        
    llm = ChatOpenAI(model="gpt-4o")
    
    template = """Given an original location string and its geocoded result, determine if the geocoding is accurate.
    Consider:
    1. Does the geocoded location match the intended location from the text?
    2. Is the level of precision appropriate?
    3. Are there any obvious errors in city, state, or other components?

    Return a JSON object with two fields:
    - validated: boolean indicating if the geocoding is valid
    - rationale: brief explanation of your decision

    Original text: {original_text}
    Original context: {original_context}
    
    Geocoded result:
    {formatted_result}

    Return only the JSON with no additional text:"""
    
    # Format the geocoded result
    formatted_result = (
        f"Label: {geocoded_result.get('label', 'N/A')}\n"
        f"City: {geocoded_result.get('boundaries', {}).get('city', {}).get('name', 'N/A')}\n"
        f"County: {geocoded_result.get('boundaries', {}).get('county', {}).get('name', 'N/A')}\n"
        f"State: {geocoded_result.get('boundaries', {}).get('state', {}).get('name', 'N/A')}\n"
        f"Confidence Score: {geocoded_result.get('confidence', {}).get('score', 'N/A')}\n"
        f"Match Type: {geocoded_result.get('confidence', {}).get('match_type', 'N/A')}"
    )
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Validating geocoding (attempt {attempt + 1}/{max_retries})")
            result = chain.invoke({
                "original_text": original_text,
                "original_context": original_context,
                "formatted_result": formatted_result
            })
            
            # Clean the response content
            content = result.content.strip()
            if content.startswith('```') and content.endswith('```'):
                content = content[3:-3].strip()
            if content.startswith('json'):
                content = content[4:].strip()
                
            validation = json.loads(content)
            return validation
                
        except Exception as e:
            logging.error(f"Error validating geocoding (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logging.info("Waiting 3 seconds before retrying...")
                time.sleep(3)
            else:
                logging.error("Max retries exceeded for geocoding validation")
                return {
                    "validated": False,
                    "rationale": f"Validation failed after {max_retries} attempts"
                }

########## CORE FUNCTION ##########

def _validate_locations(payload):
    """
    Core logic for validating geocoded locations using LLM.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with validation results
        
    Raises:
        Exception: If location validation fails
    """
    locations = payload.get('locations', [])
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping validation")
        return payload
        
    for item in locations:
        # Initialize geocode dict if it doesn't exist
        if 'geocode' not in item:
            item['geocode'] = {}
            
        geocode = item['geocode']
        if not geocode.get('results'):
            geocode['validated'] = False
            geocode['rationale'] = "No geocoding results to validate"
            continue
            
        validation = _validate_geocoding(
            original_text=item.get('original_text', ''),
            original_context=item.get('location', ''),
            geocoded_result=geocode.get('results', {})
        )
        
        geocode['validated'] = validation.get('validated', False)
        geocode['rationale'] = validation.get('rationale', '')

    logging.info("Validated locations payload: %s" % json.dumps(payload, indent=2))
    return payload

########## TASKS ##########

@celery.task(name="validate_locations", bind=True, max_retries=3)
def validate_locations_task(self, payload):
    """
    Celery task wrapper for location validation.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with validation results
    """
    try:
        url = payload.get('url')
        
        try:
            return _validate_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location validation failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for validation: {str(e)}")
        post_slack_log_message('Error validating locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in validation: {err}")
        post_slack_log_message('Error validating locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload

