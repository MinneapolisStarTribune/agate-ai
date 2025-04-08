import logging, sys, os, redis, traceback, hashlib
from celery import Celery
from worker.tasks.locations import _classify_story, _extract_locations,\
    _geocode, _context, _consolidate, _save_to_azure, review_locations
from worker.tasks.base import _scrape_article
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

@celery.task(name="editorial_review")
def _editorial_review(payload):
    """
    Performs editorial review on extracted locations to filter out incorrect or irrelevant entries.
    
    Args:
        payload (dict): Contains extracted locations and article data
        
    Returns:
        dict: Updated payload with filtered locations
    """
    try:
        locations = payload.get('locations', [])
        text = payload.get('text', '')
        headline = payload.get('headline', '')
        
        if not locations:
            return payload
            
        # Apply editorial review and capture full results
        filtered_locations, review_results = review_locations(locations, text, headline)
        
        # Update payload with filtered locations
        payload['locations'] = filtered_locations
        
        # Build removed items array with location info and removal rationale
        removed_items = []
        for location in locations:
            location_str = location.get("location", "")
            # Find if this location was removed
            removal_info = next((d for d in review_results.get("decisions", []) 
                               if d.get("location") == location_str and d.get("decision") == "REMOVE"), None)
            
            if removal_info:
                removed_items.append({
                    "location": location_str,
                    "original_text": location.get("original_text", ""),
                    "type": location.get("type", ""),
                    "importance": location.get("importance", ""),
                    "nature": location.get("nature", ""),
                    "rationale": removal_info.get("reason", "Failed editorial review")
                })
        
        # Add review metadata including removed items
        payload['review'] = {
            "original_count": len(locations),
            "filtered_count": len(filtered_locations),
            "removed_count": len(locations) - len(filtered_locations),
            "removed_items": removed_items
        }
        
        return payload
        
    except Exception as e:
        logging.error(f"Error in editorial review: {str(e)}")
        logging.error(traceback.format_exc())
        return payload  # Return original payload if review fails

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
            _scrape_article.si(url, output_filename) | # Pass filename through chain
            _classify_story.s() |
            _extract_locations.s() |
            _geocode.s() |
            _context.s() |
            _editorial_review.s() |  # Add editorial review step before consolidation
            _consolidate.s() |
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