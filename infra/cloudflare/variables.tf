# ABOUTME: Input variables for Cloudflare Terraform config.
# ABOUTME: Set values in terraform.tfvars (gitignored) — never hardcode here.

variable "cloudflare_api_token" {
  description = "Cloudflare API token with Zone:Edit and Zone:Read permissions"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for the production domain (from Cloudflare dashboard sidebar)"
  type        = string
}
