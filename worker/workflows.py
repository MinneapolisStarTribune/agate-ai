import logging, sys, os, redis, traceback, hashlib
from celery import Celery
from worker.tasks.base.scrape import _scrape_article_task
from worker.tasks.base.classify import _classify_article_task
from worker.tasks.locations.extract import _location_extraction_chain
from worker.tasks.locations.filter import _filter_chain
from worker.tasks.locations.geocode import _geocoding_chain
from worker.tasks.locations.localize import _localization_chain
from worker.tasks.locations.review import _review_chain
from worker.tasks.base.output import _save_to_azure
from utils.slack import post_slack_log_message

########## CELERY INITIALIZATION ##########

# Initialize Celery
celery = Celery('worker')

# Get Redis connection details from environment
REDIS_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')

# Configure Celery
celery.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    enable_utc=True,
)

# Test Redis connection
try:
    # Create Redis client from URL
    redis_client = redis.from_url(REDIS_URL)
    
    # Test connection with ping
    ping_result = redis_client.ping()
    logging.info(f"REDIS CONNECTION TEST: Ping successful: {ping_result}")
    
    logging.info("Celery worker configuration complete and ready to process tasks")
except Exception as e:
    logging.error(f"REDIS CONNECTION ERROR: {str(e)}")
    raise

# Configure logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout
)

########## WORKFLOWS ##########

@celery.task(name="process_locations")
def process_locations(url):
    """
    Process locations from text
    """
    try:
        logging.info(f"Processing locations from url: {url}")
        
        # Generate output filename
        output_filename = f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.json"
        
        # Create a chain that executes once
        workflow = (
            _scrape_article_task.si(url, output_filename) | # Pass filename through chain
            _classify_article_task.s() |
            _location_extraction_chain() |
            _filter_chain() |
            _geocoding_chain() |
            _localization_chain() |
            _review_chain() |
            _save_to_azure.s()
        )
        
        # Execute the workflow
        result = workflow.apply_async()
        
        return {"status": "success", "task_id": result.id}
    except Exception as e:
        logging.error(f"Error processing locations: {str(e)}")
        post_slack_log_message('Error processing locations %s' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return {"status": "error", "error": str(e)}