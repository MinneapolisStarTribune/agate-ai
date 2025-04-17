import json
from worker.tasks.base.scrape import _scrape_article
from worker.tasks.base.classify import _classify_article

if __name__ == "__main__":
    with open('../data/input.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles[:1]:
        url = payload['url']
        output_filename = payload['output_filename']

        scraped = _scrape_article(url, output_filename)
        classified = _classify_article(scraped)

        output.append(classified)
    
    with open('../data/0-extract-input.json', 'w') as f:
        json.dump(output, f, indent=2)