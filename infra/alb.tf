resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Explicit on purpose (#387). "append" is AWS's default, but the app's
  # rate limiter (app/core/rate_limit.py rate_limit_key) depends on it: it
  # reads the RIGHTMOST X-Forwarded-For entry, which is only trustworthy
  # because the ALB appends the real client IP after anything the client
  # sent. Do NOT switch to "remove" (the app would see no client IP and
  # every user would share one rate-limit bucket) or "preserve" (the ALB
  # would stop adding the real IP, leaving only client-forged values).
  # Also assumes the ALB is the ONLY proxy hop; adding a CDN/WAF in front of
  # it means rate_limit_key must change too (see SECURITY.md).
  xff_header_processing_mode = "append"

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for Fargate awsvpc networking

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${local.name_prefix}-api-tg"
  }
}

# HTTP only for now — no domain yet, so there's no cert to put on an HTTPS
# listener. Add a Route53 record + ACM cert + 443 listener (with an 80->443
# redirect) once a domain is available.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
