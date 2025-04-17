import json
from worker.tasks.locations.geocode.consolidate import _consolidate_geocoded_locations

if __name__ == "__main__":
    with open('../data/7-review-output.json', 'r') as f:
        articles = json.load(f)
    
    output = []
    for payload in articles:
        result = _consolidate_geocoded_locations(payload)
        output.append(result)
        
    with open('../data/8-consolidate-output.json', 'w') as f:
        json.dump(output, f, indent=2)