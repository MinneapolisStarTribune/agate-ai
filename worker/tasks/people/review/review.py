import logging
import traceback
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

# Configure logging
logging.basicConfig(level=logging.INFO)

celery = Celery(__name__)

def _review_people(payload):
    """
    Core logic for reviewing canonicalized people.
    Currently a no-op stub.
    """
    logging.info("People review (stub): passing through payload")
    return payload

@celery.task(name="review_people_canonical", bind=True, max_retries=3)
def _review_people_task(self, payload):
    try:
        url = payload.get('url')
        try:
            return _review_people(payload)
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"People canonical review failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for people canonical review: {str(e)}")
        post_slack_log_message(f'Error reviewing people {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload
    except Exception as err:
        logging.error(f"Error in people canonical review: {err}")
        post_slack_log_message(f'Error reviewing people {url}', {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload