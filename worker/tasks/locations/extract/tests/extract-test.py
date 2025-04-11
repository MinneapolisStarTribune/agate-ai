import json
from worker.tasks.locations.extract.extract import _extract_locations

if __name__ == "__main__":
    with open('./data/extract-input.json', 'r') as f:
        articles = json.load(f)

    output = []
    for payload in articles:
        result = _extract_locations(payload)
        output.append(result)

    with open('./data/extract-output.json', 'w') as f:
        json.dump(output, f, indent=2)