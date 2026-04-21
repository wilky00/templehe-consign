# ABOUTME: Cloudflare Terraform config — WAF managed ruleset and API rate limiting.
# ABOUTME: Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID. See variables.tf.

terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  required_version = ">= 1.5"
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Cloudflare Managed Ruleset (WAF)
resource "cloudflare_ruleset" "waf_managed" {
  zone_id     = var.cloudflare_zone_id
  name        = "temple-he managed WAF"
  description = "Cloudflare Managed Ruleset for temple-he"
  kind        = "zone"
  phase       = "http_request_firewall_managed"

  rules {
    action      = "execute"
    description = "Execute Cloudflare Managed Ruleset"
    enabled     = true
    expression  = "true"

    action_parameters {
      id = "efb7b8c949ac4650a09736fc376e9aee"
    }
  }

  rules {
    action      = "execute"
    description = "Execute Cloudflare OWASP Ruleset"
    enabled     = true
    expression  = "true"

    action_parameters {
      id = "4814384a9e5d4991b9815dcfc25d2f1f"
    }
  }
}

# Rate limiting on /api/* — 100 requests per minute per IP
resource "cloudflare_ruleset" "rate_limit_api" {
  zone_id     = var.cloudflare_zone_id
  name        = "temple-he API rate limiting"
  description = "Rate limit /api/* at 100 req/min per IP"
  kind        = "zone"
  phase       = "http_ratelimit"

  rules {
    action      = "block"
    description = "Block IPs exceeding 100 req/min on /api/*"
    enabled     = true
    expression  = "(http.request.uri.path matches \"^/api/\")"

    ratelimit {
      characteristics     = ["ip.src"]
      period              = 60
      requests_per_period = 100
      mitigation_timeout  = 60
    }
  }
}
