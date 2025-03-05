import json, logging, os
from dateutil.parser import parse as date_parse
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from googlemaps import Client as GoogleMaps
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from dotenv import load_dotenv
from utils.llm import get_json_openai
from worker.tasks.base import _classify_story
from conf.settings import CELERY_BROKER_URL, CELERY_RESULT_BACKEND,\
    CELERY_QUEUE_NAME, CELERY_BROKER_TRANSPORT_OPTIONS, AZURE_NER_ENDPOINT, AZURE_KEY, GOOGLE_MAPS_API_KEY

logging.basicConfig(level=logging.INFO)

load_dotenv()

########## SETTINGS AND SERVICES ##########

# Queue settings. TODO: CLEAN THIS UP FOR ONLY ONE INIT.
celery = Celery(__name__)
celery.conf.broker_url = CELERY_BROKER_URL
celery.conf.result_backend = CELERY_RESULT_BACKEND
celery.conf.task_default_queue = CELERY_QUEUE_NAME
celery.conf.broker_transport_options = CELERY_BROKER_TRANSPORT_OPTIONS

# Initialize the Azure NER client
AZURE_NER_CLIENT = TextAnalyticsClient(
    endpoint=AZURE_NER_ENDPOINT, 
    credential=AzureKeyCredential(AZURE_KEY)
)

# Initialize Google Maps client
GMAPS_CLIENT = GoogleMaps(key=GOOGLE_MAPS_API_KEY)

# Initialize Azure Blob Storage client
AZURE_BLOB_SERVICE_CLIENT = BlobServiceClient.from_connection_string(
    os.getenv('AZURE_STORAGE_CONNECTION_STRING'))
AZURE_STORAGE_CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME')

########## PRIVATE TASK FUNCTIONS ##########

@celery.task(name="extract_locations", bind=True, max_retries=3)
def _extract_locations(self, payload):
    """
    Extracts locations from a story using LLM.
    Uses base prompt plus story-type-specific prompt if available.
    """
    try:
        story_type = payload.get('story_type', {}).get('category')
        text = payload.get('text')
        
        if not text:
            logging.info("No text provided, skipping location extraction")
            return payload
            
        # Get the base prompt
        try:
            with open('utils/prompts/location_extraction/base.txt', 'r') as f:
                prompt = f.read()
        except FileNotFoundError:
            logging.error("Base location prompt not found")
            return payload
            
        # Try to get story-type-specific prompt
        try:
            type_prompt_path = f'utils/prompts/location_extraction/_{story_type}.txt'
            with open(type_prompt_path, 'r') as f:
                prompt += "\n\n" + f.read()
        except FileNotFoundError:
            # If no specific prompt exists, use default
            prompt += "\n\nHere is the text of the article:"
            
        try:
            # Clean text and construct user prompt
            cleaned_text = text.replace('\n', ' ')
            user_prompt = f"{cleaned_text}"
            
            # Pass to LLM for location extraction
            locations = get_json_openai(prompt, user_prompt, force_object=True)
            logging.info(f"Extracted locations: {locations}")
            
            # Add locations to payload
            payload['locations'] = locations.get('locations')
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location extraction failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location extraction: {str(e)}")
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location extraction: {err}")
        payload['locations'] = None
        return payload


@celery.task(name="coref_dedupe", bind=True, max_retries=3)
def _coref_dedupe(self, payload):
    """
    Cleans and resolves coreferences in the locations.
    """
    try:
        # Get locations from payload, handling both formats
        locations = payload.get('locations', [])
        if isinstance(locations, dict):
            locations = locations.get('locations', [])
        
        if not locations:
            logging.info("No locations provided, skipping coreference resolution")
            payload['locations'] = []
            return payload
            
        # Get the coref prompt
        try:
            with open('utils/prompts/coref.txt', 'r') as f:
                coref_prompt = f.read()
        except FileNotFoundError:
            logging.info("No coreference prompt found")
            payload['locations'] = locations
            return payload
            
        try:
            # Format locations for the prompt - wrap in object for consistency
            formatted_locations = {
                "locations": locations
            }
            
            user_prompt = f"""Here are the locations found in the article:
            {json.dumps(formatted_locations, indent=2)}"""
            
            # Pass to LLM for coreference resolution
            cleaned_locations = get_json_openai(coref_prompt, user_prompt, force_object=True)
            
            # Extract locations array from response
            if isinstance(cleaned_locations, dict):
                cleaned_locations = cleaned_locations.get('locations', locations)
            
            # Update payload with cleaned locations
            payload['locations'] = cleaned_locations
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Coreference resolution failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for coreference resolution: {str(e)}")
        # On max retries, keep original locations
        payload['locations'] = locations
        return payload


@celery.task(name="geocode", bind=True, max_retries=3)
def _geocode(self, payload):
    """
    Geocodes the locations using Google Maps API.
    """
    try:
        locations = payload.get('locations', [])
        if not locations:
            logging.info("No locations to geocode")
            return payload
            
        geocoded_locations = []
        for location in locations:
            try:
                # Get geocoding result
                result = GMAPS_CLIENT.geocode(location['location'])
                
                if result:
                    # Get the first (most relevant) result
                    first_result = result[0]
                    
                    # Add geocoding data to location object
                    location.update({
                        'formatted_address': first_result['formatted_address'],
                        'lat': first_result['geometry']['location']['lat'],
                        'lng': first_result['geometry']['location']['lng'],
                        'place_id': first_result['place_id'],
                        'types': first_result['types']
                    })
                
                geocoded_locations.append(location)
                
            except Exception as e:
                logging.error(f"Error geocoding location {location}: {str(e)}")
                geocoded_locations.append(location)  # Keep original if geocoding fails
                
        # Update payload with geocoded locations
        payload['locations'] = geocoded_locations
        return payload
        
    except Exception as e:
        backoff = 2 ** self.request.retries
        logging.error(f"Geocoding failed, retrying in {backoff} seconds. Error: {str(e)}")
        raise self.retry(exc=e, countdown=backoff)


@celery.task(name="cross_check", bind=True, max_retries=3)
def _cross_check(self, payload):
    """
    Cross-checks the locations against the article text.
    """
    try:
        locations = payload.get('locations', [])
        text = payload.get('text', '')
        
        if not locations:
            logging.info("No locations provided, skipping cross-check")
            return payload
            
        # Get the cross-check prompt
        try:
            with open('utils/prompts/cross_check.txt', 'r') as f:
                cross_check_prompt = f.read()
        except FileNotFoundError:
            logging.info("No cross-check prompt found")
            return payload
            
        try:
            # Format locations for the prompt
            formatted_locations = json.dumps(locations, indent=2)
            
            user_prompt = f"""Here are the extracted locations:
            {formatted_locations}
            
            Here is the article text:
            {text}"""
            
            # Pass to LLM for cross-checking
            cross_check_results = get_json_openai(cross_check_prompt, user_prompt, force_object=True)
            
            # Only include detailed results if there are notes
            if cross_check_results.get('check') == 'review':
                payload['cross_check'] = cross_check_results
            else:
                payload['cross_check'] = {"check": "ok"}
                
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Cross-check failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for cross-check: {str(e)}")
        return payload
        
    except Exception as err:
        logging.error(f"Error in cross-check: {err}")
        return payload


@celery.task(name="save_to_azure", bind=True, max_retries=3)
def _save_to_azure(self, payload):
    """
    Saves the payload to Azure Blob Storage.
    """
    try:
        logging.info('Saving to Azure:')
        logging.info(json.dumps(payload, indent=2))
        
        # Get task ID from the request
        task_id = self.request.id
        
        try:
            # Get container client
            container_client = AZURE_BLOB_SERVICE_CLIENT.get_container_client(
                AZURE_STORAGE_CONTAINER_NAME)
            
            # Create blob name using task ID
            blob_name = f"{task_id}.json"
            
            # Convert payload to JSON string
            json_data = json.dumps(payload, indent=2)
            
            # Upload to blob storage
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(json_data, overwrite=True)
            
            logging.info(f"Successfully saved payload to blob: {blob_name}")
            return payload
            
        except Exception as e:
            # Calculate backoff time: 2^retry_count seconds
            backoff = 2 ** self.request.retries
            logging.error(f"Save to Azure failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for Azure save: {str(e)}")
        return payload
        
    except Exception as e:
        logging.error(f"Error in saving to Azure: {e}")
        return payload