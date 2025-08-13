import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.wikidata import lookup_entity
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

def _canonicalize_people(payload):
    """
    Enrich each person with WikiData entity info if available.
    """
    people = payload.get('people', [])
    canonicalized = []
    for name in people:
        try:
            entity = lookup_entity(name)
            canonicalized.append({
                "name": name,
                "wikidata": entity
            })
        except Exception as e:
            logging.error(f"Error canonicalizing '{name}': {e}")
            canonicalized.append({
                "name": name,
                "wikidata": None
            })
    payload['people'] = canonicalized
    logging.info(f"Canonicalized people payload: {canonicalized}")
    return payload

@celery.task(name="canonicalize_people", bind=True, max_retries=3)
def _canonicalize_people_task(self, payload):
    try:
        url = payload.get('url')
        try:
            return _canonicalize_people(payload)
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"People canonicalization failed, retrying in {backoff} seconds. Error: {e}")
            raise self.retry(exc=e, countdown=backoff)
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for people canonicalization: {e}")
        post_slack_log_message(f'Error canonicalizing people {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
    except Exception as err:
        logging.error(f"Error in people canonicalization: {err}")
        post_slack_log_message(f'Error canonicalizing people {url}', {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload