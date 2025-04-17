#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print with color
print_green() {
    echo -e "${GREEN}$1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}$1${NC}"
}

cd .. &&
cp .env .env.bak &&
cp conf/env/azure.env .env &&

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
CONTEXT_API_URL=$(grep CONTEXT_API_URL .env | cut -d '=' -f2)

# Set variables
RESOURCE_GROUP=${RESOURCE_GROUP:-agate-prd}
ACR_NAME=${ACR_NAME:-agateprd}
WORKER_APP_NAME=${WORKER_APP_NAME:-agate-worker}

# Generate version tag based on timestamp
VERSION=$(date +%Y%m%d%H%M%S)
print_yellow "Using version tag: $VERSION"

# Login to Azure
print_yellow "Logging in to Azure..."
az login

# Login to ACR
print_yellow "Logging in to Azure Container Registry..."
az acr login --name ${ACR_NAME}

print_green "Building and deploying worker container..."

# Build the Docker image
print_green "Building Docker image..."
docker build --platform linux/amd64 -t ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:latest .

# Tag image with version
print_yellow "Tagging worker image with version $VERSION..."
docker tag ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:latest ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:$VERSION

# Push the image to Azure Container Registry
print_green "Pushing image to Azure Container Registry..."
docker push ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:$VERSION
docker push ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:latest

# Update the Container App
print_yellow "Updating Container App..."
az containerapp update \
  --name ${WORKER_APP_NAME} \
  --resource-group ${RESOURCE_GROUP} \
  --image ${ACR_NAME}.azurecr.io/${WORKER_APP_NAME}:$VERSION \
  --command "/usr/src/app/conf/docker/entrypoints/entrypoint-worker.sh" \
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
    "PYTHONPATH=/usr/src/app" \
    "CONTEXT_API_URL=${CONTEXT_API_URL}" \
    "GEOCODE_EARTH_API_KEY=${GEOCODE_EARTH_API_KEY}" \
    "GEOCODIO_API_KEY=${GEOCODIO_API_KEY}"

print_green "Worker container deployed successfully!"

cp .env.bak .env &&
cd ./bin