# EmailNest – Flask + Amazon RDS MySQL

A small email collection app intended for learning AWS EC2, Amazon Linux 2023, security groups, and private RDS connectivity.

## Features

- Public email subscription form
- MySQL storage with unique email constraint
- Password-protected admin page to list and delete addresses
- CSRF protection on forms
- Parameterized SQL queries
- Secrets and database settings supplied through environment variables
- Health endpoint at `/health`

## Architecture

Browser → EC2 (Flask/Gunicorn) → private RDS MySQL endpoint.

Do not expose RDS publicly. The RDS security group should allow inbound TCP 3306 only from the EC2 instance's security group.

## 1. Create the database

In RDS, create a MySQL database in the same VPC and Region as EC2. For a learning setup:
- Single-AZ / no standby
- Public access: No
- Choose only an instance/storage option that the Billing/Free Tier page confirms is covered by your account's remaining free usage or credits.
- Do not enable paid extras such as RDS Proxy, Performance Insights paid retention, or Multi-AZ.

Create a database security group with inbound MySQL TCP 3306 whose source is the EC2 security group (not `0.0.0.0/0`).

After RDS is available, copy its endpoint hostname. It is not a URL and does not include `https://`.

## 2. Create the database and table

Connect to the RDS database from EC2 after configuring the security groups. Install a MySQL client if needed, then run `schema.sql` using an administrator database account. Create a separate restricted application user, for example:

```sql
CREATE USER 'emailapp'@'%' IDENTIFIED BY 'USE_A_LONG_UNIQUE_PASSWORD';
GRANT SELECT, INSERT, DELETE ON email_app.subscribers TO 'emailapp'@'%';
FLUSH PRIVILEGES;
```

The `%` host pattern is constrained by the RDS security group; never open port 3306 to the internet. Store the application user's password only in the server environment file.

## 3. Prepare Amazon Linux 2023 on EC2

SSH into the instance:

```bash
ssh -i your-key.pem ec2-user@YOUR_EC2_PUBLIC_IP
```

Install Python tooling:

```bash
sudo dnf update -y
sudo dnf install -y python3 python3-pip
sudo mkdir -p /opt/emailnest
sudo chown ec2-user:ec2-user /opt/emailnest
```

Upload this project folder to `/opt/emailnest` (for example with `scp -i your-key.pem -r email-collection-aws ec2-user@YOUR_EC2_PUBLIC_IP:/home/ec2-user/`), then:

```bash
cd /home/ec2-user/email-collection-aws
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Configure secrets

Create an environment file:

```bash
nano .env
```

Add values (replace every example):

```bash
FLASK_SECRET_KEY=GENERATE_A_LONG_RANDOM_SECRET
ADMIN_PASSWORD=USE_A_LONG_UNIQUE_ADMIN_PASSWORD
DB_HOST=YOUR_RDS_ENDPOINT
DB_PORT=3306
DB_NAME=email_app
DB_USER=emailapp
DB_PASSWORD=YOUR_DATABASE_PASSWORD
```

Generate a secret with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Protect the file:

```bash
chmod 600 .env
```

Do not upload `.env` to GitHub or share it. The app reads environment variables, so load them before starting Gunicorn:

```bash
set -a
source .env
set +a
```

## 5. Test the app

```bash
gunicorn --bind 127.0.0.1:5000 app:app
```

In another SSH session:

```bash
curl http://127.0.0.1:5000/health
```

Expected response:

```json
{"status":"ok"}
```

Stop Gunicorn with Ctrl+C after testing.

## 6. Put Nginx in front of Gunicorn

For a basic HTTP learning deployment:

```bash
sudo dnf install -y nginx
sudo tee /etc/nginx/conf.d/emailnest.conf >/dev/null <<'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
```

Run Gunicorn as a systemd service for persistence. Create `/etc/systemd/system/emailnest.service`:

```ini
[Unit]
Description=EmailNest Flask application
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/email-collection-aws
EnvironmentFile=/home/ec2-user/email-collection-aws/.env
ExecStart=/home/ec2-user/email-collection-aws/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:5000 app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now emailnest
sudo systemctl status emailnest
```

Visit `http://YOUR_EC2_PUBLIC_IP`. For a real public production site, configure HTTPS with a domain and certificate before collecting real personal data.

## Security notes

- EC2 security group: allow SSH (22) only from your current public IP; allow HTTP (80) from the internet for the demo.
- RDS security group: allow TCP 3306 only from the EC2 security group.
- Keep RDS public access disabled.
- Use a separate least-privilege app database user, not the RDS master user.
- Use strong unique passwords and protect `.env` with `chmod 600`.
- This is a learning demo, not a production-ready mailing-list service. Add privacy notice, consent records, HTTPS, backups, monitoring, and stronger admin authentication before real-world use.
- A public IPv4 address, EC2, RDS storage, backups, data transfer, and other resources can incur charges. Verify account-specific Free Plan coverage and remaining credits before provisioning. Stop/delete resources when not using them; stopping EC2 does not necessarily stop EBS or public IPv4 charges, and RDS storage/backups can continue to cost money.

## Cleanup

When finished:
1. Delete the RDS database. Decide whether to retain a final snapshot; snapshots may incur storage charges.
2. Terminate the EC2 instance.
3. Delete unused EBS volumes, snapshots, Elastic IPs, load balancers, NAT Gateways, and other resources created for the project.
4. Check Billing and Cost Explorer after cleanup.

## 7. Build and publish a Docker image (optional)

The image contains the Flask application, not the RDS database or credentials. RDS remains a separate managed service.

From the project directory on a computer with Docker installed:

```bash
docker build -t YOUR_DOCKERHUB_USERNAME/emailnest:1.0 .
docker login
docker push YOUR_DOCKERHUB_USERNAME/emailnest:1.0
```

Replace `YOUR_DOCKERHUB_USERNAME` with your Docker Hub username. Create the repository on Docker Hub first if needed. Do not make an image public if it contains secrets; this project excludes `.env` through `.dockerignore`.

On the EC2 instance, install Docker using the Amazon Linux 2023 instructions for your instance, then pull and run:

```bash
docker pull YOUR_DOCKERHUB_USERNAME/emailnest:1.0
```

Create a protected environment file on EC2 (do not bake secrets into the image):

```bash
sudo mkdir -p /opt/emailnest
sudo chown ec2-user:ec2-user /opt/emailnest
nano /opt/emailnest/app.env
chmod 600 /opt/emailnest/app.env
```

Put these values in `/opt/emailnest/app.env`:

```bash
FLASK_SECRET_KEY=YOUR_LONG_RANDOM_SECRET
ADMIN_PASSWORD=YOUR_STRONG_ADMIN_PASSWORD
DB_HOST=YOUR_RDS_ENDPOINT
DB_PORT=3306
DB_NAME=email_app
DB_USER=emailapp
DB_PASSWORD=YOUR_DATABASE_PASSWORD
```

Run the container:

```bash
docker run -d \
  --name emailnest \
  --restart unless-stopped \
  --env-file /opt/emailnest/app.env \
  -p 127.0.0.1:8000:8000 \
  YOUR_DOCKERHUB_USERNAME/emailnest:1.0
```

If using Nginx on the EC2 host, configure its proxy target as `http://127.0.0.1:8000`. Do not publish port 8000 publicly; allow HTTP/HTTPS through Nginx instead. Check logs with `docker logs emailnest` and stop/remove with `docker rm -f emailnest`.

### Docker security reminders

- Never put passwords, `.env`, private keys, or database credentials inside the image.
- Keep the RDS database private and allow TCP 3306 only from the EC2 security group.
- Keep the container port bound to localhost when Nginx is the public entry point.
- Docker Hub public images can be downloaded by anyone; this app image should contain code only, not customer data or secrets.
