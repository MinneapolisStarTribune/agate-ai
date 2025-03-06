#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Print with color
print_green() {
    echo -e "${GREEN}$1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}$1${NC}"
}

print_red() {
    echo -e "${RED}$1${NC}"
}

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    print_red "Azure CLI is not installed. Please install it first."
    exit 1
fi

# Check if user is logged in to Azure
az account show &> /dev/null || {
    print_red "You are not logged in to Azure. Please run 'az login' first."
    exit 1
}

cd .. &&
cp .env .env.bak &&
cp conf/env/azure.env .env &&

# Use .env.production file
ENV_FILE=".env"
print_yellow "Using environment file: $ENV_FILE"

# Load environment variables from .env.production
if [ -f "$ENV_FILE" ]; then
    print_yellow "Loading environment variables from $ENV_FILE"
    export $(grep -v '^#' $ENV_FILE | xargs)
else
    print_red "Environment file $ENV_FILE not found!"
    exit 1
fi

# Check if ACR name is set
ACR_NAME=${ACR_NAME:-agateprd}
RESOURCE_GROUP=${RESOURCE_GROUP:-agate-prd}
WEB_APP_NAME=${WEB_APP_NAME:-agate-web}

# Generate version tag based on timestamp
VERSION=$(date +%Y%m%d%H%M%S)
print_yellow "Using version tag: $VERSION"

# Login to Azure
print_yellow "Logging in to Azure..."
az login

# Login to ACR
print_yellow "Logging in to Azure Container Registry..."
az acr login --name ${ACR_NAME}

# Build web image
print_yellow "Building web Docker image..."
docker build --platform linux/amd64 -t ${ACR_NAME}.azurecr.io/${WEB_APP_NAME}:latest .

# Tag image with version
print_yellow "Tagging web image with version $VERSION..."
docker tag ${ACR_NAME}.azurecr.io/agate-web:latest ${ACR_NAME}.azurecr.io/agate-web:$VERSION

# Push images
print_yellow "Pushing web image to Azure Container Registry..."
docker push ${ACR_NAME}.azurecr.io/agate-web:$VERSION
docker push ${ACR_NAME}.azurecr.io/agate-web:latest

# Load environment variables
source .env

# Get Azure outputs for environment variables
print_yellow "Getting Azure configuration..."

# Non-sensitive outputs
WEB_URL=$(terraform -chdir=terraform/azure/prd output -raw web_url)
REDIS_HOST=$(terraform -chdir=terraform/azure/prd output -raw redis_host)
REDIS_PORT=$(terraform -chdir=terraform/azure/prd output -raw redis_port)
AZURE_STORAGE_ACCOUNT_NAME=$(terraform -chdir=terraform/azure/prd output -raw storage_account_name)
AZURE_STORAGE_CONTAINER_NAME=$(terraform -chdir=terraform/azure/prd output -raw storage_container_name)

# Sensitive outputs
REDIS_KEY=$(terraform -chdir=terraform/azure/prd output -raw redis_key)
SERVICE_BUS_CONNECTION_STRING=$(terraform -chdir=terraform/azure/prd output -raw service_bus_connection_string)
AZURE_STORAGE_CONNECTION_STRING=$(terraform -chdir=terraform/azure/prd output -raw storage_connection_string)
SLACK_LOG_WEBHOOK_URL=$(grep SLACK_LOG_WEBHOOK_URL .env | cut -d '=' -f2)

# Update container app
print_yellow "Updating web container app..."
az containerapp update \
  --name ${WEB_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --image ${ACR_NAME}.azurecr.io/${WEB_APP_NAME}:$VERSION \
  --command "/usr/src/app/conf/docker/entrypoints/entrypoint-web.sh" \
  --set-env-vars \
    "ENVIRONMENT=production" \
    "WEB_URL=${WEB_URL}" \
    "REDIS_HOST=${REDIS_HOST}" \
    "REDIS_PORT=${REDIS_PORT}" \
    "REDIS_KEY=${REDIS_KEY}" \
    "REDIS_CONNECTION_STRING=rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}?ssl_cert_reqs=none" \
    "SERVICE_BUS_CONNECTION_STRING=${SERVICE_BUS_CONNECTION_STRING}" \
    "AZURE_STORAGE_ACCOUNT_NAME=${AZURE_STORAGE_ACCOUNT_NAME}" \
    "AZURE_STORAGE_CONTAINER_NAME=${AZURE_STORAGE_CONTAINER_NAME}" \
    "AZURE_STORAGE_CONNECTION_STRING=${AZURE_STORAGE_CONNECTION_STRING}" \
    "CELERY_BROKER_URL=rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}/0?ssl_cert_reqs=none" \
    "CELERY_RESULT_BACKEND=rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}/0?ssl_cert_reqs=none" \
    "SLACK_LOG_WEBHOOK_URL=${SLACK_LOG_WEBHOOK_URL}" \
    "PYTHONPATH=/usr/src/app"

# Get the web app URL
WEB_URL=$(az containerapp show \
  --name $WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv)

print_green "Web deployment completed successfully!"
print_green "Web app URL: https://$WEB_URL"
print_green "Version: $VERSION"

cp .env.bak .env &&
cd bin/