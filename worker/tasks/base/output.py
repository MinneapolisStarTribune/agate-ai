import os, logging, json, traceback
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
from conf.settings import AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME, AZURE_STORAGE_ACCOUNT_NAME

celery = Celery(__name__)

def get_azure_client():
    """
    Lazily initialize Azure Blob Storage client.
    Returns None if credentials are not properly configured.
    """
    try:
        if not AZURE_STORAGE_CONNECTION_STRING:
            logging.info("Azure connection string not configured")
            return None
            
        return BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    except ValueError as e:
        logging.warning(f"Invalid Azure connection string: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Error initializing Azure client: {str(e)}")
        return None

########### TASKS ##########

@celery.task(name="save_to_azure", bind=True, max_retries=3)
def _save_to_azure(self, payload):
    """
    Saves the payload to Azure Blob Storage if credentials are configured.
    If Azure credentials are not set or invalid, logs the output locally.
    """
    try:
        logging.info('Saving output:')
        logging.info(json.dumps(payload, indent=2))

        # Get Azure client
        azure_client = get_azure_client()

        # Check if Azure is properly configured
        if not azure_client or not AZURE_STORAGE_CONTAINER_NAME or not AZURE_STORAGE_ACCOUNT_NAME:
            logging.info("Azure storage not properly configured. Skipping blob storage upload.")
            logging.info("Final payload:")
            logging.info(json.dumps(payload, indent=2))
            return

        # Get task ID and URL from the request
        task_id = self.request.id
        url = payload.get('url')
        
        try:
            # Get container client
            container_client = azure_client.get_container_client(
                AZURE_STORAGE_CONTAINER_NAME)
            
            # Get output filename from payload
            blob_name = payload.get('output_filename')
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