```python
"""
crowdpay_connect/infra/terraform/main.tf  (Python‐CDK for Terraform)

This module defines the core AWS infrastructure for the CrowdPay Connect
platform using the CDK for Terraform (CDKTF).  Resources are provisioned
according to our “Security-by-Design” architecture and provide the
foundation for micro-services, event-sourcing, Saga orchestration and
multi-currency settlement.

NOTE:
    • The module expects CDKTF “providers” to be generated via
      `cdktf get` ( cf. package cdktf_cdktf_provider_aws ).
    • Required environment variables (see _required_envs) must be set
      before synthesising or deploying the stack:
          export AWS_PROFILE=crowdpay-ci
          export AWS_REGION=us-east-1
          export TF_STATE_BUCKET=crowdpay-terraform-state
          export TF_STATE_LOCK_TABLE=crowdpay-terraform-locks
          export ENV=prod|staging|dev
"""

from __future__ import annotations

import os
import sys
from typing import Dict

from cdktf import (
    App,
    S3Backend,
    TerraformOutput,
    TerraformStack,
)
from constructs import Construct

# Generated provider bindings (“cdktf get”)
from cdktf_cdktf_provider_aws.provider import AwsProvider
from cdktf_cdktf_provider_aws.iam_role import IamRole
from cdktf_cdktf_provider_aws.kms_key import KmsKey
from cdktf_cdktf_provider_aws.s3_bucket import S3Bucket, S3BucketVersioning
from cdktf_cdktf_provider_aws.dynamodb_table import (
    DynamodbTable,
    DynamodbTableAttribute,
    DynamodbTablePointInTimeRecovery,
)
from cdktf_cdktf_provider_aws.rds_cluster import RdsCluster
from cdktf_cdktf_provider_aws.rds_cluster_instance import RdsClusterInstance
from cdktf_cdktf_provider_aws.vpc import Vpc
from cdktf_cdktf_provider_aws.subnet import Subnet
from cdktf_cdktf_provider_aws.security_group import SecurityGroup
from cdktf_cdktf_provider_aws.ecs_cluster import EcsCluster
from cdktf_cdktf_provider_aws.cloudwatch_log_group import CloudwatchLogGroup
from cdktf_cdktf_provider_aws.sns_topic import SnsTopic
from cdktf_cdktf_provider_aws.sns_topic_subscription import SnsTopicSubscription


# --------------------------------------------------------------------------------------
# Helper utilities
# --------------------------------------------------------------------------------------
def _validate_env() -> Dict[str, str]:
    """Ensure all mandatory environment variables are present."""
    _required_envs = (
        "AWS_REGION",
        "TF_STATE_BUCKET",
        "TF_STATE_LOCK_TABLE",
        "ENV",
    )
    missing = [v for v in _required_envs if not os.getenv(v)]
    if missing:
        sys.stderr.write(
            f"[ERROR] Missing environment variables: {', '.join(missing)}\n"
        )
        sys.exit(1)

    return {k: os.getenv(k) for k in _required_envs}


def _common_tags(env: str) -> Dict[str, str]:
    """Standardised tags applied to every resource."""
    return {
        "project": "crowdpay-connect",
        "environment": env,
        "managed-by": "cdktf",
        "compliance": "pci-dss",
    }


# --------------------------------------------------------------------------------------
# Terraform Stack
# --------------------------------------------------------------------------------------
class CrowdPayInfraStack(TerraformStack):
    """
    Core infrastructure stack.

    High-level components
    ─────────────────────
    • VPC & networking primitives
    • S3 bucket (encrypted) for compliance reports & artefacts
    • KMS key for envelope encryption
    • DynamoDB table for immutable event store (Event Sourcing, CQRS)
    • Aurora (PostgreSQL) cluster for transactional & read models
    • ECS Cluster (Fargate capacity providers) for micro-services
    • CloudWatch Log Group with retention policy
    • SNS topic for compliance & risk alerts
    """

    def __init__(self, scope: Construct, ns: str, env: Dict[str, str]) -> None:
        super().__init__(scope, ns)

        # -------------------------------------------------------------------
        # Providers / Backend
        # -------------------------------------------------------------------
        AwsProvider(
            self,
            "aws",
            region=env["AWS_REGION"],
            default_tags={"tags": _common_tags(env["ENV"])},
        )

        S3Backend(
            self,
            bucket=env["TF_STATE_BUCKET"],
            key=f"terraform/state/{env['ENV']}/crowdpay-infra.tfstate",
            region=env["AWS_REGION"],
            dynamodb_table=env["TF_STATE_LOCK_TABLE"],
            encrypt=True,
        )

        # -------------------------------------------------------------------
        # KMS – centralised envelope encryption key
        # -------------------------------------------------------------------
        kms_key = KmsKey(
            self,
            "crowdpay-kms",
            description="KMS CMK for CrowdPay Connect – used for S3, DynamoDB, RDS, etc.",
            enable_key_rotation=True,
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # VPC ( /16 ) with public + private isolated subnets
        # -------------------------------------------------------------------
        vpc = Vpc(
            self,
            "crowdpay-vpc",
            cidr_block="10.42.0.0/16",
            enable_dns_support=True,
            enable_dns_hostnames=True,
            tags=_common_tags(env["ENV"]),
        )

        # Public & Private subnets ( 3 AZs )
        public_subnets: list[Subnet] = []
        private_subnets: list[Subnet] = []

        for idx, az in enumerate(["a", "b", "c"], start=1):
            public = Subnet(
                self,
                f"public-{idx}",
                vpc_id=vpc.id,
                availability_zone=f"{env['AWS_REGION']}{az}",
                cidr_block=f"10.42.{idx}.0/24",
                map_public_ip_on_launch=True,
                tags={**_common_tags(env["ENV"]), "tier": "public"},
            )
            public_subnets.append(public)

            private = Subnet(
                self,
                f"private-{idx}",
                vpc_id=vpc.id,
                availability_zone=f"{env['AWS_REGION']}{az}",
                cidr_block=f"10.42.{idx+10}.0/24",
                map_public_ip_on_launch=False,
                tags={**_common_tags(env["ENV"]), "tier": "private"},
            )
            private_subnets.append(private)

        # -------------------------------------------------------------------
        # S3 – Compliance & Audit artefacts
        # -------------------------------------------------------------------
        compliance_bucket = S3Bucket(
            self,
            "compliance-bucket",
            bucket=f"crowdpay-compliance-{env['ENV']}",
            force_destroy=False,
            versioning=S3BucketVersioning(enabled=True),
            server_side_encryption_configuration={
                "rule": {
                    "applyServerSideEncryptionByDefault": {
                        "sseAlgorithm": "aws:kms",
                        "kmsMasterKeyId": kms_key.key_id,
                    }
                }
            },
            lifecycle_rule=[
                {
                    "id": "retain-7-years",
                    "enabled": True,
                    "expiration": {"days": 2555},  # ~7 years
                }
            ],
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # DynamoDB – Append-only event store
        # -------------------------------------------------------------------
        event_store = DynamodbTable(
            self,
            "event-store",
            name=f"crowdpay-event-store-{env['ENV']}",
            billing_mode="PAY_PER_REQUEST",
            hash_key="aggregate_id",
            range_key="sequence",
            attribute=[
                DynamodbTableAttribute(name="aggregate_id", type="S"),
                DynamodbTableAttribute(name="sequence", type="N"),
            ],
            server_side_encryption={
                "enabled": True,
                "kmsKeyArn": kms_key.arn,
            },
            point_in_time_recovery=DynamodbTablePointInTimeRecovery(enabled=True),
            stream_enabled=True,
            stream_view_type="NEW_AND_OLD_IMAGES",
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # Aurora PostgreSQL – ACID read/write projections
        # -------------------------------------------------------------------
        db_sg = SecurityGroup(
            self,
            "db-sg",
            vpc_id=vpc.id,
            description="Allow micro-services access to Aurora cluster",
            ingress=[
                {
                    "description": "ECS services → RDS",
                    "fromPort": 5432,
                    "toPort": 5432,
                    "protocol": "tcp",
                    "cidrBlocks": ["10.42.0.0/16"],
                }
            ],
            egress=[
                {
                    "fromPort": 0,
                    "toPort": 0,
                    "protocol": "-1",
                    "cidrBlocks": ["0.0.0.0/0"],
                }
            ],
            tags=_common_tags(env["ENV"]),
        )

        rds_cluster = RdsCluster(
            self,
            "aurora-cluster",
            cluster_identifier=f"crowdpay-aurora-{env['ENV']}",
            engine="aurora-postgresql",
            engine_version="14.6",
            master_username="crowdpay",
            master_password="ChangeMeInSecretsManager!",  # Placeholder; rotate via Secrets Manager post-creation
            kms_key_id=kms_key.key_id,
            storage_encrypted=True,
            db_subnet_group_name=None,
            vpc_security_group_ids=[db_sg.id],
            skip_final_snapshot=True if env["ENV"] == "dev" else False,
            tags=_common_tags(env["ENV"]),
        )

        # “Serverless v2” instances – pay-per-request
        RdsClusterInstance(
            self,
            "aurora-cluster-instance",
            identifier=f"crowdpay-aurora-{env['ENV']}-instance-1",
            cluster_identifier=rds_cluster.id,
            instance_class="db.serverless",
            engine="aurora-postgresql",
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # ECS – Cluster for micro-services (Fargate only)
        # -------------------------------------------------------------------
        ecs_cluster = EcsCluster(
            self,
            "ecs-cluster",
            name=f"crowdpay-cluster-{env['ENV']}",
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # CloudWatch Logs
        # -------------------------------------------------------------------
        log_group = CloudwatchLogGroup(
            self,
            "crowdpay-logs",
            name=f"/crowdpay/{env['ENV']}",
            retention_in_days=30,
            kms_key_id=kms_key.key_id,
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # IAM – Task execution role (least-privilege)
        # -------------------------------------------------------------------
        task_role = IamRole(
            self,
            "ecs-task-role",
            name=f"crowdpay-task-role-{env['ENV']}",
            assume_role_policy="""{
              "Version": "2012-10-17",
              "Statement": [
                {
                  "Action": "sts:AssumeRole",
                  "Principal": { "Service": "ecs-tasks.amazonaws.com" },
                  "Effect": "Allow"
                }
              ]
            }""",
            inline_policy=[
                {
                    "name": "kms",
                    "policy": kms_key.arn.apply(
                        lambda arn: f"""{{
                          "Version": "2012-10-17",
                          "Statement": [
                            {{
                              "Effect": "Allow",
                              "Action": [
                                "kms:Decrypt",
                                "kms:Encrypt",
                                "kms:GenerateDataKey*"
                              ],
                              "Resource": "{arn}"
                            }}
                          ]
                        }}"""
                    ),
                }
            ],
            tags=_common_tags(env["ENV"]),
        )

        # -------------------------------------------------------------------
        # SNS – compliance / risk alert topic
        # -------------------------------------------------------------------
        compliance_topic = SnsTopic(
            self,
            "compliance-topic",
            name=f"crowdpay-compliance-{env['ENV']}",
            kms_master_key_id=kms_key.key_id,
            tags=_common_tags(env["ENV"]),
        )

        SnsTopicSubscription(
            self,
            "compliance-email-sub",
            topic_arn=compliance_topic.arn,
            protocol="email",
            endpoint="security@crowdpay.example.com",
        )

        # -------------------------------------------------------------------
        # Outputs
        # -------------------------------------------------------------------
        TerraformOutput(self, "compliance_bucket", value=compliance_bucket.bucket)
        TerraformOutput(self, "event_store_table", value=event_store.name)
        TerraformOutput(self, "aurora_endpoint", value=rds_cluster.endpoint)
        TerraformOutput(self, "ecs_cluster_name", value=ecs_cluster.name)
        TerraformOutput(self, "sns_topic_arn", value=compliance_topic.arn)
        TerraformOutput(self, "log_group_name", value=log_group.name)


# --------------------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    env_cfg = _validate_env()

    app = App()
    CrowdPayInfraStack(app, "crowdpay-infra", env_cfg)
    app.synth()
```