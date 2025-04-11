import json
import logging
from braintrust import Eval
from autoevals import ExactMatch
from utils.llm import get_json_openai

logging.basicConfig(level=logging.ERROR)

def evaluate_locations(predicted, expected):
    """
    Use LLM to evaluate if all locations are properly extracted.
    """
    if not predicted or not isinstance(predicted, list):
        return {"result": "false", "rationale": "No locations were extracted"}
    
    prompt = f"""You are evaluating a location extraction system. You will be provided a list of locations an LLM extracted from a news article. You will also be provided a list of locations that should have been extracted.

    Here are the locations that should have been extracted:
    {json.dumps(expected, indent=2)}

    Here are the locations that were extracted:
    {json.dumps(predicted, indent=2)}

    If all of the locations are present in the list of locations that should have been extracted, return true in the "result" field of the output object below. Otherwise, return false.

    Minor variations in spelling and formatting of the locations are acceptable and can be ignored. If additional locations are present in the extracted list, that is acceptable and can be ignored.

    Briefly explain your reasoning, then return a JSON object with this structure:
    {{
        "result": boolean,
        "rationale": "detailed explanation of decision"
    }}"""

    try:
        result = get_json_openai(prompt, "")
        return {
            "result": "true" if result.get('result', False) else "false",
            "rationale": result.get('rationale', 'No rationale provided')
        }
    except Exception as e:
        logging.error(f"Error in LLM evaluation: {e}")
        return {"result": "false", "rationale": str(e)}

def process_for_eval(text, hooks):
    """
    Process a single case for evaluation
    """    
    try:
        # Create the appropriate extraction prompt

        # Get the base prompt
        try:
            with open('../worker/tasks/locations/extract/prompts/extract.txt', 'r') as f:
                base_prompt = f.read()
        except FileNotFoundError:
            raise Exception("Base location prompt not found")
        
        # Get the format prompt
        try:
            with open('../worker/tasks/locations/extract/prompts/_formatting.txt', 'r') as f:
                format_prompt = f.read()
        except FileNotFoundError:
            raise Exception("Format location prompt not found")
        
        # Get the output prompt
        try:
            with open('../worker/tasks/locations/extract/prompts/_output.txt', 'r') as f:
                output_prompt = f.read()
        except FileNotFoundError:
            raise Exception("Output location prompt not found")
        
        # Combine the prompts
        prompt = f"{base_prompt}\n\n{format_prompt}\n\n{output_prompt}"
        print(prompt)

        # Get model's prediction
        result = get_json_openai(prompt, f"\nHere is the article text:\n{text}")
        
        # Extract locations from result
        predicted = result.get('locations', [])
        
        # Clean up the prediction to match expected format
        cleaned_locations = []
        for loc in predicted:
            if isinstance(loc, dict):
                cleaned_locations.append({
                    'location': loc.get('location', '')
                })
                
        # Evaluate the locations against criteria
        eval_result = evaluate_locations(cleaned_locations, hooks.metadata.get('eval_locations', ''))
        
        hooks.meta(
            description=result.get('rationale'),
            scores=result.get('scores'),
            extracted_locations=cleaned_locations,
            evaluation_rationale=eval_result['rationale']
        )
        
        return eval_result['result']
        
    except Exception as e:
        logging.error(f"Error extracting locations: {e}")
        return "false"

def main():
    # Load evaluation data
    data = json.loads(open('data/extract.json', 'r').read())
    
    # Format data for Braintrust
    eval_data = []
    for case in data.get('cases', []):
        eval_data.append({
            'input': case['input'],
            'expected': "true",  # We expect all locations to be extracted
            'metadata': {
                'eval_locations': case.get('eval_locations', ''),
            }
        })
    
    # Run evaluation
    Eval(
        "Agate location extraction eval",
        is_public=True,
        data=lambda: eval_data,
        task=process_for_eval,
        scores=[ExactMatch]
    )

if __name__ == "__main__":
    main()
