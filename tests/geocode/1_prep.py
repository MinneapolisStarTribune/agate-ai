import json
from worker.tasks.locations.geocode.prep import _prep_locations

if __name__ == "__main__":
    with open('../data/4-consolidate-output.json', 'r') as f:
        articles = json.load(f)
        
    output = []
    for payload in articles:
        result = _prep_locations(payload)
        output.append(result)
        
    with open('../data/5-prep-output.json', 'w') as f:
        json.dump(output, f, indent=2)