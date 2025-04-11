import json
from worker.tasks.locations.relevance.consolidate import _consolidate_locations

if __name__ == "__main__":
    with open('./data/classify-output.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles:
        result = _consolidate_locations(payload)
        output.append(result)

    with open('./data/consolidate-output.json', 'w') as f:
        json.dump(output, f, indent=2)