variable "destination_region" {
  description = "AWS region that receives replicated ECR images."
  type        = string
  default     = "us-east-2"
}

variable "repository_prefixes" {
  description = "Replicate repositories whose names start with any of these prefixes. MUST include every prefix in use across the account (see main.tf singleton warning)."
  type        = list(string)
  default     = ["contenthub-", "cht-platform-"]
}

variable "repository_names" {
  description = "Known repository names (used for data sources and outputs)."
  type        = list(string)
  default     = ["contenthub-api", "contenthub-dev-api"]
}
