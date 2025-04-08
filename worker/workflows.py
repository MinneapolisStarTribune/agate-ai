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
    Performs editorial review on extracted locations to:
    1. Filter out incorrect or irrelevant entries
    2. Identify new locations that were missed in previous steps
    
    Args:
        payload (dict): Contains extracted locations and article data
        
    Returns:
        dict: Updated payload with filtered locations and newly identified locations
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
        
        # Process newly identified locations - convert them to the same format as existing locations
        missed_locations = []
        for missed in review_results.get("missed_locations", []):
            try:
                # Format matches our existing location structure
                missed_loc = {
                    "original_text": missed.get("original_text", ""),
                    "location": missed.get("location", ""),
                    "type": missed.get("type", ""),
                    "importance": missed.get("importance", ""),
                    "nature": missed.get("nature", ""),
                    "description": missed.get("description", ""),
                    "source": "editorial_review"  # Mark these as coming from the review step
                }
                missed_locations.append(missed_loc)
                
                # Also add to the main locations list so they'll be processed in later steps
                payload['locations'].append(missed_loc)
            except Exception as e:
                logging.error(f"Error processing missed location: {str(e)}")
        
        # Add review metadata including removed and missed items
        payload['review'] = {
            "original_count": len(locations),
            "filtered_count": len(filtered_locations),
            "removed_count": len(locations) - len(filtered_locations),
            "removed_items": removed_items,
            "missed_count": len(missed_locations),
            "missed_items": missed_locations
        }
        
        return payload
        
    except Exception as e:
        logging.error(f"Error in editorial review: {str(e)}")
        logging.error(traceback.format_exc())
        return payload  # Return original payload if review fails

@celery.task(name="geocode_missed")
def _geocode_missed(payload):
    """
    Geocodes any locations that were discovered during the editorial review step.
    
    Args:
        payload (dict): Contains locations data including newly discovered locations
        
    Returns:
        dict: Updated payload with geocoded missed locations
    """
    try:
        # Skip if no review data or no missed locations
        if not payload.get('review') or not payload.get('review').get('missed_items'):
            return payload
            
        missed_count = payload['review'].get('missed_count', 0)
        if missed_count <= 0:
            return payload
            
        logging.info(f"Geocoding {missed_count} missed locations discovered in editorial review")
        
        # We need to geocode the missed locations we found
        # But since they've already been added to the main locations list,
        # and we need to preserve the existing geocoded locations,
        # we'll create a temporary payload with only the missed locations
        missed_payload = {
            "locations": [loc for loc in payload.get('locations', []) if loc.get('source') == 'editorial_review'],
            "url": payload.get('url'),
            "text": payload.get('text'),
            "headline": payload.get('headline'),
            "output_filename": payload.get('output_filename')
        }
        
        # Pass through the geocoding task
        if missed_payload["locations"]:
            result = _geocode(missed_payload)
            
            # Get the geocoded missed locations
            geocoded_missed = result.get('locations', [])
            
            # Update the missed locations in the main payload
            # Remove the old ungeocoded versions
            payload['locations'] = [loc for loc in payload.get('locations', []) 
                                   if loc.get('source') != 'editorial_review']
            
            # Add the geocoded versions
            payload['locations'].extend(geocoded_missed)
            
            # Update the missed_items in the review with geocoded versions
            payload['review']['missed_items'] = geocoded_missed
            
            logging.info(f"Successfully geocoded {len(geocoded_missed)} missed locations")
        
        return payload
        
    except Exception as e:
        logging.error(f"Error geocoding missed locations: {str(e)}")
        logging.error(traceback.format_exc())
        return payload  # Return original payload if geocoding fails

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
            _editorial_review.s() |  # Editorial review to filter and find missed locations
            _geocode_missed.s() |    # Geocode any newly discovered locations
            _context.s() |           # Add context for newly discovered locations
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