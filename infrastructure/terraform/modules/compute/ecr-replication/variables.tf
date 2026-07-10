variable "destination_region" {
  description = "AWS region that receives replicated ECR images."
  type        = string
  default     = "us-east-2"
}

variable "repository_prefix" {
  description = "Replicate repositories whose names start with this prefix."
  type        = string
  default     = "contenthub"
}

variable "repository_names" {
  description = "Known repository names (used for data sources and outputs)."
  type        = list(string)
  default     = ["contenthub-api", "contenthub-dev-api"]
}
