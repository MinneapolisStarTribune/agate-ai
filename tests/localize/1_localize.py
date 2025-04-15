import json
from worker.tasks.locations.localize.localize import _localize_locations

if __name__ == "__main__":
    with open('../data/8-consolidate-output.json', 'r') as f:
        articles = json.load(f)
        
    output = []
    for payload in articles:
        result = _localize_locations(payload)
        output.append(result)
        
    with open('../data/9-localize-output.json', 'w') as f:
        json.dump(output, f, indent=2)