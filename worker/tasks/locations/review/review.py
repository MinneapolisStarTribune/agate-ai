import json
import logging
import traceback
import os
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

########## CORE FUNCTION ##########

def _review_locations(payload):
    """
    Core logic for reviewing locations using LLM.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Updated payload with reviewed locations
    """
    locations = payload.get('locations', [])
    text = payload.get('text')
    url = payload.get('url')
    
    if not locations:
        logging.info("No locations provided, skipping review")
        return payload
        
    logging.info(f"Reviewing {len(locations)} locations for {url}")
    
    # Get the review prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/review.txt'), 'r') as f:
            base_prompt = f.read()
    except FileNotFoundError:
        logging.error("Review prompt not found")
        raise Exception("Review prompt not found")
        
    # Set up LLM chain
    llm = ChatOpenAI(model="gpt-4.1")
    
    # Create the template by combining base prompt with additional context
    template = base_prompt + """

Here is the article text:
{text}

Here are the locations to review:
{locations}

Return only the JSON with no additional text."""

    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    # Process with LLM
    try:
        result = chain.invoke({
            "text": text,
            "locations": json.dumps(locations, indent=2)
        })
        
        # Clean the response content
        content = result.content.strip()
        if content.startswith('```') and content.endswith('```'):
            content = content[3:-3].strip()
        if content.startswith('json'):
            content = content[4:].strip()
            
        reviewed = json.loads(content)
        logging.info(f"Review completed for {len(reviewed)} locations")
        
        # Update the payload with reviewed locations
        payload['locations'] = reviewed
        
    except Exception as e:
        logging.error(f"Error in LLM review: {str(e)}")
        # If LLM review fails, preserve the original locations
        logging.warning("Preserving original locations due to review failure")
        raise
    
    logging.info("Review payload: %s" % json.dumps(payload, indent=2))    
    return payload

########## TASKS ##########

@celery.task(name="review_locations", bind=True, max_retries=3)
def _review_locations_task(self, payload):
    """
    Celery task wrapper for reviewing locations.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing locations and metadata
        
    Returns:
        dict: Payload with review results
    """
    try:
        url = payload.get('url')
        
        try:
            return _review_locations(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location review failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for review: {str(e)}")
        post_slack_log_message('Error reviewing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in review: {err}")
        post_slack_log_message('Error reviewing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
