# Provides port "volume" (storage.ebs/v1)
output "volume_id" { value = aws_ebs_volume.this.id }
output "availability_zone" { value = aws_ebs_volume.this.availability_zone }
