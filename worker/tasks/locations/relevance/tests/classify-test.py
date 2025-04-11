import json
from worker.tasks.locations.relevance.classify import _classify_locations

if __name__ == "__main__":
    with open('./data/classify-input.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles:
        result = _classify_locations(payload)
        output.append(result)

    with open('./data/classify-output.json', 'w') as f:
        json.dump(output, f, indent=2)