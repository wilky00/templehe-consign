# ABOUTME: Terraform outputs for Cloudflare resources.

output "waf_ruleset_id" {
  description = "ID of the deployed WAF managed ruleset"
  value       = cloudflare_ruleset.waf_managed.id
}

output "rate_limit_ruleset_id" {
  description = "ID of the deployed API rate limit ruleset"
  value       = cloudflare_ruleset.rate_limit_api.id
}
