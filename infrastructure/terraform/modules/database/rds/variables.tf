variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "allowed_security_groups" {
  type = list(string)
}

variable "kms_key_arn" {
  type    = string
  default = ""
}

variable "engine_version" {
  type    = string
  default = "15.17"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "database_name" {
  type    = string
  default = "mediahub"
}

variable "master_username" {
  type    = string
  default = "mediahub_admin"
}

variable "backup_retention_period" {
  type    = number
  default = 7
}

variable "multi_az" {
  type    = bool
  default = false
}
