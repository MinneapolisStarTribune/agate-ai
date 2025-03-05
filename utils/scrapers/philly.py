import requests, logging
from bs4 import BeautifulSoup
from utils.scrapers.base import Article

logging.basicConfig(level=logging.INFO)

class PhillyInquirerArticle(Article):
    def __init__(self, soup):
        self.soup = soup

    @property
    def headline(self):
        '''
        Return a headline to a Philly Inquirer article, based on our knowledge of the
        site structure.
        '''
        selectors = [
            ('h1', {'class': 'inq-headline inq-headline--standard'}),
        ]

        for tag, attrs in selectors:
            headline_tag = self.soup.find(tag, attrs=attrs)
            if headline_tag:
                headline = headline_tag.get_text().strip()
                logging.info(f"Found headline using selector {tag}, {attrs}: {headline}")
                return headline

    @property
    def body(self):
        '''
        Return the body of a Philly Inquirer article, based on our knowledge of the
        site structure.
        '''
        body_selectors = [
            ('div', {'id': 'article-body'})
        ]
        
        paragraph_selectors = [
            ('p', {'class': 'inq-p text-primary'})
        ]

        # Try to find the article body
        for body_tag, body_attrs in body_selectors:
            body_divs = self.soup.find_all(body_tag, attrs=body_attrs)
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
        paragraphs = self.soup.find_all('p')
        if paragraphs:
            # Filter out short paragraphs (likely not part of the main content)
            paragraphs = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 50]
            text = '\n\n'.join(paragraphs)
            if text:
                return text
        
        logging.error("Could not extract any text from the article")
        return "No article text found"  # Return a default value instead of None