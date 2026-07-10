variable "name_prefix" {
  description = "Resource name prefix (e.g. contenthub-dr-use2)"
  type        = string
}

variable "deletion_window_in_days" {
  type    = number
  default = 30
}
