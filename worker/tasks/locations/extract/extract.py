import logging, traceback, json, os
from utils.llm import get_json_openai
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _extract_locations(payload):
    """
    Core logic for extracting locations from a story using LLM.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing story text and metadata
        
    Returns:
        dict: Updated payload with extracted locations
        
    Raises:
        Exception: If location extraction fails
    """
    text = payload.get('text')
    url = payload.get('url')
    
    if not text:
        logging.info("No text provided, skipping location extraction")
        return payload
        
    # Get the base prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/extract.txt'), 'r') as f:
            base_prompt = f.read()
    except FileNotFoundError:
        logging.error("Base location prompt not found")
        raise Exception("Base location prompt not found")
    
    # Get the format prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/_formatting.txt'), 'r') as f:
            format_prompt = f.read()
    except FileNotFoundError:
        logging.error("Format location prompt not found")
        raise Exception("Format location prompt not found")
    
    # Get the output prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/_output.txt'), 'r') as f:
            output_prompt = f.read()
    except FileNotFoundError:
        logging.error("Output location prompt not found")
        raise Exception("Output location prompt not found")
    
    # Combine the prompts
    prompt = f"{base_prompt}\n\n{format_prompt}\n\n{output_prompt}"
        
    # Clean text and construct user prompt
    cleaned_text = text.replace('\n', ' ')
    user_prompt = f"Here is the article text:\n\n{cleaned_text}"
    
    # Pass to LLM for location extraction
    locations = get_json_openai(prompt, user_prompt, force_object=True)
    logging.info(f"Extracted locations: {locations}")
    
    # Add locations to payload
    payload['locations'] = locations.get('locations')
    payload['url'] = url
    
    # Preserve output_filename
    payload['output_filename'] = payload.get('output_filename')
    logging.info("Extracted locations payload: %s" % json.dumps(payload, indent=2))
    return payload

########## TASKS ##########

@celery.task(name="extract_locations", bind=True, max_retries=3)
def _extract_locations_task(self, payload):
    """
    Celery task wrapper for location extraction.
    Handles retries and error reporting.
    """
    try:
        url = payload.get('url')
        
        try:
            return _extract_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location extraction failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location extraction: {str(e)}")
        post_slack_log_message('Error extracting locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location extraction: {err}")
        post_slack_log_message('Error extracting locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload