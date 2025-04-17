import logging, traceback, os, json
from utils.llm import get_json_openai
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## CORE FUNCTION ##########

def _classify_article(payload):
    """
    Core logic for classifying a story into a category.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing story text and metadata
        
    Returns:
        dict: Updated payload with story classification
        
    Raises:
        Exception: If classification fails
    """
    text = payload.get("text", "")
    headline = payload.get("headline", "")
    url = payload.get("url", "")
    
    logging.info(f"Starting article classification for URL: {url}")
    
    # Get the story type prompt
    with open(os.path.join(os.path.dirname(__file__), 'prompts/classify.txt'), 'r') as f:
        type_prompt = f.read()

    # Clean text and construct user prompt
    user_prompt = f"""Here is the headline:
    {headline}"""

    # Pass to LLM for classification
    story_type = get_json_openai(type_prompt, user_prompt, force_object=True)
    logging.info(f"Classification completed - type: {story_type}")
    
    output = {
        "story_type": story_type,
        "text": text,
        "headline": headline,
        "url": url,
        "author": payload.get("author", ""),
        "pub_date": payload.get("pub_date", ""),
        "output_filename": payload.get("output_filename")
    }

    logging.info(f"Classification output: {json.dumps(output, indent=2)}")
    return output

########## TASKS ##########

@celery.task(name="classify_article", bind=True, max_retries=3)
def _classify_article_task(self, payload):
    """
    Celery task wrapper for story classification.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing story text and metadata
        
    Returns:
        dict: Updated payload with story classification
    """
    try:
        url = payload.get("url", "")
        logging.info(f"Starting classification task for URL: {url}")
        
        try:
            return _classify_article(payload)
            
        except Exception as e:
            # Calculate backoff time: 2^retry_count seconds
            backoff = 2 ** self.request.retries
            logging.error(f"Error classifying story, retrying in {backoff} seconds. Error: {str(e)}")
            logging.error(f"Error traceback: {traceback.format_exc()}")
            
            if not self.request.retries:  # Only post to Slack on first error
                post_slack_log_message(f'Error classifying story {url}', {
                    'error_message': str(e.args[0]),
                    'traceback': traceback.format_exc()
                }, 'create_error')
                
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for story classification: {url}")
        post_slack_log_message(f'Error classifying story {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return {"status": "error", "error": f"Max retries exceeded: {url}"}