# 1. Setup .env file (then edit it)
Copy-Item .env.example .env

# 2. Validate
python validate_deployment.py

# 3. Install
.\docker.ps1 install

# 4. Access
Start-Process http://localhost:8000