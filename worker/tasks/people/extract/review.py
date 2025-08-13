import logging
import traceback
import json
import os
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.llm import get_json_openai
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

def _review_people(payload):
    """
    Core logic for reviewing extracted people using LLM.
    """
    text = payload.get('text')
    url = payload.get('url')

    if not text:
        logging.info("No text provided, skipping people review")
        return payload

    base_dir = os.path.dirname(__file__)
    try:
        with open(os.path.join(base_dir, 'prompts/extract-review.txt'), 'r') as f:
            base_prompt = f.read()
        with open(os.path.join(base_dir, 'prompts/_formatting.txt'), 'r') as f:
            format_prompt = f.read()
        with open(os.path.join(base_dir, 'prompts/_output.txt'), 'r') as f:
            output_prompt = f.read()
    except FileNotFoundError as e:
        logging.error(f"People review prompt file not found: {e}")
        raise Exception("People review prompt not found")

    prompt = f"{base_prompt}\n\n{format_prompt}\n\n{output_prompt}"
    cleaned_text = text.replace('\n', ' ')
    people_list = payload.get('people')
    user_prompt = f"Article text:\n\n{cleaned_text}\n\nExtracted people:\n\n{people_list}"

    reviewed = get_json_openai(prompt, user_prompt, force_object=True)
    logging.info(f"Reviewed people: {reviewed}")

    payload['people'] = reviewed.get('people')
    payload['url'] = url
    logging.info("Reviewed people payload: %s" % json.dumps(payload, indent=2))
    return payload

@celery.task(name="review_people", bind=True, max_retries=3)
def review_people_task(self, payload):
    try:
        url = payload.get('url')
        try:
            return _review_people(payload)
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"People review failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for people review: {str(e)}")
        post_slack_log_message(f'Error reviewing people {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
    except Exception as err:
        logging.error(f"Error in people review: {err}")
        post_slack_log_message(f'Error reviewing people {url}', {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload