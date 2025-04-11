import logging, traceback
from utils.scrape import scrape
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

celery = Celery(__name__)

@celery.task(name="scrape_article", bind=True, max_retries=3, default_retry_delay=60)
def _scrape_article(self, url, output_filename):
    """
    Scrape article from URL and process locations
    """
    try:
        logging.info(f"Starting scrape task [Task ID: {self.request.id}] for URL: {url}")
        
        # Scrape article
        article = scrape(url)
        logging.info(f"Scrape completed for URL: {url}, success: {article is not None}")
        
        if not article:
            raise Exception("Failed to scrape article: returned None")
            
        # Extract text and headline
        text = article.get("text", "")
        headline = article.get("headline", "")
        
        logging.info(f"Extracted content - headline: '{headline}', text length: {len(text)}")
        
        if not text or not headline:
            raise Exception(f"Failed to extract content: text={bool(text)}, headline={bool(headline)}")
        
        return {
            "author": article.get("author", ""),
            "pub_date": article.get("pub_date", ""),
            "headline": headline,
            "text": text,
            "url": url,
            "output_filename": output_filename
        }
    
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for scraping article: {url}")
        post_slack_log_message(f'Error scraping {url} (max retries exceeded)', {
            'error_message': str(e.args[0]),
            'traceback': traceback.format_exc()
        }, 'create_error')
        return {"status": "error", "error": f"Max retries exceeded: {url}"}
        
    except Exception as e:
        # Calculate backoff time: 2^retry_count minutes
        backoff = 60 * (2 ** self.request.retries)
        logging.error(f"Error scraping article, retrying in {backoff} seconds. Error: {str(e)}")
        logging.error(f"Error traceback: {traceback.format_exc()}")
        
        if not self.request.retries:  # Only post to Slack on first error
            post_slack_log_message(f'Error scraping {url}', {
                'error_message': str(e.args[0]),
                'traceback': traceback.format_exc()
            }, 'create_error')
            
        raise self.retry(exc=e, countdown=backoff)