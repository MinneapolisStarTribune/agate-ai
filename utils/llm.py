import json, os, logging
from openai import OpenAI
from langchain_community.callbacks.manager import get_openai_callback
from conf.settings import OPENAI_API_KEY

OPENAI_MODEL = "gpt-4o"

OPENAI_CLIENT = OpenAI(
    api_key=OPENAI_API_KEY
)

def get_json_openai(system, user, force_object=False):
    """
    Get JSON response from OpenAI
    
    Args:
        system: System prompt
        user: User prompt
        force_object: If True, requires response to be a JSON object. If False, allows arrays.
    """
    try:
        with get_openai_callback() as cb:
            kwargs = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": "%s" % user}
                ],
                "temperature": 0.0
            }
            
            if force_object:
                kwargs["response_format"] = {"type": "json_object"}

            response = OPENAI_CLIENT.chat.completions.create(**kwargs)
            content = response.choices[0].message.content.strip()
            
            if not content:
                raise ValueError("Empty response from LLM")
            
            # Clean up markdown formatting if present
            if content.startswith('```'):
                # Remove opening backticks and optional 'json' identifier
                content = content.split('\n', 1)[1] if '\n' in content else content[3:]
                # Remove closing backticks
                content = content.rsplit('\n', 1)[0] if '\n' in content else content[:-3]
                content = content.strip()
                
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If JSON parsing fails, log the response and raise
                logging.error(f"Failed to parse LLM response as JSON: {content}")
                raise

    except Exception as e:
        logging.error(f"LLM error: {str(e)}")
        raise