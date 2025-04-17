import json
from worker.tasks.locations.review.review import _review_locations

if __name__ == "__main__":
    with open('../data/9-localize-output.json', 'r') as f:
        articles = json.load(f)
        
    output = []
    for payload in articles:
        result = _review_locations(payload)
        output.append(result)
        
    with open('../data/10-final-review-output.json', 'w') as f:
        json.dump(output, f, indent=2)