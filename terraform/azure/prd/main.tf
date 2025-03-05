# main.tf

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

# Resource Group
resource "azurerm_resource_group" "rg" {
  name     = "agate-prd"
  location = var.location
}

# Container Registry
resource "azurerm_container_registry" "acr" {
  name                = "agateprd"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true
}

# Redis Cache
resource "azurerm_redis_cache" "redis" {
  name                = "agate-redis-prd"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  capacity            = 1
  family              = "C"
  sku_name            = "Basic"
  non_ssl_port_enabled = false
}

# Service Bus
resource "azurerm_servicebus_namespace" "sb" {
  name                = "agate-sb-prd"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Basic"
}

resource "azurerm_servicebus_queue" "queue" {
  name         = "agate-queue-prd"
  namespace_id = azurerm_servicebus_namespace.sb.id
}

# Storage Account
resource "azurerm_storage_account" "storage" {
  name                     = "agateprd"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Enable blob encryption
  blob_properties {
    versioning_enabled = true
  }
}

# Storage Container
resource "azurerm_storage_container" "container" {
  name                  = "agate"
  storage_account_name  = azurerm_storage_account.storage.name
  container_access_type = "blob"
}

# Container Apps Environment
resource "azurerm_container_app_environment" "env" {
  name                       = "agate-env"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  
  # Enable outbound internet access
  workload_profile {
    name                 = "Consumption"
    workload_profile_type = "Consumption"
    maximum_count        = 10
    minimum_count        = 0
  }
}

# Web App
resource "azurerm_container_app" "web" {
  name                         = "agate-web"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "registry-password"
  }

  secret {
    name  = "registry-password"
    value = azurerm_container_registry.acr.admin_password
  }

  template {
    container {
      name   = "web"
      image  = "${azurerm_container_registry.acr.login_server}/agate-web:latest"
      cpu    = 0.5
      memory = "1Gi"
      
      # Add environment variables for outbound connectivity
      env {
        name  = "WEBSITES_PORT"
        value = "8000"
      }
      
      env {
        name  = "WEBSITES_ENABLE_APP_SERVICE_STORAGE"
        value = "true"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# Worker App
resource "azurerm_container_app" "worker" {
  name                         = "agate-worker"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "registry-password"
  }

  secret {
    name  = "registry-password"
    value = azurerm_container_registry.acr.admin_password
  }

  template {
    container {
      name   = "worker"
      image  = "${azurerm_container_registry.acr.login_server}/agate-worker:latest"
      cpu    = 0.5
      memory = "1Gi"
      
      # Add environment variables for outbound connectivity
      env {
        name  = "WEBSITES_ENABLE_APP_SERVICE_STORAGE"
        value = "true"
      }
    }
  }
}