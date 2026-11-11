# Class hourly_no_data: an ALB is billed per hour and cannot be stopped, so sleep removes it.
# Unlike aws-alb-https-entry it does not attach a fixed instance: the container service that
# binds the "target" port registers its tasks by IP. The entry therefore depends only on the
# network, and the service depends on the entry.

locals {
  https = var.certificate_arn != null
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Load balancer for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  count = local.https ? 1 : 0

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Tasks receive private addresses in the VPC; the service admits the ALB on its side.
resource "aws_vpc_security_group_egress_rule" "to_tasks" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = data.aws_vpc.this.cidr_block
  ip_protocol       = "tcp"
  from_port         = var.target_port
  to_port           = var.target_port
}

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [aws_security_group.alb.id]

  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_lb_target_group" "app" {
  name                 = "${var.name_prefix}-tg"
  port                 = var.target_port
  protocol             = "HTTP"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  deregistration_delay = 30

  health_check {
    path                = var.health_path
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Name = "${var.name_prefix}-tg" }
}

# With a certificate, port 80 redirects to 443. Without one, port 80 forwards to the tasks.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.https ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = local.https ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.app.arn
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.https ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
