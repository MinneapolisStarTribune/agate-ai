import json
import logging
from braintrust import Eval
from autoevals import ExactMatch
from utils.llm import get_json_openai

logging.basicConfig(level=logging.ERROR)

def get_classification_prompt():
    """Load the classification prompt"""
    with open('../utils/prompts/type.txt', 'r') as f:
        return f.read()

def process_for_eval(text, hooks):
    """Process a single case for evaluation"""
    # Get the classification prompt
    prompt = get_classification_prompt()
    
    # Get model's prediction
    try:
        result = get_json_openai(prompt, f"\nHere is the text:\n{text}")
        predicted = result.get('category') if isinstance(result, dict) else None
    except Exception as e:
        logging.error(f"Error classifying story: {e}")
        predicted = None
    
    hooks.meta(
        description=result.get('rationale'),
        scores=result.get('scores')
    )

    return result.get('category') if isinstance(result, dict) else None

def main():
    # Load evaluation data
    data = json.loads(open('data/classify.json', 'r').read())
    
    # Format data for Braintrust
    eval_data = []
    for case in data.get('cases', []):
        eval_data.append({
            'input': case['input'],
            'expected': case['expected'],
            'metadata': {}  # Add empty metadata dict
        })
    
    # Run evaluation
    Eval(
        "Agate classification test",
        is_public=True,
        data=lambda: eval_data,
        task=process_for_eval,
        scores=[ExactMatch]
    )

if __name__ == "__main__":
    main() 