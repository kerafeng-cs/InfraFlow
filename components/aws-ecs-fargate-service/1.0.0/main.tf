# Class stoppable: the service runs one task. The stop and start drivers set the desired count
# to 0 and 1; Terraform creates and removes the service and ignores the desired count after that.

locals {
  task_size = {
    small  = { cpu = 256, memory = 512 }
    medium = { cpu = 512, memory = 1024 }
  }
}

data "aws_region" "current" {}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/infraflow/env/${var.env_id}/app"
  retention_in_days = 7
}

resource "aws_iam_role" "execution" {
  name = "${var.name_prefix}-task-exec"
  path = "/infraflow/env/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.name_prefix}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.task_size[var.size].cpu
  memory                   = local.task_size[var.size].memory
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "app"
    image        = var.app_image
    essential    = true
    portMappings = [{ containerPort = var.app_port, protocol = "tcp" }]
    environment = [
      { name = "PORT", value = tostring(var.app_port) },
      { name = "INFRAFLOW_ENV_ID", value = var.env_id }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
}

resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "Fargate tasks for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-tasks" }
}

resource "aws_vpc_security_group_egress_rule" "tasks_all" {
  security_group_id = aws_security_group.tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The rule admitting the ALB to the tasks follows the service's lifecycle
resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = var.alb_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = var.app_port
  to_port                      = var.app_port
}

resource "aws_ecs_service" "this" {
  name            = "${var.name_prefix}-svc"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "app"
    container_port   = var.app_port
  }

  health_check_grace_period_seconds = 60

  lifecycle {
    # Set by the start and stop drivers
    ignore_changes = [desired_count]
  }
}
