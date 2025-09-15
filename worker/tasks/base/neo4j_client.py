import logging
import uuid
from neo4j import GraphDatabase
from conf.settings import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE

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

def create_article(tx, article_data):
    query = """
    MERGE (a:Article {uuid: $uuid})
    ON CREATE SET
        a.fk_id = $fk_id,
        a.headline = $headline,
        a.url = $url,
        a.author = $author,
        a.pub_date = $pub_date,
        a.story_type_category = $story_type_category,
        a.story_type_headline = $story_type_headline,
        a.story_type_rationale = $story_type_rationale,
        a.story_type_confidence = $story_type_confidence
    ON MATCH SET
        a.fk_id = $fk_id,
        a.headline = $headline,
        a.url = $url,
        a.author = $author,
        a.pub_date = $pub_date,
        a.story_type_category = $story_type_category,
        a.story_type_headline = $story_type_headline,
        a.story_type_rationale = $story_type_rationale,
        a.story_type_confidence = $story_type_confidence
    RETURN a.uuid as uuid
    """
    result = tx.run(query, article_data)
    record = result.single()
    return record["uuid"] if record else None

def create_location(tx, location_data):
    query = """
    MERGE (l:Location {uuid: $uuid})
    ON CREATE SET
      l.name = $name,
      l.original_text = $original_text,
      l.type = $type,
      l.importance = $importance,
      l.description = $description,
      l.latitude = $latitude,
      l.longitude = $longitude
    RETURN l.uuid as uuid
    """
    result = tx.run(query, location_data)
    record = result.single()
    return record["uuid"] if record else None


def create_location_mention(tx, location_uuid, article_uuid):
    query = """
    MATCH (l:Location {uuid: $location_uuid})
    MATCH (a:Article {uuid: $article_uuid})
    CREATE (l)-[:MENTIONED_IN]->(a)
    """
    tx.run(query, {"location_uuid": location_uuid, "article_uuid": article_uuid})


def write_article_with_entities(driver, article_data, locations, persons):
    """
    Wraps creation of Article and Location nodes and their relationships in a transaction.
    """
    with driver.session(database=NEO4J_DATABASE) as session:
        try:
            with session.begin_transaction() as tx:
                article_uuid = create_article(tx, article_data)
                if not article_uuid:
                    logging.error("Failed to create article node")
                    return None
                
                logging.info(f"Created article node with UUID: {article_uuid}")
                
                location_count = 0
                for i, loc in enumerate(locations):
                    try:
                        loc_name = loc.get('name', 'unknown')
                        logging.info(f"Processing location {i+1}/{len(locations)}: {loc_name}")
                        
                        loc_uuid = create_location(tx, loc)
                        if loc_uuid:
                            create_location_mention(tx, loc_uuid, article_uuid)
                            location_count += 1
                            logging.info(f"Successfully created location node and relationship: {loc_name}")
                        else:
                            logging.error(f"Failed to create location node: {loc_name}")
                    except Exception as e:
                        loc_name = loc.get('name', 'unknown')
                        logging.error(f"Error processing location '{loc_name}': {e}")
                        # Continue with other locations rather than failing entire transaction
                
                logging.info(f"Transaction completed: Article {article_uuid} with {location_count}/{len(locations)} locations")
                return article_uuid
        except Exception as e:
            logging.error(f"Transaction failed: {e}")
            return None