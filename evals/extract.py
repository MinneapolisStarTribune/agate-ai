import json
import logging
from braintrust import Eval
from autoevals import ExactMatch
from utils.llm import get_json_openai

logging.basicConfig(level=logging.ERROR)

def get_extraction_prompt(story_type):
    """Load the appropriate extraction prompt based on story type"""
    prompt_map = {
        'crime_public_safety': '../utils/prompts/location_extraction/crime_public_safety.txt',
        'weather': '../utils/prompts/location_extraction/weather.txt',
        'elections': '../utils/prompts/location_extraction/elections.txt',
        # Add other story types and their corresponding prompts here
    }
    
    prompt_path = prompt_map.get(story_type)
    if not prompt_path:
        raise ValueError(f"No prompt found for story type: {story_type}")
        
    with open(prompt_path, 'r') as f:
        return f.read()

def evaluate_locations(output, eval_criteria):
    """Use LLM to evaluate if locations meet criteria"""
    if not output or not isinstance(output, list):
        return {"result": "false", "rationale": "No locations were extracted"}
    
    prompt = f"""You are evaluating a location extraction system.

Extracted locations:
{json.dumps(output, indent=2)}

Evaluation criteria:
{eval_criteria}

Do the extracted locations meet ALL of the criteria specified above? Do not apply any additional critiera. If the criteria tell you to return true or false, do not assess and simply return it.
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
    """Process a single case for evaluation"""
    # Get story type from metadata
    story_type = hooks.metadata.get('story_type')
    if not story_type:
        logging.error("No story type provided")
        return "false"
    
    try:
        # Get the appropriate extraction prompt
        prompt = get_extraction_prompt(story_type)
        
        # Get model's prediction
        result = get_json_openai(prompt, f"\nHere is the text:\n{text}")
        
        # Extract locations from result
        predicted = result.get('locations', [])
        
        # Clean up the prediction to match expected format
        cleaned_locations = []
        for loc in predicted:
            if isinstance(loc, dict):
                cleaned_locations.append({
                    'location': loc.get('location', ''),
                    'type': loc.get('type', ''),
                    'nature': loc.get('nature', ''),
                    'description': loc.get('description', '')
                })
                
        # Evaluate the locations against criteria
        eval_result = evaluate_locations(cleaned_locations, hooks.metadata.get('eval_criteria', ''))
        
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
            'expected': "true",  # We expect all criteria to be met
            'metadata': {
                'eval_criteria': case.get('eval_criteria', ''),
                'story_type': case.get('type', '')
            }
        })
    
    # Run evaluation
    Eval(
        "Agate location extraction test",
        is_public=True,
        data=lambda: eval_data,
        task=process_for_eval,
        scores=[ExactMatch]
    )

if __name__ == "__main__":
    main()
