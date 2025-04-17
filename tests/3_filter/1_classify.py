import json
from worker.tasks.locations.filter.classify import _classify_locations

if __name__ == "__main__":
    with open('../data/2-review-output.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles:
        result = _classify_locations(payload)
        output.append(result)

    with open('../data/3-classify-output.json', 'w') as f:
        json.dump(output, f, indent=2)