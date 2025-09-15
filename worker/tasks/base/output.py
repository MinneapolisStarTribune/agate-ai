import os, logging, json, traceback
from celery import Celery
from utils.slack import post_slack_log_message
import uuid
from neo4j import GraphDatabase
from conf.settings import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE

celery = Celery(__name__)

########### TASKS ##########

from .neo4j_client import get_neo4j_driver, write_article_with_entities

@celery.task(name="save_to_neo4j", bind=True, max_retries=3)
def _save_to_neo4j(self, payload):
    """
    Saves the payload into Neo4j as Article, Location, and Person nodes,
    with MENTIONED_IN relationships. Skips if Neo4j is not configured.
    """
    return _save_to_neo4j_impl(self, payload)

@celery.task(name="save_to_azure", bind=True, max_retries=3)
def _save_to_azure(self, payload):
    """
    Alias for save_to_neo4j to handle misnamed task calls.
    """
    logging.warning("save_to_azure task called - redirecting to save_to_neo4j")
    return _save_to_neo4j_impl(self, payload)

def _save_to_neo4j_impl(self, payload):
    """
    Implementation for saving payload to Neo4j.
    """
    try:
        logging.info("Saving payload to Neo4j")
        driver = get_neo4j_driver()
        if not driver:
            logging.info("Neo4j driver unavailable, skipping save_to_neo4j.")
            return payload

        # Prepare article data
        article_url = payload.get("url", "")
        story_type = payload.get("story_type", {})
        
        article_data = {
            "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, article_url)),
            "fk_id": payload.get("output_filename") or "",
            "headline": payload.get("headline", ""),
            "url": article_url,
            "author": payload.get("author", ""),
            "pub_date": payload.get("pub_date", ""),
            "story_type_category": story_type.get("category", "") if isinstance(story_type, dict) else str(story_type),
            "story_type_headline": story_type.get("headline", "") if isinstance(story_type, dict) else "",
            "story_type_rationale": story_type.get("rationale", "") if isinstance(story_type, dict) else "",
            "story_type_confidence": story_type.get("confidence", 0) if isinstance(story_type, dict) else 0
        }

        # Prepare locations list
        locations = []
        # After finalization, locations are in 'places' key, before finalization in 'locations' key
        payload_locations = payload.get("places", payload.get("locations", []))
        logging.info(f"Processing {len(payload_locations)} locations for Neo4j save")
        
        for place in payload_locations:
            try:
                loc_name = place.get("location", "")
                if not loc_name:
                    logging.warning("Skipping location with empty name")
                    continue
                    
                logging.info(f"Processing location: {loc_name}")
                place_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, loc_name))
                
                # Extract geocoded coordinates if available
                georesults = place.get("geocode", {}).get("results", {}) or {}
                geometry = georesults.get("geometry", {}) or {}
                coords = geometry.get("coordinates", []) or []
                
                # Safe coordinate extraction
                latitude = None
                longitude = None
                if isinstance(coords, list) and len(coords) >= 2:
                    try:
                        longitude = float(coords[0]) if coords[0] is not None else None
                        latitude = float(coords[1]) if coords[1] is not None else None
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Invalid coordinates for {loc_name}: {coords} - {e}")
                        
                location_data = {
                    "uuid": place_uuid,
                    "name": loc_name,
                    "original_text": place.get("original_text", ""),
                    "type": place.get("type", ""),
                    "importance": place.get("importance", ""),
                    "description": place.get("description", ""),
                    "latitude": latitude,
                    "longitude": longitude
                }
                locations.append(location_data)
                coord_info = f"({latitude}, {longitude})" if latitude and longitude else "no coordinates"
                logging.info(f"Prepared location data for {loc_name} with {coord_info}")
            except Exception as e:
                logging.error(f"Error processing location {place}: {e}")
                continue
            
        logging.info(f"Prepared {len(locations)} locations for Neo4j save")

        # Execute the transaction - only locations for now
        write_article_with_entities(driver, article_data, locations, [])
    except Exception as e:
        logging.error(f"Error saving to Neo4j: {e}")
    return payload
        