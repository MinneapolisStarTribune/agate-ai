import json, logging, os, traceback
from dateutil.parser import parse as date_parse
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from googlemaps import Client as GoogleMaps
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from dotenv import load_dotenv
from utils.llm import get_json_openai
from utils.slack import post_slack_log_message
from worker.tasks.base import _classify_story
from conf.settings import CELERY_BROKER_URL, CELERY_RESULT_BACKEND,\
    CELERY_QUEUE_NAME, CELERY_BROKER_TRANSPORT_OPTIONS, AZURE_NER_ENDPOINT, AZURE_KEY, GOOGLE_MAPS_API_KEY,\
    AZURE_STORAGE_CONTAINER_NAME, AZURE_STORAGE_ACCOUNT_NAME, CONTEXT_API_URL
import requests

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
        url = payload.get('url')
        
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
            payload['url'] = url
            # Preserve output_filename
            payload['output_filename'] = payload.get('output_filename')
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location extraction failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location extraction: {str(e)}")
        post_slack_log_message('Error extracting locations %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location extraction: {err}")
        post_slack_log_message('Error extracting locations %s' % url, {
            'error_message':  str(err.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
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
        url = payload.get('url')
        
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
            # Preserve output_filename
            payload['output_filename'] = payload.get('output_filename')
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Coreference resolution failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for coreference resolution: {str(e)}")
        post_slack_log_message('Error resolving locations %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
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
        url = payload.get('url')
        
        if not locations:
            logging.info("No locations to geocode")
            return payload
            
        # Define valid location types for geocoding
        geocodable_types = ['place', 'address_intersection', 'neighborhood', 'city', 'street_road', 'county']
        
        geocoded_locations = []
        for location in locations:
            location['geography'] = {}

            # Skip locations that don't have a valid type
            location_type = location.get('type', '').lower()
            if location_type not in geocodable_types:
                logging.info(f"Skipping geocoding for location type: {location_type}")
                geocoded_locations.append(location)
                continue
            
            try:
                # Get geocoding result
                result = GMAPS_CLIENT.geocode(location['location'])
                
                if result:
                    # Get the first (most relevant) result
                    first_result = result[0]
                    
                    # Add geocoding data to location object
                    location['geography'] = {
                        'formatted_address': first_result['formatted_address'],
                        'lat': first_result['geometry']['location']['lat'],
                        'lng': first_result['geometry']['location']['lng'],
                        'google_place_id': first_result['place_id'],
                        'google_precision': first_result['geometry']['location_type'],
                        'google_types': first_result['types']
                    }
                
                geocoded_locations.append(location)
                
            except Exception as e:
                logging.error(f"Error geocoding location {location}: {str(e)}")
                geocoded_locations.append(location)  # Keep original if geocoding fails
                
        # Update payload with geocoded locations
        payload['locations'] = geocoded_locations
        # Preserve output_filename
        payload['output_filename'] = payload.get('output_filename')
        return payload
        
    except MaxRetriesExceededError as max_retries_err:
        logging.error(f"Max retries exceeded for geocoding: {str(max_retries_err)}")
        post_slack_log_message('Error geocoding locations %s (max retries exceeded)' % url, {
            'error_message': str(max_retries_err),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload

    except Exception as e:
        backoff = 2 ** self.request.retries
        logging.error(f"Geocoding failed, retrying in {backoff} seconds. Error: {str(e)}")
        raise self.retry(exc=e, countdown=backoff)


@celery.task(name="context", bind=True, max_retries=3)
def _context(self, payload):
    """
    Canonicalize and contextualize locations.
    """
    try:
        logging.info("Contextualizing locations")
        locations = payload.get('locations', [])
        url = payload.get('url')

        if not locations:
            logging.info("No locations to contextualize")
            return payload

        contextualized_locations = []
        for location in locations:
            logging.info("Contextualizing location: %s" % location)
            try:
                # Skip if we don't have coordinates
                if not location.get('geography', {}).get('lat') or not location.get('geography', {}).get('lng'):
                    location_type = location.get('type', '').lower()
                    location_name = location.get('location', '')
                    
                    if location_type == 'state':
                        logging.info(f"Looking up state context for: {location_name}")
                        response = requests.get(
                            CONTEXT_API_URL + "locations/state",
                            params={'q': location_name}
                        )
                        response.raise_for_status()
                        logging.info("Response: %s" % response.json())
                        
                        context_data = response.json()
                        location['geography']['boundaries'] = context_data
                        contextualized_locations.append(location)
                        continue

                    elif location_type == 'county':
                        logging.info(f"Looking up county context for: {location_name}")
                        response = requests.get(
                            CONTEXT_API_URL + "locations/county",
                            params={'q': location_name}
                        )
                        response.raise_for_status()
                        logging.info("Response: %s" % response.json())
                        
                        context_data = response.json()
                        location['geography']['boundaries'] = context_data
                        contextualized_locations.append(location)
                        continue
                        
                    elif location_type == 'city':
                        logging.info(f"Looking up city context for: {location_name}")
                        response = requests.get(
                            CONTEXT_API_URL + "locations/city",
                            params={'q': location_name}
                        )
                        response.raise_for_status()
                        logging.info("Response: %s" % response.json())
                        
                        context_data = response.json()
                        location['geography']['boundaries'] = context_data
                        contextualized_locations.append(location)
                        continue
                        
                    else:
                        logging.info(f"Skipping context for location without coordinates: {location_name}")
                        contextualized_locations.append(location)
                        continue

                # Make request to context API for locations with coordinates
                logging.info("Requesting context for location ...")
                params = {
                    'lat': location['geography']['lat'],
                    'lng': location['geography']['lng']
                }
                
                # Exclude neighorhoods if precision isn't ROOFTOP
                if location.get('geography', {}).get('google_precision') != 'ROOFTOP':
                    params['include'] = 'region,state,county,city'
                    logging.info("Adding region includes due to non-ROOFTOP precision")
                
                response = requests.get(
                    CONTEXT_API_URL + "locations/boundary",
                    params=params
                )
                response.raise_for_status()
                logging.info("Response: %s" % response.json())

                # Add context data to location
                context_data = response.json()
                location['geography']['boundaries'] = context_data
                contextualized_locations.append(location)

            except Exception as e:
                logging.error(f"Error getting context for location {location}: {str(e)}")
                contextualized_locations.append(location)  # Keep original if context fails

        # Update payload with contextualized locations
        payload['locations'] = contextualized_locations
        # Preserve output_filename
        payload['output_filename'] = payload.get('output_filename')
        return payload

    except MaxRetriesExceededError as max_retries_err:
        logging.error(f"Max retries exceeded for context: {str(max_retries_err)}")
        post_slack_log_message('Error getting context for locations %s (max retries exceeded)' % url, {
            'error_message': str(max_retries_err),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return payload

    except Exception as e:
        backoff = 2 ** self.request.retries
        logging.error(f"Context failed, retrying in {backoff} seconds. Error: {str(e)}")
        raise self.retry(exc=e, countdown=backoff)


@celery.task(name="cross_check", bind=True, max_retries=3)
def _cross_check(self, payload):
    """
    Cross-checks the locations against the article text.
    """
    try:
        locations = payload.get('locations', [])
        text = payload.get('text', '')
        url = payload.get('url')

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
                
            # Preserve output_filename
            payload['output_filename'] = payload.get('output_filename')
            return payload
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Cross-check failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for cross-check: {str(e)}")
        post_slack_log_message('Error cross-checking locations %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as err:
        logging.error(f"Error in cross-check: {err}")
        post_slack_log_message('Error cross-checking locations %s' % url, {
            'error_message':  str(err.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload


@celery.task(name="save_to_azure", bind=True, max_retries=3)
def _save_to_azure(self, payload):
    """
    Saves the payload to Azure Blob Storage.
    """
    try:
        logging.info('Saving to Azure:')
        logging.info(json.dumps(payload, indent=2))
        
        # Get task ID and URL from the request
        task_id = self.request.id
        url = payload.get('url')
        
        try:
            # Get container client
            container_client = AZURE_BLOB_SERVICE_CLIENT.get_container_client(
                AZURE_STORAGE_CONTAINER_NAME)
            
            # Get output filename from payload
            blob_name = payload.get('output_filename')
            logging.info(f"Payload contents: {json.dumps(payload, indent=2)}")
            logging.info(f"Container name: {AZURE_STORAGE_CONTAINER_NAME}, Blob name: {blob_name}")
            
            if not blob_name:
                raise ValueError("Missing output_filename in payload")
                          
            # Convert payload to JSON string
            json_data = json.dumps(payload, indent=2)
            
            # Upload to blob storage
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(
                json_data, 
                overwrite=True,
                content_type='application/json'
            )
            
            # Construct the blob URL
            storage_account = AZURE_STORAGE_ACCOUNT_NAME
            container_name = AZURE_STORAGE_CONTAINER_NAME
            blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_name}"
            
            logging.info(f"Successfully saved payload to blob: {blob_name}")
            post_slack_log_message(f"Successfully processed locations!", {
                'agate_update_msg': "View the payload below:",
                'storage_url': blob_url,
                'headline': payload.get('headline', ''),
                'article_url': payload.get('url', '')
            }, 'create_success')

            return payload
            
        except Exception as e:
            # Calculate backoff time: 2^retry_count seconds
            backoff = 2 ** self.request.retries
            logging.error(f"Save to Azure failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for Azure save: {str(e)}")
        post_slack_log_message('Error saving to Azure %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload
        
    except Exception as e:
        logging.error(f"Error in saving to Azure: {e}")
        post_slack_log_message('Error saving to Azure %s' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return payload