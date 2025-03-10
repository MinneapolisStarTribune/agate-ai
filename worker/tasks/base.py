import logging, traceback
from utils.llm import get_json_openai
from utils.scrape import scrape
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from utils.slack import post_slack_log_message

celery = Celery(__name__)

@celery.task(name="scrape_article", bind=True, max_retries=3, default_retry_delay=60)
def _scrape_article(self, url):
    """
    Scrape article from URL and process locations
    """
    try:
        logging.info(f"SCRAPE TASK STARTED: Task ID: {self.request.id}, URL: {url}")
        
        # Scrape article with a longer timeout
        try:
            logging.info(f"SCRAPE TASK: Calling scrape function for URL: {url}")
            article = scrape(url)
            logging.info(f"SCRAPE TASK: Scrape function returned: {article is not None}")
        except Exception as e:
            logging.error(f"SCRAPE TASK ERROR: Error scraping article: {str(e)}")
            import traceback
            logging.error(f"SCRAPE TASK ERROR TRACEBACK: {traceback.format_exc()}")
            # Retry the task with exponential backoff
            retry_delay = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
            raise self.retry(exc=e, countdown=retry_delay)
            
        if not article:
            logging.error(f"SCRAPE TASK ERROR: Failed to scrape article, article is None")
            # Retry the task with exponential backoff
            retry_delay = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
            raise self.retry(countdown=retry_delay)
            
        # Extract text and headline
        text = article.get("text", "")
        headline = article.get("headline", "")
        
        logging.info(f"SCRAPE TASK: Extracted headline: '{headline}', text length: {len(text)}")
        
        if not text or not headline:
            logging.error(f"SCRAPE TASK ERROR: Failed to extract text or headline from article: text={bool(text)}, headline={bool(headline)}")
            # Retry the task with exponential backoff
            retry_delay = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
            raise self.retry(countdown=retry_delay)
        
        return {
            "author": article.get("author", ""),
            "pub_date": article.get("pub_date", ""),
            "headline": headline,
            "text": text,
            "url": url
        }
    
    except self.MaxRetriesExceededError:
        logging.error(f"SCRAPE TASK ERROR: Max retries exceeded for scraping article: {url}")
        post_slack_log_message('Error scraping %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return {"status": "error", "error": f"Max retries exceeded for scraping article: {url}"}
    except Exception as e:
        logging.error(f"SCRAPE TASK ERROR: Unexpected error: {str(e)}")
        logging.error(f"SCRAPE TASK ERROR TRACEBACK: {traceback.format_exc()}")
        post_slack_log_message('Error scraping %s' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return {"status": "error", "error": str(e)}


@celery.task(name="classify_story", bind=True, max_retries=3)
def _classify_story(self, payload):
    """
    Classifies a story into a category, which is used to determine the prompt
    for location extraction.
    """
    text = payload.get("text", "")
    headline = payload.get("headline", "")
    url = payload.get("url", "")
    try:
        # Get the story type prompt
        with open('utils/prompts/type.txt', 'r') as f:
            type_prompt = f.read()

        # Clean text and construct user prompt
        user_prompt = f"""Here is the headline:
        {headline}"""

        try:
            # Pass to LLM for classification
            story_type = get_json_openai(type_prompt, user_prompt, force_object=True)
            logging.info(f"Story classified as: {story_type}")
            
            # Return both classification and original text for next task
            return {
                "story_type": story_type,
                "text": text,
                "headline": headline,
                "url": url,
                "author": payload.get("author", ""),
                "pub_date": payload.get("pub_date", "")
            }
            
        except Exception as e:
            # Calculate backoff time: 2^retry_count seconds
            backoff = 2 ** self.request.retries
            logging.error(f"Classification failed, retrying in {backoff} seconds. Error: {str(e)}")
            
            # Retry with exponential backoff
            raise self.retry(exc=e, countdown=backoff)
            
    except MaxRetriesExceededError as e:
        logging.error(f"Max retries exceeded for story classification: {str(e)}")
        post_slack_log_message('Error classifying story %s (max retries exceeded)' % url, {
            'error_message':  str(e.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return {"story_type": None, "text": text, "headline": headline}
        
    except Exception as err:
        logging.error(f"Error in story classification: {err}")
        post_slack_log_message('Error classifying story %s' % url, {
            'error_message':  str(err.args[0]),
            'traceback':  traceback.format_exc()
        }, 'create_error')
        return {"story_type": None, "text": text, "headline": headline}