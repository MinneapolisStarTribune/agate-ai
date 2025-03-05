#!/bin/bash

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

# Function to update environment variables
update_env_var() {
    local key=$1
    local value=$2
    local env_file=$3
    
    if grep -q "^$key=" $env_file; then
        sed -i '' "s|^$key=.*|$key=$value|" $env_file
    else
        echo "$key=$value" >> $env_file
    fi
}

# Set paths
TERRAFORM_DIR="../terraform/azure/prd"
ENV_FILE="../conf/env/azure.env"
LOCAL_ENV_FILE="../conf/env/local.env"

# Function to update environment files
update_environments() {
    local azure_env=$1
    local local_env=$2

    # Update Azure environment file
    print_yellow "Updating Azure environment file: $azure_env"
    update_env_var "WEB_URL" "$WEB_URL" "$azure_env"
    update_env_var "REDIS_HOST" "$REDIS_HOST" "$azure_env"
    update_env_var "REDIS_PORT" "$REDIS_PORT" "$azure_env"
    update_env_var "REDIS_KEY" "$REDIS_KEY" "$azure_env"
    update_env_var "REDIS_CONNECTION_STRING" "rediss://:$REDIS_KEY@$REDIS_HOST:$REDIS_PORT?ssl_cert_reqs=CERT_NONE" "$azure_env"
    update_env_var "SERVICE_BUS_CONNECTION_STRING" "$SERVICE_BUS_CONNECTION_STRING" "$azure_env"
    update_env_var "ENVIRONMENT" "production" "$azure_env"
    update_env_var "ACR_NAME" "agateprd" "$azure_env"
    update_env_var "AZURE_STORAGE_ACCOUNT_NAME" "$AZURE_STORAGE_ACCOUNT_NAME" "$azure_env"
    update_env_var "AZURE_STORAGE_CONTAINER_NAME" "$AZURE_STORAGE_CONTAINER_NAME" "$azure_env"
    update_env_var "AZURE_STORAGE_CONNECTION_STRING" "$AZURE_STORAGE_CONNECTION_STRING" "$azure_env"

    # Update local environment file with subset of variables
    print_yellow "Updating local environment file: $local_env"
    update_env_var "ENVIRONMENT" "development" "$local_env"
    update_env_var "AZURE_STORAGE_ACCOUNT_NAME" "$AZURE_STORAGE_ACCOUNT_NAME" "$local_env"
    update_env_var "AZURE_STORAGE_CONTAINER_NAME" "$AZURE_STORAGE_CONTAINER_NAME" "$local_env"
    update_env_var "AZURE_STORAGE_CONNECTION_STRING" "$AZURE_STORAGE_CONNECTION_STRING" "$local_env"
    update_env_var "CELERY_BROKER_URL" "redis://redis:6379/0" "$local_env"
    update_env_var "CELERY_RESULT_BACKEND" "redis://redis:6379/0" "$local_env"
}

# Login to Azure
print_yellow "Logging in to Azure..."
az login

# Create container registry and resource group
print_yellow "Creating container registry and resource group ..."
terraform -chdir=$TERRAFORM_DIR apply \
  -target=azurerm_resource_group.rg -target=azurerm_container_registry.acr

# Login to ACR
print_yellow "Logging in to Azure Container Registry..."
az acr login --name agateprd

# Setup Docker Compose
print_yellow "Setting up Docker Compose..."
cp ../conf/docker/docker-compose.yml.azure ../docker-compose.yml

# Build and push containers
print_yellow "Building and pushing containers..."
docker-compose build
docker-compose push

# Apply full infrastructure
print_yellow "Applying full infrastructure..."
terraform -chdir=$TERRAFORM_DIR apply

# Get Terraform outputs
print_yellow "Getting Terraform outputs..."

# Non-sensitive outputs
WEB_URL=$(terraform -chdir=$TERRAFORM_DIR output -raw web_url)
REDIS_HOST=$(terraform -chdir=$TERRAFORM_DIR output -raw redis_host)
REDIS_PORT=$(terraform -chdir=$TERRAFORM_DIR output -raw redis_port)
AZURE_STORAGE_ACCOUNT_NAME=$(terraform -chdir=$TERRAFORM_DIR output -raw storage_account_name)
AZURE_STORAGE_CONTAINER_NAME=$(terraform -chdir=$TERRAFORM_DIR output -raw storage_container_name)

# Sensitive outputs
REDIS_KEY=$(terraform -chdir=$TERRAFORM_DIR output -raw redis_key)
REDIS_CONNECTION_STRING=$(terraform -chdir=$TERRAFORM_DIR output -raw redis_connection_string)
SERVICE_BUS_CONNECTION_STRING=$(terraform -chdir=$TERRAFORM_DIR output -raw service_bus_connection_string)
AZURE_STORAGE_CONNECTION_STRING=$(terraform -chdir=$TERRAFORM_DIR output -raw storage_connection_string)

# Update both environment files
update_environments "$ENV_FILE" "$LOCAL_ENV_FILE"

print_yellow "Deploying containers ..."
./bin/azure-deploy-web.sh &&
./bin/azure-deploy-worker.sh

print_green "Provisioning and environment setup completed successfully!"