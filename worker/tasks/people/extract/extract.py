import logging
import traceback
import json
import os
from utils.llm import get_json_openai
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

def _extract_people(payload):
    """
    Core logic for extracting people from a story using LLM.
    """
    text = payload.get('text')
    url = payload.get('url')

    if not text:
        logging.info("No text provided, skipping people extraction")
        return payload

    base_dir = os.path.dirname(__file__)
    try:
        with open(os.path.join(base_dir, 'prompts/extract.txt'), 'r') as f:
            base_prompt = f.read()
        with open(os.path.join(base_dir, 'prompts/_formatting.txt'), 'r') as f:
            format_prompt = f.read()
        with open(os.path.join(base_dir, 'prompts/_output.txt'), 'r') as f:
            output_prompt = f.read()
    except FileNotFoundError as e:
        logging.error(f"People extraction prompt file not found: {e}")
        raise Exception("People extraction prompt not found")

    prompt = f"{base_prompt}\n\n{format_prompt}\n\n{output_prompt}"
    cleaned_text = text.replace('\n', ' ')
    user_prompt = f"Here is the article text:\n\n{cleaned_text}"

    people = get_json_openai(prompt, user_prompt, force_object=True)
    logging.info(f"Extracted people: {people}")

    payload['people'] = people.get('people')
    payload['url'] = url
    payload['output_filename'] = payload.get('output_filename')
    logging.info("Extracted people payload: %s" % json.dumps(payload, indent=2))
    return payload

@celery.task(name="extract_people", bind=True, max_retries=3)
def _extract_people_task(self, payload):
    try:
        url = payload.get('url')
        try:
            return _extract_people(payload)
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"People extraction failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for people extraction: {str(e)}")
        post_slack_log_message(f'Error extracting people {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['people'] = None
        return payload
    except Exception as err:
        logging.error(f"Error in people extraction: {err}")
        post_slack_log_message(f'Error extracting people {url}', {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['people'] = None
        return payload