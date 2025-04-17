import json
from worker.tasks.locations.review.finalize import _finalize_locations

if __name__ == "__main__":
    with open('../data/10-final-review-output.json', 'r') as f:
        articles = json.load(f)
        
    output = []
    for payload in articles:
        result = _finalize_locations(payload)
        output.append(result)
        
    with open('../data/11-finalize-output.json', 'w') as f:
        json.dump(output, f, indent=2)