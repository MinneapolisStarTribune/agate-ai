import json
from worker.tasks.locations.geocode.prep import _prep_locations

if __name__ == "__main__":
    with open('./data/prep-input.json', 'r') as f:
        articles = json.load(f)
        
    output = []
    for payload in articles[-1:]:
        result = _prep_locations(payload)
        output.append(result)
        
    with open('./data/prep-output.json', 'w') as f:
        json.dump(output, f, indent=2)