import requests, logging, json
from geocodio import GeocodioClient
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from conf.settings import GEOCODE_EARTH_API_KEY, GEOCODIO_API_KEY

########## INITIALIZATION ##########

# State name to abbreviation mapping
STATE_ABBREVS = {
    'alabama': 'AL',
    'alaska': 'AK',
    'arizona': 'AZ',
    'arkansas': 'AR',
    'california': 'CA',
    'colorado': 'CO',
    'connecticut': 'CT',
    'delaware': 'DE',
    'florida': 'FL',
    'georgia': 'GA',
    'hawaii': 'HI',
    'idaho': 'ID',
    'illinois': 'IL',
    'indiana': 'IN',
    'iowa': 'IA',
    'kansas': 'KS',
    'kentucky': 'KY',
    'louisiana': 'LA',
    'maine': 'ME',
    'maryland': 'MD',
    'massachusetts': 'MA',
    'michigan': 'MI',
    'minnesota': 'MN',
    'mississippi': 'MS',
    'missouri': 'MO',
    'montana': 'MT',
    'nebraska': 'NE',
    'nevada': 'NV',
    'new hampshire': 'NH',
    'new jersey': 'NJ',
    'new mexico': 'NM',
    'new york': 'NY',
    'north carolina': 'NC',
    'north dakota': 'ND',
    'ohio': 'OH',
    'oklahoma': 'OK',
    'oregon': 'OR',
    'pennsylvania': 'PA',
    'rhode island': 'RI',
    'south carolina': 'SC',
    'south dakota': 'SD',
    'tennessee': 'TN',
    'texas': 'TX',
    'utah': 'UT',
    'vermont': 'VT',
    'virginia': 'VA',
    'washington': 'WA',
    'west virginia': 'WV',
    'wisconsin': 'WI',
    'wyoming': 'WY',
    'district of columbia': 'DC'
}

# Initialize Geocodio client
geocodio_client = None
if GEOCODIO_API_KEY:
    try:
        geocodio_client = GeocodioClient(GEOCODIO_API_KEY)
        logging.info("Geocodio client initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing Geocodio client: {str(e)}")

########## LLM FUNCTIONS ##########

def get_city_state(location_str):
    """
    Use LLM to extract city and state from a location string.
    
    Args:
        location_str (str): Location string to parse
        
    Returns:
        dict: Dictionary containing city and state, or None if extraction fails
        Example: {"city": "Minneapolis", "state": "MN"}
    """
    llm = ChatOpenAI(model="gpt-4o-mini")
    
    template = """Extract the city and state from the following location string.
    Return ONLY a JSON object with two fields:
    - city: The city name (or null if not found)
    - state: The state name or abbreviation (or null if not found)
    
    Location: {location}
    
    Return only the JSON with no additional text:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm
    
    try:
        result = chain.invoke({"location": location_str})
        
        # Clean the response content
        content = result.content.strip()
        if content.startswith('```') and content.endswith('```'):
            content = content[3:-3].strip()
        if content.startswith('json'):
            content = content[4:].strip()
            
        return json.loads(content)
        
    except Exception as e:
        logging.error(f"Error extracting city/state from '{location_str}': {str(e)}")
        return None

########## GEOCODING FUNCTIONS ##########

def pelias_geocode_reverse(lat, lng):
    """
    Geocode a location using the Pelias Geocode Earth reverse API.
    """
    query = "https://api.geocode.earth/v1/reverse?" \
            "api_key="+GEOCODE_EARTH_API_KEY+"&"\
            "point.lat="+str(lat)+"&"\
            "point.lon="+str(lng)

    try:
        response = requests.get(query).json()
        return response
    except Exception as e:
        logging.error(f"Error geocoding {lat}, {lng} with Pelias: {str(e)}")
        return None


def pelias_geocode_search(text):
    """
    Geocode a location using the Pelias Geocode Earth search API.
    """
    query = "https://api.geocode.earth/v1/search?" \
            "api_key="+GEOCODE_EARTH_API_KEY+"&"\
            "text="+text
    try:
        response = requests.get(query).json()

        candidates = []
        for f in response.get('features'):
            candidate = {
                "id": f.get("properties").get("id"),
                "label": f.get("properties").get("label"),
                "geometry": f.get("geometry"),
                "confidence": {
                    "score": f.get("properties").get("confidence"),
                    "match_type": f.get("properties").get("match_type"),
                    "accuracy": f.get("properties").get("accuracy")
                },
                "boundaries": {
                    "neighborhood": {
                        "id": f.get("properties").get("neighbourhood_gid"),
                        "name": f.get("properties").get("neighbourhood"),
                    },
                    "city": {
                        "id": f.get("properties").get("locality_gid"),
                        "name": f.get("properties").get("locality"),
                    },
                    "county": { 
                        "id": f.get("properties").get("county_gid"),
                        "name": f.get("properties").get("county"),
                    },
                    "state": {
                        "id": f.get("properties").get("region_gid"),
                        "name": f.get("properties").get("region"),
                    }
                }
            }
            candidates.append(candidate)
        return candidates
    except Exception as e:
        logging.error(f"Error geocoding {text}: {str(e)}")
        return None


def pelias_geocode_structured(address_obj):
    """
    Geocode a location using the Pelias Geocode Earth structured API.
    """
    # Build query parameters
    params = [f"api_key={GEOCODE_EARTH_API_KEY}"]
    
    # Add available components to query
    if address_obj.get('address'):
        params.append(f"address={requests.utils.quote(address_obj['address'])}")
    if address_obj.get('neighborhood'):
        params.append(f"neighbourhood={requests.utils.quote(address_obj['neighborhood'])}")
    if address_obj.get('locality'):
        params.append(f"locality={requests.utils.quote(address_obj['locality'])}")
    if address_obj.get('county'):
        params.append(f"county={requests.utils.quote(address_obj['county'])}")
    if address_obj.get('region'):
        params.append(f"region={requests.utils.quote(address_obj['region'])}")
    if address_obj.get('country'):
        params.append(f"country={requests.utils.quote(address_obj['country'])}")
    if address_obj.get('postalcode'):
        params.append(f"postalcode={requests.utils.quote(address_obj['postalcode'])}")
            
    if len(params) == 1:  # Only API key
        logging.warning("No address components provided for structured geocoding")
        return None
            
    # Construct the query URL
    query = "https://api.geocode.earth/v1/search/structured?" + "&".join(params)
    
    try:
        response = requests.get(query).json()

        candidates = []
        for f in response.get('features'):
            candidate = {
                "id": f.get("properties").get("id"),
                "label": f.get("properties").get("label"),
                "geometry": f.get("geometry"),
                "confidence": {
                    "score": f.get("properties").get("confidence"),
                    "match_type": f.get("properties").get("match_type"),
                    "accuracy": f.get("properties").get("accuracy")
                },
                "boundaries": {
                    "neighborhood": {
                        "id": f.get("properties").get("neighbourhood_gid"),
                        "name": f.get("properties").get("neighbourhood"),
                    },
                    "city": {
                        "id": f.get("properties").get("locality_gid"),
                        "name": f.get("properties").get("locality"),
                    },
                    "county": { 
                        "id": f.get("properties").get("county_gid"),
                        "name": f.get("properties").get("county"),
                    },
                    "state": {
                        "id": f.get("properties").get("region_gid"),
                        "name": f.get("properties").get("region"),
                    }
                }
            }
            candidates.append(candidate)
        return candidates
    except Exception as e:
        logging.error(f"Error in structured geocoding: {str(e)}")
        return None
    
    
def geocodio_geocode(text):
    """
    Geocode a location using the Geocodio search API.
    
    Args:
        text (str): Location text to geocode
        
    Returns:
        list: List of candidate results in standardized format, or None if geocoding fails
        
    """
    if not geocodio_client:
        logging.error("Geocodio client not initialized")
        return None
        
    try:
        geocodio_response = geocodio_client.geocode(text)

        if not geocodio_response or not geocodio_response.get('results'):
            return None
        
        for result in geocodio_response.get('results'):

            # Fall back to city and state if accuracy is too low
            if result.get('accuracy') < 0.8:
                city_state = get_city_state(text)
                
                city = city_state.get('city')
                state = city_state.get('state')

                if city and state:
                    return pelias_geocode_search(f"{city}, {state}")
                else:
                    result = None
            # If accuracy is sufficient, try to get a point and reverse geocode for consistency with Pelias
            else:
                lat = result.get('location').get('lat')
                lng = result.get('location').get('lng')

                try:    
                    response = pelias_geocode_reverse(lat, lng)
                    candidates = []
                    for f in response.get('features')[:1]:
                        candidate = {
                            "id": f.get("properties").get("id"),
                            "label": f.get("properties").get("label"),
                            "geometry": f.get("geometry"),
                            "confidence": {
                                "score": f.get("properties").get("confidence"),
                                "match_type": f.get("properties").get("match_type"),
                                "accuracy": f.get("properties").get("accuracy")
                            },
                            "boundaries": {
                                "neighborhood": {
                                    "id": f.get("properties").get("neighbourhood_gid"),
                                    "name": f.get("properties").get("neighbourhood"),
                                },
                                "city": {
                                    "id": f.get("properties").get("locality_gid"),
                                    "name": f.get("properties").get("locality"),
                                },
                                "county": { 
                                    "id": f.get("properties").get("county_gid"),
                                    "name": f.get("properties").get("county"),
                                },
                                "state": {
                                    "id": f.get("properties").get("region_gid"),
                                    "name": f.get("properties").get("region"),
                                }
                            }
                        }
                        candidates.append(candidate)
                    return candidates
                except Exception as e:
                    logging.error(f"Error geocoding {text} with Pelias: {str(e)}")
                    return None
        
    except Exception as e:
        logging.error(f"Error geocoding {text} with Geocodio: {str(e)}")
        return None

def get_state_abbrev(state_name):
    """
    Convert a state name to its two-letter abbreviation.
    
    Args:
        state_name (str): Full state name (case insensitive)
        
    Returns:
        str: Two-letter state abbreviation, or None if not found
    """
    if not state_name:
        return None
        
    # If input is already an abbreviation, verify and return it
    if len(state_name) == 2:
        abbrev = state_name.upper()
        if abbrev in STATE_ABBREVS.values():
            return abbrev
            
    # Otherwise look up the full name
    lookup = state_name.lower().strip()
    return STATE_ABBREVS.get(lookup)