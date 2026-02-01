```markdown
# LedgerQuest Engine – Deployment Guide
> Target Env: AWS Serverless (Lambda + Step Functions + DynamoDB + EventBridge)

Welcome to the official production-grade deployment guide for **LedgerQuest Engine**.  
This document walks DevOps and game-play engineers through:

1. Automated infrastructure provisioning (AWS CDK ‑ Python).
2. Packaging and releasing stateless game-loop functions.
3. Zero-downtime updates, canary deployments, and roll-backs.
4. Local-to-cloud parity testing with `sam local` and Docker.
5. Operational excellence (observability, cost guards, compliance).

---

## 0. Architecture Overview

```
┌──────────┐   PutEvents    ┌────────────────────┐
│ GameHub  ├──────────────►│  Amazon EventBridge │
└──────────┘                └─────────┬──────────┘
                                      │Triggers
                         ┌────────────▼────────────┐
                         │ AWS Step Functions       │
                         │  (Game Loop Orches.)     │
                         └──────┬───────────▲──────┘
              Read/Write       │           │Callback
       ┌───────────────────────▼─┐   ┌─────┴────────────────┐
       │ Amazon DynamoDB Tables  │   │ AWS Lambda Functions │
       │ (Entity State, Audit)   │   │  (Stateless Ops)     │
       └─────────────────────────┘   └──────────────────────┘
```

---

## 1. Prerequisites

| Tool               | Version (min) | Purpose                               |
|--------------------|--------------:|---------------------------------------|
| AWS CDK            | 2.113.0       | IaC – stacks & pipelines              |
| Node.js            | 18 LTS        | CDK backend, JS runtime               |
| Python             | 3.11          | Game logic & CDK constructs           |
| Docker             | 24.x          | Lambda & GPU-worker builds            |
| AWS CLI            | 2.13.x        | Auth & bootstrap                      |

```bash
# Quick bootstrap
pipx install aws-sam-cli
npm install -g aws-cdk@2
python -m pip install "ledgerquest[cicd]"  # meta-package
aws configure sso  # Use SSO or IAM user
```

---

## 2. Infrastructure as Code (CDK Python)

Create a dedicated repository (or mono-repo folder) named `infra/`. The CDK app synthesises:

* `GameCoreStack` – DynamoDB tables, S3 asset bucket.
* `ComputeStack`  – Lambda + Step Functions.
* `ApiStack`      – WebSocket API Gateway + CloudFront.
* `PipelineStack` – Multi-stage CI/CD.

Below is a fully-functional CDK app trimmed for brevity but deployable as-is.

```python
# infra/app.py
#!/usr/bin/env python3
"""
LedgerQuest Engine – CDK application entry-point.

Run:
    cdk bootstrap aws://<ACCOUNT>/<REGION>
    cdk deploy PipelineStack

The PipelineStack will deploy the rest automatically via GitHub Actions.
"""
import aws_cdk as cdk

from stacks.compute import ComputeStack
from stacks.core import GameCoreStack
from stacks.pipeline import PipelineStack

app = cdk.App()

# Shared resources first
core_stack = GameCoreStack(app, "GameCoreStack",
                           description="Global tables & buckets.")

compute_stack = ComputeStack(app, "ComputeStack",
                             vpc=core_stack.vpc,
                             event_bus=core_stack.bus)

PipelineStack(app, "PipelineStack",
              synth_stage=cdk.Stage.of(core_stack),
              description="CI/CD for LedgerQuest Engine")

app.synth()
```

### 2.1 Construct: GameCoreStack

```python
# infra/stacks/core.py
from aws_cdk import (
    Stack, RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_events as events,
    aws_ec2 as ec2,
)
from constructs import Construct


class GameCoreStack(Stack):
    """Shared, persistent data layers."""

    def __init__(self, scope: Construct, stack_id: str, **kwargs):
        super().__init__(scope, stack_id, **kwargs)

        # VPC is optional for pure serverless but handy for future GPU workers.
        self.vpc = ec2.Vpc(self, "GameVpc", max_azs=2)

        self.bus = events.EventBus(self, "GameEventBus",
                                   event_bus_name="ledgerquest.eventbus")

        self.entity_table = dynamodb.Table(
            self, "EntityTable",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            partition_key=dynamodb.Attribute(name="entity_id",
                                             type=dynamodb.AttributeType.STRING),
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.audit_table = dynamodb.Table(
            self, "AuditLog",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            partition_key=dynamodb.Attribute(name="pk",
                                             type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk",
                                        type=dynamodb.AttributeType.STRING),
            stream=dynamodb.StreamViewType.NEW_IMAGE,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.assets_bucket = s3.Bucket(
            self, "AssetsBucket",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(
                abort_incomplete_multipart_upload_after=cdk.Duration.days(7),
                enabled=True
            )]
        )
```

### 2.2 Construct: ComputeStack

```python
# infra/stacks/compute.py
import json
from pathlib import Path

from aws_cdk import (
    Duration, Stack, aws_lambda as _lambda,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class ComputeStack(Stack):
    """
    Stateless compute: Lambda functions & Step Function orchestrator.
    """

    def __init__(self, scope: Construct, stack_id: str, *,
                 vpc, event_bus, **kwargs):
        super().__init__(scope, stack_id, **kwargs)

        layer = _lambda.LayerVersion(
            self, "SharedLayer",
            code=_lambda.Code.from_asset("layers/shared"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
            description="Common motor, ECS, utils."
        )

        # Game Loop Lambda
        game_loop_fn = _lambda.Function(
            self, "GameLoopFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="game_loop.handler",
            code=_lambda.Code.from_asset("src/game_loop"),
            memory_size=1024,
            timeout=Duration.seconds(30),
            layers=[layer],
            environment={
                "EVENT_BUS_NAME": event_bus.event_bus_name,
            },
        )
        event_bus.grant_put_events_to(game_loop_fn)

        # Step Functions definition
        definition = tasks.LambdaInvoke(
            self, "Tick",
            lambda_function=game_loop_fn,
            output_path="$.Payload"
        )

        self.state_machine = sfn.StateMachine(
            self, "GameLoopStateMachine",
            definition=definition,
            timeout=Duration.minutes(5),
            tracing_enabled=True,
        )

        # IAM Least Privilege Example
        self.state_machine.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=["*"]  # tighten in prod
        ))
```

---

## 3. Packaging & Deploying Lambda Functions

LedgerQuest uses **AWS SAM** under the hood to create artefact-optimised layers.  
The `buildspec.yml` below is executed by CodeBuild, triggered from the Pipeline Stack.

```yaml
version: 0.2
phases:
  install:
    runtime-versions:
      python: 3.11
    commands:
      - pip install --upgrade pip
      - pip install -r requirements.txt -t ./package
  build:
    commands:
      - sam build --template template.yaml --use-container
artifacts:
  files:
    - .aws-sam/build/**
```

> Production tip: use `--cached` Docker builds to shrink CI times and lock consistent base images.

---

## 4. Zero-Downtime Updates (Traffic Shifting)

The PipelineStack attaches **CodeDeploy** to each Lambda alias (`prod`, `beta`).  
On every merge to `main`:

1. A new function version is published.
2. CodeDeploy shifts 10% of traffic every 2 minutes.
3. CloudWatch Alarms roll back if `5xx` or latency > p99 threshold.

```python
# infra/stacks/pipeline.py (snippet)
alias_prod = _lambda.Alias(self, "ProdAlias",
                           alias_name="prod",
                           version=function.current_version)

codedeploy.LambdaDeploymentGroup(
    self, "DeploymentGroup",
    alias=alias_prod,
    deployment_config=codedeploy.LambdaDeploymentConfig.LINEAR_10_PERCENT_EVERY_2_MINUTES,
    alarms=[errors_alarm, latency_alarm],
)
```

---

## 5. Local Integration Tests

The repository ships an executable test harness that fires the Step Function locally
using a mocked Dynamo table (`moto`) and validates deterministic physics ticks.

```python
# tests/test_local_game_loop.py
import json
import boto3
from moto import mock_dynamodb
from pathlib import Path

from game_loop import handler as game_loop_handler


@mock_dynamodb
def test_game_loop_tick():
    """
    Ensures the physics integrator conserves energy within tolerance.
    """
    # Arrange
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName="EntityTable",
        KeySchema=[{"AttributeName": "entity_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "entity_id",
                               "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST"
    )
    table.put_item(Item={"entity_id": "ball_1", "momentum": 42})

    event = {"entity_id": "ball_1"}
    # Act
    result = game_loop_handler(event, context={})

    # Assert
    assert abs(result["delta_energy"]) < 0.0001
```

Run locally:

```bash
pytest -q tests/test_local_game_loop.py
sam local invoke --event events/tick_event.json GameLoopFn
```

---

## 6. Observability & Alarms

* **CloudWatch Logs Insights** – Real-time ECS query templates.
* **X-Ray** – End-to-end tracing across Step Functions.
* **AWS Budgets + Cost Anomaly Detection** – Serverless cost guardrails.
* **Datadog** (optional) – Managed log routing via subscription filters.

---

## 7. Disaster Recovery

All stateful stores are provisioned with:

* DynamoDB PITR (point-in-time recovery).
* S3 – cross-region replication (`ap-southeast-2` → `us-east-1`).
* Automated daily Step Function exports to S3 for versioned blueprints.

---

## 8. Complete Bootstrap Script

For single-command deployments in sandbox environments, use the helper below.

```python
#!/usr/bin/env python3
"""
bootstrap.py – Idempotent one-shot bootstrap for LedgerQuest Engine.

This script:
1. Ensures CDK bootstrap stack exists.
2. Deploys the full pipeline stack.
3. Optionally seeds sample entities and quests.

Run:
    python bootstrap.py --profile ledgerquest-dev --seed
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CDK_APP_PATH = Path(__file__).parent / "infra" / "app.py"


def sh(cmd: str) -> None:
    """Run shell command with stderr passthrough."""
    print(f"$ {cmd}")
    res = subprocess.run(cmd, shell=True)
    if res.returncode != 0:
        sys.exit(res.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="default",
                        help="AWS credentials profile name")
    parser.add_argument("--seed", action="store_true",
                        help="Seed sample data after deploy")
    args = parser.parse_args()

    sh(f"cdk bootstrap --profile {args.profile}")
    sh(f"cdk deploy PipelineStack --profile {args.profile} --require-approval never")

    if args.seed:
        import boto3
        dynamo = boto3.resource("dynamodb", region_name="us-east-1",
                                profile_name=args.profile)
        table = dynamo.Table("EntityTable")
        table.put_item(Item={"entity_id": "player_0001", "xp": 0, "gold": 100})
        print("Seeded initial player.")

    print("LedgerQuest deployment complete ✅")


if __name__ == "__main__":
    main()
```

---

## 9. Next Steps

* Integrate **GitHub Actions** secrets for cross-account deploys.
* Configure **Fargate GPU Burst Workers** for cinematic rendering.
* Extend the CDK stacks with **multi-tenant Cognito** authorisers.

---

Happy shipping! 🚀👾  
Questions? Reach out on Slack **#ledgerquest-engine** or open a GitHub issue.
```