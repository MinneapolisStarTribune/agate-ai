import json
from worker.tasks.locations.extract.review import _extract_locations_review

if __name__ == "__main__":
    with open('../data/1-extract-output.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles:
        result = _extract_locations_review(payload)
        output.append(result)

    with open('../data/2-review-output.json', 'w') as f:
        json.dump(output, f, indent=2)