import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

def _finalize_people(payload):
    """
    Finalize people output by filtering out entries without WikiData match.
    """
    people = payload.get('people', [])
    finalized = []
    for entry in people:
        if entry.get('wikidata'):
            finalized.append(entry)
        else:
            logging.info(f"Discarding unmatched person: {entry.get('name')}")
    payload['people'] = finalized
    return payload

@celery.task(name="finalize_people", bind=True, max_retries=3)
def _finalize_people_task(self, payload):
    try:
        url = payload.get('url')
        try:
            return _finalize_people(payload)
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"People finalization failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for people finalization: {str(e)}")
        post_slack_log_message(f'Error finalizing people {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
    except Exception as err:
        logging.error(f"Error in people finalization: {err}")
        post_slack_log_message(f'Error finalizing people {url}', {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload