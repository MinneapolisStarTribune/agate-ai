from bs4 import BeautifulSoup

class Article(object):
    def __init__(self, soup):
        self.soup = soup

    @property
    def author(self):
        return
    
    @property
    def pub_date(self):
        return

    @property
    def headline(self):
        return

    @property
    def body(self):
        return