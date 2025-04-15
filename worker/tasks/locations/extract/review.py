import logging, json, os, traceback
from celery import Celery
from utils.slack import post_slack_log_message
from utils.llm import get_json_openai
from celery.exceptions import MaxRetriesExceededError
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.exceptions import ServiceRequestError, HttpResponseError
from conf.settings import AZURE_NER_ENDPOINT, AZURE_KEY

# Configure logging
logging.basicConfig(level=logging.INFO)

########## CELERY INITIALIZATION ##########

celery = Celery(__name__)

########## AZURE NER INITIALIZATION ##########

# Azure credentials from environment variables
endpoint = AZURE_NER_ENDPOINT
key = AZURE_KEY

# Initialize the Azure client with timeout settings
text_analytics_client = TextAnalyticsClient(
    endpoint=endpoint, 
    credential=AzureKeyCredential(key),
    connection_timeout=5,  # Reduced timeout for faster failure
    read_timeout=10       # Increased for processing multiple chunks
)

########## HELPER FUNCTIONS ##########

def extract_locations(text):
    """
    Extract locations from text using Azure's NER service.
    
    Args:
        text: The text to analyze
        
    Returns:
        List of location entities
    """
    if not AZURE_NER_ENDPOINT or not AZURE_KEY:
        logging.error("Azure NER endpoint or key not found")
        return []
    
    try:
        # Prepare document
        document = {"id": "1", "language": "en", "text": text}
        
        result = text_analytics_client.recognize_entities(documents=[document])[0]
        
        # Filter for only Location entities
        locations = [
            {
                'text': entity.text,
                'confidence': entity.confidence_score,
                'offset': entity.offset
            }
            for entity in result.entities 
            if entity.category == 'Location'
        ]
        
        return locations
            
    except (ServiceRequestError, HttpResponseError, Exception) as e:
        logging.error(f"Error extracting locations: {str(e)}")
        return []

def split_into_chunks(text, words_per_chunk=100):
    """
    Split text into chunks of approximately N words.
    
    Args:
        text: Text to split
        words_per_chunk: Target number of words per chunk
        
    Returns:
        List of text chunks
    """
    words = text.split()
    chunks = []
    
    for i in range(0, len(words), words_per_chunk):
        chunk = ' '.join(words[i:i + words_per_chunk])
        chunks.append(chunk)
    
    return chunks

def process_text_ner(text):
    """
    Process text by splitting into chunks and extracting locations from each.
    
    Args:
        text: The full text to analyze
        
    Returns:
        List of unique location entities
    """
    # Split text into chunks
    chunks = split_into_chunks(text)
    
    all_locations = []
    seen_locations = set()  # Track unique location texts
    
    logging.info(f"Processing {len(chunks)} chunks")
    
    for i, chunk in enumerate(chunks, 1):
        logging.info(f"Processing chunk {i}/{len(chunks)}")
        locations = extract_locations(chunk)
        
        # Add only unique locations
        for loc in locations:
            if loc['text'] not in seen_locations:
                seen_locations.add(loc['text'])
                all_locations.append(loc)
    
    logging.info(f"Found {len(all_locations)} unique locations")
    return [location['text'] for location in all_locations]

def _extract_locations_review(payload):
    """
    Core logic for reviewing extracted locations using LLM and conventional NER.
    This function can be called independently for testing or used by the Celery task.
    
    Args:
        payload (dict): Dictionary containing story text, metadata, and extracted locations
        
    Returns:
        dict: Updated payload with reviewed locations
        
    Raises:
        Exception: If location review fails
    """
    text = payload.get('text')
    url = payload.get('url')
    
    if not text:
        logging.info("No text provided, skipping location review")
        return payload
        
    # Get the base prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/extract-review.txt'), 'r') as f:
            base_prompt = f.read()
    except FileNotFoundError:
        logging.error("Base location prompt not found")
        raise Exception("Base location prompt not found")
    
    # Get the format prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/_formatting.txt'), 'r') as f:
            format_prompt = f.read()
    except FileNotFoundError:
        logging.error("Format location prompt not found")
        raise Exception("Format location prompt not found")
    
    # Get the output prompt
    try:
        with open(os.path.join(os.path.dirname(__file__), 'prompts/_output.txt'), 'r') as f:
            output_prompt = f.read()
    except FileNotFoundError:
        logging.error("Output location prompt not found")
        raise Exception("Output location prompt not found")

    # The list of locations from the LLM
    llm_locations = payload.get('locations', [])

    # The list of locations from the NER
    ner_locations = process_text_ner(text)

    # Combine the prompts
    prompt = f"""{base_prompt}

    New locations should be formatted according to the following rules:

    {format_prompt}\n\n

    The article text is:

    {text}

    The locations extracted from the LLM are:

    {llm_locations}
    """

    if ner_locations:
        prompt += f"\n\nThe locations extracted from the NER service are: {ner_locations}\n\n"

    prompt += f"{output_prompt}"

    prompt += f"\n\nIf you add anything to the list of locations, add an attribute to the location called 'notes' and set it to 'Added by extraction reviewer'"
        
    # Clean text and construct user prompt
    cleaned_text = text.replace('\n', ' ')
    user_prompt = f"{cleaned_text}"
    
    # Pass to LLM for location extraction
    locations = get_json_openai(prompt, user_prompt, force_object=True)
    logging.info(f"Locations after review: {locations}")
    
    # Add locations to payload
    payload['locations'] = locations.get('locations')
    payload['url'] = url
    
    # Preserve output_filename
    payload['output_filename'] = payload.get('output_filename')
    logging.info("Reviewed locations payload: %s" % json.dumps(payload, indent=2))
    return payload

########## TASKS ##########

@celery.task(name="extract_locations_review", bind=True, max_retries=3)
def extract_locations_review_task(self, payload):
    """
    Celery task wrapper for location review.
    Handles retries and error reporting.
    
    Args:
        payload (dict): Dictionary containing story text, metadata, and extracted locations
        
    Returns:
        dict: Updated payload with reviewed locations
    """
    try:
        url = payload.get('url')
        
        try:
            return _extract_locations_review(payload)
            
        except Exception as e:
            backoff = 2 ** self.request.retries
            logging.error(f"Location review failed, retrying in {backoff} seconds. Error: {str(e)}")
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for location review: {str(e)}")
        post_slack_log_message('Error reviewing locations %s (max retries exceeded)' % url, {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload
        
    except Exception as err:
        logging.error(f"Error in location review: {err}")
        post_slack_log_message('Error reviewing locations %s' % url, {
            'error_message': str(err.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        payload['locations'] = None
        return payload