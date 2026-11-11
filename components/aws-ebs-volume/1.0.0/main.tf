# Class data: the volume holds the workbench's datasets, notebooks and checkpoints. Before it is
# removed (hibernate or reclaim) the snapshot driver takes and verifies a snapshot, and the
# next wake restores the volume from it.

locals {
  size_gb = {
    small  = 50
    medium = 200
  }
}

data "aws_subnet" "first" {
  id = var.subnet_ids[0]
}

resource "aws_ebs_volume" "this" {
  availability_zone = data.aws_subnet.first.availability_zone
  type              = "gp3"
  size              = local.size_gb[var.size]
  encrypted         = true
  snapshot_id       = var.restore_from_snapshot

  tags = { Name = "${var.name_prefix}-data" }

  lifecycle {
    # Changing snapshot_id after a restore would replace the volume and lose the data written since.
    ignore_changes = [snapshot_id]
  }
}
