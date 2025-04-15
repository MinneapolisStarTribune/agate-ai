import logging, traceback, json, os
from utils.llm import get_json_openai
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## HELPER FUNCTIONS ##########

def _classify_locations(payload):
    """
    Core logic for classifying the relevance of locations to the story.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing story text, metadata, and locations
        
    Returns:
        dict: Updated payload with classified locations
        
    Raises:
        Exception: If location classification fails
    """
    story_type = payload.get('story_type', {}).get('category')
    text = payload.get('text')
    url = payload.get('url')
    
    if not text:
        logging.info("No text provided, skipping location classification")
        return payload
        
    # Get the base prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/classify.txt'), 'r') as f:
            base_prompt = f.read()
    except FileNotFoundError:
        raise Exception("Base location prompt not found")
    
    # Get the output prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/_output.txt'), 'r') as f:
            output_prompt = f.read()
    except FileNotFoundError:
        raise Exception("Output location prompt not found")
    
    # Get story type
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/types/_%s.txt' % story_type), 'r') as f:
            story_type_prompt = f.read()
    except FileNotFoundError:
        story_type_prompt = ''
    
    # Combine the prompts
    prompt = f"{base_prompt}"
    
    if story_type_prompt != '':
        prompt += f"\n\n## Special relevance rules for this article"
        prompt += f"\n\n{story_type_prompt}"
        
    prompt += f"\n\n{output_prompt}"
        
    # Clean text and construct user prompt
    cleaned_text = text.replace('\n', ' ')
    user_prompt = f"Here is the article text:\n\n{cleaned_text}\n\nHere are the locations to classify:\n\n{payload.get('locations')}"
                    
    # Pass to LLM for location extraction
    locations = get_json_openai(prompt, user_prompt, force_object=True)
    logging.info(f"Classified location relevance: {locations}")
    
    # Add locations to payload
    payload['locations'] = locations.get('locations')
    payload['url'] = url
    
    # Preserve output_filename
    payload['output_filename'] = payload.get('output_filename')
    logging.info("Classified location relevance payload: %s" % json.dumps(payload, indent=2))
    return payload

########## TASKS ##########

@celery.task(name="classify_locations", bind=True, max_retries=3)
def _classify_locations_task(self, payload):
    """
    Celery task wrapper for location classification.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing story text, metadata, and locations
        
    Returns:
        dict: Updated payload with classified locations
    """
    try:
        url = payload.get('url')
        
        try:
            return _classify_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location classification failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location classification: {str(e)}")
        post_slack_log_message('Error classifying location relevance %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location classification: {err}")
        post_slack_log_message('Error classifying location relevance %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload