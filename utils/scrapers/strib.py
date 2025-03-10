from utils.scrapers.base import Article
import logging

logging.basicConfig(level=logging.INFO)

class StarTribuneArticle(Article):
    def __init__(self, soup):
        self.soup = soup

    @property
    def author(self):
        author_tag = self.soup.find('meta', {'name': 'article:author'})
        if author_tag:
            author = author_tag.get('content', '').strip()
            logging.info(f"Found author: {author}")
            return author
        logging.error("Could not find author")
        return None

    @property
    def pub_date(self):
        pub_date_tag = self.soup.find('meta', {'name': 'article:published_time'})
        if pub_date_tag:
            pub_date = pub_date_tag.get('content', '').strip()
            logging.info(f"Found publication date: {pub_date}")
            return pub_date
        logging.error("Could not find publication date")
        return None

    @property
    def headline(self):
        '''
        Return a headline to a Star Tribune article, based on our knowledge of the
        site structure.
        '''
        # This selector tends to contain the headline
        selectors = [
            ('h1', {'data-testid': 'article-hero-header'}),
        ]
        
        # In case there are other selectors we want to add later, we can iterate over them 
        for tag, attrs in selectors:
            headline_tag = self.soup.find(tag, attrs=attrs)
            if headline_tag:
                headline = headline_tag.get_text().strip()
                logging.info(f"Found headline using selector {tag}, {attrs}: {headline}")
                return headline
                
        logging.error("Could not find headline with any selector")
        return "Unknown Headline"  # Return a default value instead of None

    @property
    def body(self):
        body_selectors = [
            ('div', {'data-testid': 'article-body'})
        ]
        
        paragraph_selectors = [
            ('p', {'class': 'rt-Text'})    ]
        
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