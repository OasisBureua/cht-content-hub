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

variable "attach_task_role_policy" {
  type        = bool
  description = "Attach S3 read/write policy to the ECS task role (set true when task_role_arn is wired from module.iam)"
  default     = false
}

variable "public_read_prefixes" {
  type        = list(string)
  description = "S3 key prefixes world-readable via bucket policy (e.g. kol-headshots/)"
  default     = ["kol-headshots/"]
}
