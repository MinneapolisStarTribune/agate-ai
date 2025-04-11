import json
from worker.tasks.locations.geocode.geocode import _geocode_locations

if __name__ == "__main__":
    with open('./data/prep-output.json', 'r') as f:
        articles = json.load(f)
    
    output = []
    for payload in articles:
        result = _geocode_locations(payload)
        output.append(result)
        
    with open('./data/geocode-output.json', 'w') as f:
        json.dump(output, f, indent=2)