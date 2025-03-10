import requests
from bs4 import BeautifulSoup
import logging
import urllib.parse
from conf.settings import SCRAPER_API_KEY
from utils.scrapers.strib import StarTribuneArticle
from utils.scrapers.philly import PhillyInquirerArticle

logging.basicConfig(level=logging.INFO)

# More realistic browser user agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-User': '?1',
    'Sec-Fetch-Dest': 'document'
}

# Define a list of proxy services
PROXY_SERVICES = [
    {
        "url": "http://api.scraperapi.com?api_key={api_key}&url={url}&keep_headers=true&premium=true&country_code=us",
        "name": "ScraperAPI Premium"
    }
]

########## PRIVATE FUNCTIONS ##########

def _normalize_url(url):
    """
    Normalize URL to ensure it's properly formatted
    """
    # Fix missing double slash after protocol
    if url.startswith('http:/') and not url.startswith('http://'):
        url = url.replace('http:/', 'http://')
    if url.startswith('https:/') and not url.startswith('https://'):
        url = url.replace('https:/', 'https://')
        
    # Ensure URL has a valid scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url.lstrip('/')
        
    # Parse and reconstruct the URL to normalize it
    try:
        parsed = urllib.parse.urlparse(url)
        # Reconstruct the URL
        url = urllib.parse.urlunparse(parsed)
    except Exception as e:
        logging.error(f"Error normalizing URL {url}: {str(e)}")
        
    return url

def _get_article(url):
    """
    Scrape article from a given URL using ScraperAPI
    
    Args:
        url: The URL of the article to scrape
        
    Returns:
        BeautifulSoup object if successful, None if failed
    """
    try:
        # Get ScraperAPI key from environment
        scraper_api_key = SCRAPER_API_KEY
        
        if scraper_api_key:
            # Set up the payload for ScraperAPI
            payload = {
                'api_key': scraper_api_key,
                'url': url,
                'keep_headers': 'true',
                'premium': 'true',
                'country_code': 'us'
            }
            
            # Try with standard settings
            try:
                logging.info(f"Using ScraperAPI to fetch URL: {url}")
                
                # Make the request with params
                response = requests.get(
                    'https://api.scraperapi.com/',
                    params=payload,
                    headers=HEADERS,
                    timeout=60,
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    logging.info(f"Successfully fetched URL with ScraperAPI: {url}")
                    return BeautifulSoup(response.text, "html.parser")
                else:
                    logging.warning(f"Failed to fetch URL with ScraperAPI: {url}, status code: {response.status_code}")
            except Exception as e:
                logging.error(f"Error fetching URL with ScraperAPI: {url}, error: {str(e)}")
        
        # If ScraperAPI failed or no key, try direct request
        logging.warning(f"Trying direct request for URL: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                logging.info(f"Successfully fetched URL directly: {url}")
                return BeautifulSoup(response.text, "html.parser")
            else:
                logging.error(f"Failed to fetch URL directly: {url}, status code: {response.status_code}")
        except Exception as e:
            logging.error(f"Error fetching URL directly: {url}, error: {str(e)}")
        
        # If we get here, all attempts failed
        logging.error(f"All attempts to fetch URL failed: {url}")
        return None
    except Exception as e:
        logging.error(f"Error in _get_article: {str(e)}")
        return None

########## PUBLIC FUNCTIONS ##########

def scrape(url):
    """
    Scrape article from a given URL, using a proxy service.
    """
    try:
        # Normalize URL
        url = _normalize_url(url)
        
        # Log the normalized URL
        logging.info(f"Scraping URL: {url}")
        
        # Get article content, using appropriate parser
        if "startribune.com" in url:
            article = StarTribuneArticle(_get_article(url))
        elif "inquirer.com" in url:
            article = PhillyInquirerArticle(_get_article(url))
        else:
            # TODO: Ideally this would have a generic parser
            article = None

        if not article:
            logging.error("Failed to get article content")
            return None
            
        # Extract text and headline
        text = article.body
        if not text:
            logging.error("Failed to extract article body")
            
        headline = article.headline
        if not headline:
            logging.error("Failed to extract headline")
        
        # Log the extracted content
        if text:
            logging.info(f"Extracted text: {len(text)} characters")
            logging.info(f"Text preview: {text[:100]}...")
        else:
            logging.error("Failed to extract article body")
            
        if headline:
            logging.info(f"Extracted headline: {headline}")
        else:
            logging.error("Failed to extract headline")
        
        result = {
            "author": article.author,
            "pub_date": article.pub_date,
            "text": text,
            "headline": headline,
            "url": url
        }
        
        logging.info(f"Successfully scraped article: {headline}")
        return result
        
    except Exception as e:
        logging.error(f"Error scraping URL {url}: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return None