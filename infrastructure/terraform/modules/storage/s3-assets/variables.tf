variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "task_role_arn" {
  type        = string
  description = "ECS task role — granted read/write on kol-headshots/ prefix"
  default     = ""
}

variable "public_read_prefixes" {
  type        = list(string)
  description = "S3 key prefixes world-readable via bucket policy (e.g. kol-headshots/)"
  default     = ["kol-headshots/"]
}
