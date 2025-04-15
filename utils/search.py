import logging
import time
from duckduckgo_search import DDGS

def search_duckduckgo(query, max_results=5, max_retries=3):
    """
    Search DuckDuckGo for location information with retry logic.
    
    Args:
        query (str): Search query
        max_results (int): Maximum number of results to return
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        list: Search results or empty list if search fails
    """
    logging.info(f"Searching DuckDuckGo for: {query}")
    
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                
                if not results:
                    logging.warning(f"No results found for query: {query}")
                    return []
                    
                return results
                
        except Exception as e:
            logging.error(f"Error searching DuckDuckGo (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                logging.info("Waiting 3 seconds before retrying...")
                time.sleep(3)
            else:
                logging.error("Max retries exceeded for DuckDuckGo search")
                return []