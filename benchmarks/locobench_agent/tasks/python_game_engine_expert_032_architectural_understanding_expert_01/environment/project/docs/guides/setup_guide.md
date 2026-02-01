```markdown
# LedgerQuest Engine – Setup Guide  
*Version: 1.1.0 • Last updated: 2024-05-09*

Welcome to the LedgerQuest Engine!  
This guide will walk you through:

1. Local development prerequisites  
2. Repository bootstrap (`make init`)  
3. First-time AWS bootstrap (serverless stack)  
4. Running the engine locally (`sam local`, `pytest`)  
5. Deploying a staging environment via CI/CD  
6. Frequently-asked questions & troubleshooting

> ℹ️  The guide assumes **macOS / Linux** and an AWS account with **AdministratorAccess**.  
>    Windows users may substitute `bash` with PowerShell, but command semantics are identical.

---

## 1. Prerequisites

| Tool / Service                 | Minimum version | Reason                               |
| ------------------------------ | --------------- | ------------------------------------ |
| Python                         | 3.11            | Lambda runtime + type-hints          |
| Docker Engine                  | 24.x            | Build Lambda images & GPU workers    |
| AWS CLI                        | 2.13            | Stack deployment & parameter store   |
| AWS SAM CLI                    | 1.112.0         | Local emulation + packaging          |
| Terraform                      | 1.7             | Optional IaC alternative to SAM      |
| Node.js (for level-editor UI)  | 20.x            | Bundles the React/Three.js front-end |
| GNU Make                       | any             | Quality-of-life wrappers             |

> **GPU Workers**  
> If you plan to perform real-time GPU-accelerated renders, install `nvidia-container-toolkit` and ensure that Docker sees your GPU:  
> `docker run --rm --gpus all nvidia/cuda:12.2.0-base nvidia-smi`

---

## 2. Clone & Bootstrap

```bash
# 1. Clone the mono-repo
git clone --depth 1 https://github.com/<your-org>/ledgerquest-engine.git
cd ledgerquest-engine

# 2. Create & activate the Python virtual env
python3.11 -m venv .venv         # macOS/Linux
source .venv/bin/activate        # or .venv\Scripts\activate on Windows

# 3. Install dev requirements
pip install --upgrade pip
pip install -r requirements/dev.txt

# 4. One-liner bootstrap (Makefile)
make init
```

`make init` performs the following:

1. Installs pre-commit hooks (Black, Ruff, MyPy, Commitizen).  
2. Generates a `.env` placeholder for local secrets.  
3. Runs a smoke test (`pytest -q tests/smoke`).  
4. Downloads the latest step-function ASL schemas.

---

## 3. AWS Credentials & Region

LedgerQuest relies on STS-assumed roles and isolates tenants by account + stage.  
We **strongly recommend** a dedicated named profile:

```bash
aws configure --profile ledgerquest-dev
# > AWS Access Key ID [None]: AKIA...
# > AWS Secret Access Key [None]: ****
# > Default region name [None]: us-east-1
# > Default output format [None]: json
```

Validate credentials:

```bash
AWS_PROFILE=ledgerquest-dev aws sts get-caller-identity
```

---

## 4. Infrastructure Provisioning

LedgerQuest ships with **two** IaC flavours. Choose one:

### Option A – AWS SAM (quick start)

```bash
AWS_PROFILE=ledgerquest-dev sam deploy \
  --stack-name ledgerquest-dev \
  --config-env dev \
  --parameter-overrides Stage=dev MaxPlayerSessions=100 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
```

### Option B – Terraform (team or multi-account)

```bash
cd iac/terraform
terraform init -backend-config="profile=ledgerquest-dev"
terraform apply -var="stage=dev" -var="aws_profile=ledgerquest-dev"
```

#### High-level architecture

```mermaid
flowchart TD
    subgraph Lambda "Serverless Game Loop"
        Physics[λ Physics Sim]
        AI[λ AI Behaviour]
        ECS[λ ECS Mutator]
        EventBus((EventBridge))
        Physics --> EventBus
        AI --> EventBus
        ECS --> EventBus
    end
    PlayerWebSocket((API GW • WS))
    PlayerWebSocket --> Physics
    S3Assets((S3 Scene & Assets))
    DynamoState[(DynamoDB State)]
    EventBus -->|Spawn| ECS
    ECS -->|Persist| DynamoState
    S3Assets --> ECS
```

---

## 5. Local Development Workflow

### 5.1 Environment variables

Create `.env.local` (auto-loaded by [pydantic-dotenv]):

```dotenv
AWS_PROFILE=ledgerquest-dev
STAGE=dev
LOG_LEVEL=DEBUG
```

### 5.2 Unit & integration tests

```bash
# Run fast type-checked tests
pytest -q -m "not slow" --cov=ledgerquest_engine --cov-report=term-missing

# Include Step-Function integ tests (~45 s)
pytest -q -m slow
```

### 5.3 Run Lambda functions locally

```bash
# Launch Docker-based API Gateway + Lambda emulation
sam local start-api --warm-containers eager

# In another shell
curl http://127.0.0.1:3000/physics/tick -d '{"delta_time":16}'
```

### 5.4 Autoreload with `watchmedo`

```bash
# Automatically rebuild on file changes
make watch
```

---

## 6. Deploy a Feature Branch to Staging

All pushes to `feature/*` trigger an ephemeral *review environment*:

1. GitHub Actions workflow `.github/workflows/pr-preview.yml` packages the branch.  
2. Creates a suffix-based CloudFormation stack (`ledgerquest-pr-42`).  
3. Comments on the PR with a WebSocket URL for live testing.  
4. Destroys the stack after merge or 7 days of inactivity.

### Manual promotion

```bash
gh workflow run promote.yml -f source_stack=ledgerquest-pr-42 -f target=staging
```

---

## 7. Integrate a Sample Scene

The `/samples` directory contains a minimal WASM-compiled physics scene.

```bash
# Upload sample assets to S3
aws s3 sync samples/scene1 s3://ledgerquest-dev-assets/sample-scene/

# Tell the engine to warm the object pool
aws events put-events --entries file://samples/scene1/warm-pool.json
```

Open your **level editor** (http://localhost:5173) and select *Sample Scene* from the sidebar.  
Within seconds, WebSocket clients should receive a `PoolReadyEvent`.

---

## 8. Clean-up

```bash
# Delete dev stack
sam delete --stack-name ledgerquest-dev --profile ledgerquest-dev

# Or via Terraform
terraform destroy -auto-approve
```

---

## 9. Troubleshooting

| Symptom                             | Possible cause / fix                                                                    |
| ----------------------------------- | --------------------------------------------------------------------------------------- |
| `botocore.exceptions.NoCredentials` | Run `aws configure --profile ledgerquest-dev` or export `AWS_ACCESS_KEY_ID`.           |
| `docker: Error response from daemon: could not select device` | Install NVIDIA drivers & restart Docker.                              |
| `An error occurred (ValidationException) when calling the PutEvents operation` | Check EventBridge schema: stage mismatch.           |
| Hot-reload not working              | Ensure `watchdog` is installed (`pip install watchdog[watchmedo]`).                     |
| `Connection ××× closed abnormally`  | WebSocket ping/pong timeout: increase `IdleTimeout` in `template.yaml`.                 |

---

## 10. Next steps

• Explore the [Scripting System Guide](./scripting_guide.md) to write Lua-like scenarios.  
• Read the [AI Behaviour Trees Walkthrough](./ai_guide.md).  
• Contribute by opening a PR—remember to run `cz bump` for semantic versioning!

Happy questing! 🛡️
```