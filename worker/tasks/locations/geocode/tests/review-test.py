import json
from worker.tasks.locations.geocode.review import _validate_locations

if __name__ == "__main__":
    with open('./data/geocode-output.json', 'r') as f:
        articles = json.load(f)
    
    output = []
    for payload in articles:
        result = _validate_locations(payload)
        output.append(result)
        
    with open('./data/review-output.json', 'w') as f:
        json.dump(output, f, indent=2)