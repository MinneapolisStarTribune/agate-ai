import os, logging, json, traceback
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message
from conf.settings import AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME, AZURE_STORAGE_ACCOUNT_NAME
import uuid
from neo4j import GraphDatabase
from conf.settings import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE

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

# -------------------- Neo4j Integration --------------------
def get_neo4j_driver():
    """
    Lazily initialize Neo4j driver. Returns None if not configured.
    """
    try:
        if not NEO4J_URI or not NEO4J_USER or not NEO4J_PASSWORD:
            logging.info("Neo4j not configured, skipping graph write.")
            return None
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception as e:
        logging.error(f"Error initializing Neo4j driver: {e}")
        return None

def _create_article_node(tx, uuid, fk_id, headline, url, author, pub_date, story_type):
    tx.run(
        "MERGE (a:Article {uuid: $uuid})"
        " SET a.fk_id = $fk_id, a.headline = $headline, a.url = $url,"
        " a.author = $author, a.pub_date = $pub_date, a.story_type = $story_type",
        {"uuid": uuid, "fk_id": fk_id, "headline": headline, "url": url,
         "author": author, "pub_date": pub_date, "story_type": story_type}
    )

def _create_location_node(tx, uuid, name, original_text, loc_type, importance, description, latitude, longitude):
    tx.run(
        "MERGE (l:Location {uuid: $uuid})"
        " SET l.name = $name, l.original_text = $original_text, l.type = $loc_type,"
        " l.importance = $importance, l.description = $description,"
        " l.latitude = $latitude, l.longitude = $longitude",
        {"uuid": uuid, "name": name, "original_text": original_text,
         "loc_type": loc_type, "importance": importance, "description": description,
         "latitude": latitude, "longitude": longitude}
    )

def _create_person_node(tx, uuid, name, wikidata_id, wikidata_label):
    tx.run(
        "MERGE (p:Person {uuid: $uuid})"
        " SET p.name = $name, p.wikidata_id = $wikidata_id, p.wikidata_label = $wikidata_label",
        {"uuid": uuid, "name": name,
         "wikidata_id": wikidata_id, "wikidata_label": wikidata_label}
    )

def _create_mention_rel(tx, from_uuid, to_uuid, rel_type="LOCATION"):
    # rel_type unused: always MENTIONED_IN
    tx.run(
        "MATCH (src {uuid: $from_uuid}), (dst {uuid: $to_uuid})"
        " MERGE (src)-[:MENTIONED_IN]->(dst)",
        {"from_uuid": from_uuid, "to_uuid": to_uuid}
    )

def _create_person_mention_rel(tx, person_uuid, article_uuid):
    tx.run(
        "MATCH (p:Person {uuid: $person_uuid}), (a:Article {uuid: $article_uuid})"
        " MERGE (p)-[:MENTIONED_IN]->(a)",
        {"person_uuid": person_uuid, "article_uuid": article_uuid}
    )

@celery.task(name="save_to_neo4j", bind=True, max_retries=3)
def _save_to_neo4j(self, payload):
    """
    Saves the payload into Neo4j as Article, Location, and Person nodes,
    with MENTIONED_IN relationships. Skips if Neo4j is not configured.
    """
    try:
        logging.info("Saving payload to Neo4j")
        driver = get_neo4j_driver()
        if not driver:
            logging.info("Neo4j driver unavailable, skipping save_to_neo4j.")
            return payload

        # Generate identifiers
        article_url = payload.get('url', '')
        article_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, article_url))
        fk_id = payload.get('output_filename') or ''
        headline = payload.get('headline', '')
        author = payload.get('author', '')
        pub_date = payload.get('pub_date', '')
        story_type = payload.get('story_type', '')

        with driver.session(database=NEO4J_DATABASE) as session:
            # Create or update Article node
            session.write_transaction(
                _create_article_node,
                article_uuid, fk_id, headline, article_url,
                author, pub_date, story_type
            )
            # Create Location nodes and relationships
            for place in payload.get('places', []):
                loc_name = place.get('location', '')
                place_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, loc_name))
                original_text = place.get('original_text', '')
                loc_type = place.get('type', '')
                importance = place.get('importance', '')
                description = place.get('description', '')
                # Extract coordinates
                coords = []
                geores = place.get('geocode', {}).get('results', {})
                geometry = geores.get('geometry', {}) or {}
                coords = geometry.get('coordinates', []) or []
                longitude = coords[0] if len(coords) > 0 else None
                latitude = coords[1] if len(coords) > 1 else None
                session.write_transaction(
                    _create_location_node,
                    place_uuid, loc_name, original_text,
                    loc_type, importance, description,
                    latitude, longitude
                )
                session.write_transaction(
                    _create_mention_rel,
                    place_uuid, article_uuid
                )
            # Create Person nodes and relationships
            for person in payload.get('people', []):
                name = person.get('name', '')
                person_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, name)) if name else None
                if not person_uuid:
                    continue
                wikidata = person.get('wikidata', {}) or {}
                wikidata_id = wikidata.get('id', '')
                wikidata_label = wikidata.get('label', '')
                session.write_transaction(
                    _create_person_node,
                    person_uuid, name, wikidata_id, wikidata_label
                )
                session.write_transaction(
                    _create_person_mention_rel,
                    person_uuid, article_uuid
                )
        return payload
    except Exception as e:
        logging.error(f"Error saving to Neo4j: {e}")
        return payload
        