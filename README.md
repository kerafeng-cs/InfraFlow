# InfraFlow

Ngủ đông cho cả môi trường thử nghiệm trên AWS. Tài liệu thiết kế: Technical Design v3.0 và Interface Contracts v3.0.

```
components/   5 component ICS của web-db (Terraform + component.yaml)
blueprints/   blueprint.yaml của catalog (web-db@1.0.0)
ics/          registry.yaml (kiểu cổng, loại tài nguyên, driver) + ví dụ hỏng có chủ đích
services/     mã Python: infraflow/ics (model, planner, checker, compiler, validator),
              desired, controller, drivers, api, cost, local; runner/ cho CodeBuild; tests/
platform/     Terraform của chính InfraFlow (DynamoDB, Lambda, Step Functions, CodeBuild, API, Cognito, web)
web/          web quản lý + sleeping page (HTML/JS tĩnh)
live/dev/     root module đã biên dịch cho môi trường thử tay dev-demo-qa
```

## 0. Chuẩn bị (WSL, một lần)

```bash
cd /mnt/c/Users/lelovo/Desktop/InfraFlow
python3 -m venv .venv && . .venv/bin/activate
pip install -r services/requirements-dev.txt
```

## 1. Test và kiểm định

```bash
cd services
python -m unittest discover -s tests -t .          # 51 test
python -m infraflow.cli check                      # kiểm tĩnh + kiểm tra ghép + model checking
python -m infraflow.cli validate-blueprint ../ics/examples/web-db-shallow.blueprint.yaml   # phải KHÔNG ĐẠT (A2)
python -m infraflow.cli plan --from deep --to awake   # in lifecycle plan + kết quả model check
```

Sửa component hoặc blueprint xong thì chạy lại `python -m infraflow.cli bundle` và
`python -m infraflow.cli compile --components-rel ../../../components --out ../live/dev/web-db-manual --levels`.

## 2. Việc A: ngủ/thức thật ở máy, không cần nền tảng

```bash
cd live/dev/web-db-manual
terraform init
# Kiểm tra main.tf biên dịch khớp state cũ: phải ra "No changes"
terraform plan -var network_present=true -var egress_present=false -var database_present=true \
               -var app_present=false -var entry_present=false

cd ../../../services
python -m infraflow.local status --dir ../live/dev/web-db-manual
python -m infraflow.local go awake --dir ../live/dev/web-db-manual    # 10-20 phút, in URL ALB khi xong
python -m infraflow.local go deep  --dir ../live/dev/web-db-manual    # ngủ sâu: xóa ALB, stop EC2, xóa NAT ∥ stop RDS
```

Mỗi lần `go`: quan sát AWS, sinh plan, model check, rồi mỗi giai đoạn chạy `terraform plan -out`, Plan Validator,
`terraform apply plan.out` và các driver. **Xong buổi thì `go deep`**, đừng để NAT/ALB chạy qua đêm.

## 3. Dựng nền tảng (Việc B, C, D)

```bash
cd platform
terraform init
terraform apply                       # khoảng 5 phút; in site_url, api_url, user_pool_id
POOL=$(terraform output -raw user_pool_id)
aws cognito-idp admin-create-user --profile infraflow --user-pool-id $POOL --username ban@email.com \
  --user-attributes Name=email,Value=ban@email.com Name=email_verified,Value=true Name=custom:org_id,Value=org_nhom10 \
  --temporary-password 'TamThoi123'
aws cognito-idp admin-add-user-to-group --profile infraflow --user-pool-id $POOL --username ban@email.com --group-name infraflow_admins
```

Mở `site_url`, đăng nhập (lần đầu đặt mật khẩu mới), tạo Lease. Tên Lease và Environment ngắn (ví dụ `nhom10` / `qa`)
vì tên ALB tối đa 32 ký tự.

Nền tảng toàn serverless nên gần như không tốn tiền khi không có Environment thức. Một Environment web-db đang thức
tốn khoảng 0,15 USD/giờ (NAT + ALB + EC2 + RDS).

Lỗi thường gặp: tài khoản free plan chặn một dịch vụ (CodeBuild, CloudFront...) thì `terraform apply` báo lỗi
ở tài nguyên đó; ghi lại cho PoC S0.

## 4. Trước khi commit

```bash
terraform fmt -recursive components platform     # không fmt thư mục live/: main.tf ở đó là đầu ra trình biên dịch
cd services && python -m unittest discover -s tests -t .
```
