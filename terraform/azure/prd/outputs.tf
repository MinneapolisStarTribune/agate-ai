output "redis_connection_string" {
  description = "The connection string for the Redis cache"
  value       = "rediss://:${azurerm_redis_cache.redis.primary_access_key}@${azurerm_redis_cache.redis.hostname}:${azurerm_redis_cache.redis.ssl_port}?ssl_cert_reqs=CERT_NONE"
  sensitive   = true
}

output "redis_host" {
  description = "The hostname of the Redis cache"
  value       = azurerm_redis_cache.redis.hostname
}

output "redis_port" {
  description = "The port of the Redis cache"
  value       = azurerm_redis_cache.redis.ssl_port
}

output "redis_key" {
  description = "The primary access key for the Redis cache"
  value       = azurerm_redis_cache.redis.primary_access_key
  sensitive   = true
}

output "service_bus_connection_string" {
  description = "The connection string for the Service Bus"
  value       = azurerm_servicebus_namespace.sb.default_primary_connection_string
  sensitive   = true
}

output "web_url" {
  description = "The URL of the web container app"
  value       = azurerm_container_app.web.latest_revision_fqdn
}

output "storage_connection_string" {
  description = "The connection string for the Storage Account"
  value       = azurerm_storage_account.storage.primary_connection_string
  sensitive   = true
}

output "storage_account_name" {
  description = "The name of the Storage Account"
  value       = azurerm_storage_account.storage.name
}

output "storage_container_name" {
  description = "The name of the Storage Container"
  value       = azurerm_storage_container.container.name
}