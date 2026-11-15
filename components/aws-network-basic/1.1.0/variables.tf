variable "env_id" {
  type        = string
  description = "Selects the Availability Zones, so that Environments are spread across them"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix, for example dev-demo-qa"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
