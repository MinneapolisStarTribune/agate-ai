import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '../.env')
load_dotenv(dotenv_path)

########## ENV VARS ##########

ENV = os.getenv('ENV') or 'dev'

# Azure settings
AZURE_NER_ENDPOINT = os.getenv('AZURE_NER_ENDPOINT') or ''
AZURE_KEY = os.getenv('AZURE_KEY') or ''
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING') or ''
AZURE_STORAGE_CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME') or ''
AZURE_STORAGE_ACCOUNT_NAME = os.getenv('AZURE_STORAGE_ACCOUNT_NAME') or ''
ACR_NAME = os.getenv('ACR_NAME') or ''
SERVICE_BUS_CONNECTION_STRING = os.getenv('SERVICE_BUS_CONNECTION_STRING') or ''
WEB_URL = os.getenv('WEB_URL') or ''

# Redis settings
REDIS_HOST = os.getenv('REDIS_HOST') or 'redis'
REDIS_PORT = os.getenv('REDIS_PORT') or 6379
REDIS_DB = os.getenv('REDIS_DB') or 0
REDIS_URL = os.getenv('REDIS_URL') or ''
# External API settings
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or ''
GEOCODIO_API_KEY = os.getenv('GEOCODIO_API_KEY') or ''
GEOCODE_EARTH_API_KEY = os.getenv('GEOCODE_EARTH_API_KEY') or ''
BRAINTRUST_API_KEY = os.getenv('BRAINTRUST_API_KEY') or ''
SCRAPER_API_KEY = os.getenv('SCRAPER_API_KEY') or ''
JINA_API_KEY = os.getenv('JINA_API_KEY') or ''

# Celery settings
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or ''
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or ''
CELERY_QUEUE_NAME = os.environ.get("CELERY_QUEUE_NAME") or 'celery' 
CELERY_BROKER_TRANSPORT_OPTIONS = {'region': os.environ.get("CELERY_QUEUE_REGION", 'us-west-1')}
CELERY_UPDATE_THROTTLE = os.environ.get("CELERY_UPDATE_THROTTLE") or 30 

# Slack credentials, set by environment variables
SLACK_LOG_WEBHOOK_URL = os.getenv('SLACK_LOG_WEBHOOK_URL') or ''

# Context API
CONTEXT_API_URL = os.getenv('CONTEXT_API_URL') or ''

# Star Tribune base URL, for new open in website button
STAR_TRIBUNE_BASE_URL = os.getenv('STAR_TRIBUNE_BASE_URL') or ''

########## FLASK SETTINGS ##########

class FlaskDevelopmentConfig():
    TESTING = False
    WTF_CSRF_ENABLED = False