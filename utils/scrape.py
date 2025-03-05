import requests
from bs4 import BeautifulSoup
import logging
import urllib.parse
from conf.settings import SCRAPER_API_KEY

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

def _extract_headline(soup):
    """
    Extract headline from article using various selectors
    
    Args:
        soup: BeautifulSoup object of the article page
        
    Returns:
        Headline text if found, None if not found
    """
    # Try different selectors for the headline
    selectors = [
        ('h1', {'data-testid': 'article-hero-header'}),
    ]
    
    for tag, attrs in selectors:
        headline_tag = soup.find(tag, attrs=attrs)
        if headline_tag:
            headline = headline_tag.get_text().strip()
            logging.info(f"Found headline using selector {tag}, {attrs}: {headline}")
            return headline
            
    logging.error("Could not find headline with any selector")
    return "Unknown Headline"  # Return a default value instead of None

def _extract_body(soup):
    """
    Extract article body text using various selectors
    
    Args:
        soup: BeautifulSoup object of the article page
        
    Returns:
        Article body text if found, None if not found
    """
    # Try different selectors for the article body
    body_selectors = [
        ('div', {'data-testid': 'article-body'})
    ]
    
    paragraph_selectors = [
        ('p', {'class': 'rt-Text'})    ]
    
    # Try to find the article body
    for body_tag, body_attrs in body_selectors:
        body_divs = soup.find_all(body_tag, attrs=body_attrs)
        if body_divs:
            logging.info(f"Found article body using selector {body_tag}, {body_attrs}")
            
            all_paragraphs = []
            for div in body_divs:
                # Try different paragraph selectors
                for p_tag, p_attrs in paragraph_selectors:
                    paragraphs = div.find_all(p_tag, attrs=p_attrs)
                    if paragraphs:
                        logging.info(f"Found paragraphs using selector {p_tag}, {p_attrs}")
                        all_paragraphs.extend(p.get_text().strip() for p in paragraphs)
                        break
            
            # Join all paragraphs with newlines
            text = '\n\n'.join(p for p in all_paragraphs if p)
            if text:
                return text
    
    # If we couldn't find the article body using the selectors, try a more general approach
    logging.warning("Could not find article body with specific selectors, trying general approach")
    
    # Get all paragraphs in the document
    paragraphs = soup.find_all('p')
    if paragraphs:
        # Filter out short paragraphs (likely not part of the main content)
        paragraphs = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 50]
        text = '\n\n'.join(paragraphs)
        if text:
            return text
    
    logging.error("Could not extract any text from the article")
    return "No article text found"  # Return a default value instead of None

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
        
        # Get article content
        soup = _get_article(url)
        if not soup:
            logging.error("Failed to get article content")
            return None
            
        # Extract text and headline
        text = _extract_body(soup)
        if not text:
            logging.error("Failed to extract article body")
            
        headline = _extract_headline(soup)
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