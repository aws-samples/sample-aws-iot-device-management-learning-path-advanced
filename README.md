# AWS IoT Device Management - Learning Path - Advanced

Sample code for the **ADVANCED** AWS IoT Device Management learning path. It accompanies the **AWS IoT Device Management: Advanced** workshop (all of its topics) and is the one-repo-per-learning-path sibling of [`sample-aws-iot-core-learning-path-basics`](../sample-aws-iot-core-learning-path-basics) and [`sample-aws-iot-device-management-learning-path-basics`](../sample-aws-iot-device-management-learning-path-basics).

It is the sample-code companion for the **whole advanced learning path** — a set of self-contained AWS IoT Device Management topics (device provisioning, fleet task execution, fleet search & analytics, software delivery / OTA, secure remote access, and observability). The scripts compose a **boto3 control plane** with an **AWS IoT Device SDK for Python v2 device plane**, so you both create the cloud-side resources and connect a simulated device over MQTT. Scripts for each topic land in this repo as that topic's workshop content is published.

## 🌍 Available Languages

This README is provided in English. The scripts themselves are localized: set `AWS_IOT_LANG` (`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`) or pick a language interactively on first run; missing translations fall back to English.

## 🎯 Topics in This Learning Path

Each topic is self-contained — run them in order or pick the ones you need. Scripts are added here as each topic's hands-on content is published.

| # | Topic | Status | Scripts in this repo |
|---|-------|--------|----------------------|
| 1 | **Device Provisioning End-to-End** — JITP/JITR, Fleet Provisioning by claim and by trusted user, Multi-Account Registration | ✅ Available | Yes — see [Available Scripts](#-available-scripts) |
| 2 | **Fleet Task Execution** — AWS IoT Jobs and AWS IoT Commands across a fleet | 🚧 In progress | Planned |
| 3 | **Fleet Search & Analytics** — Fleet Indexing, aggregations, thing groups | 🚧 In progress | Planned |
| 4 | **Software Delivery / OTA** — Software Package Catalog, versioned deployments via AWS IoT Jobs, SBOM | 🚧 In progress | Planned |
| 5 | **Secure Remote Access** — AWS IoT Secure Tunneling and SSH over a tunnel | 🚧 In progress | Planned |
| 6 | **Observability & Troubleshooting** — AWS IoT logging, Amazon CloudWatch, AWS CloudTrail | 🚧 In progress | Planned |

> The rest of this README documents **Topic 1 — Device Provisioning End-to-End**, the topic whose scripts ship today. As the other topics are published, their scripts (and their own base-infrastructure and cost notes) are added under the same structure.

## 👥 Target Audience

**Primary Audience:** IoT developers, solution architects, and DevOps engineers designing device onboarding at scale on AWS IoT Core

**Prerequisites:** Intermediate AWS knowledge, AWS IoT Core fundamentals (certificates, policies, MQTT), Python fundamentals, and command line usage

**Learning Level:** Advanced — a hands-on tour of every provisioning method and when to use each

## 🎯 Device Provisioning — Learning Objectives

By the end of Topic 1 you can:

- **Custom CA + JITP**: Register a certificate authority and auto-provision devices on first connect with an embedded provisioning template
- **JITR**: Drive registration from the `$aws/events/certificates/registered` event with a Lambda handler and a country allow-list guardrail
- **Fleet Provisioning by claim**: Bootstrap devices with a shared, per-batch claim certificate exchanged for a permanent one over reserved MQTT topics
- **Pre-provisioning hook**: Gate `RegisterThing` with a synchronous Lambda that allows/denies and injects `parameterOverrides`
- **Fleet Provisioning by trusted user**: Mint a short-lived claim as a scoped IAM identity (the mobile-app model) and prove the least-privilege boundary
- **Multi-Account Registration**: Move a device to another Region/account as an endpoint change with the same certificate reused — no re-minting
- **Certificate lifecycle**: Create, register, activate/deactivate, attach/detach policies
- **Resource cleanup**: Remove exactly what the topic created, pattern-scoped, leaving the shared environment intact

## 🧩 Two-Plane Composition

The advanced provisioning topic composes **two planes**:

- **Control plane — `boto3`** — device management via the `aws iot ...` APIs (registering certificate authorities, provisioning templates, pre-provisioning hooks, Multi-Account Registration, and so on), through the shared `safe_api_call` construct.
- **Device plane — `aws-iot-device-sdk-python-v2`** — a simulated device that actually connects over MQTT. It provides the `awscrt` / `awsiot` packages and reuses the MQTT connection construct (`awsiot.mqtt_connection_builder.mtls_from_path` over `awscrt.mqtt`) for the connect steps in the JITP, fleet-provisioning, trusted-user, and Multi-Account Registration flows.

Both planes install together from `requirements.txt`.

## 📋 Prerequisites

- **AWS Account** with administrative access (the base-infrastructure stack creates named IAM roles)
- **AWS credentials** configured (`aws configure`, environment variables, or IAM roles)
- **Python 3.10+** with pip
- **OpenSSL** on the PATH (used for the custom CA and Certificate Signing Request exercises)
- **Git** for cloning the repository and installing the device-plane SDK

## 💰 Cost Analysis — Device Provisioning topic

**This topic creates real AWS resources that will incur charges. Here's what to expect for a complete run:**

| Service | Usage | Estimated Cost (USD) |
|---------|-------|---------------------|
| **AWS IoT Core — messaging** | A few hundred MQTT messages across the flows | $0.01 - $0.10 |
| **AWS IoT Core — provisioning** | Certificates, things, provisioning-template registrations | $0.01 - $0.10 |
| **AWS Lambda** | JITR handler + pre-provisioning hook (tens of invokes) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | Two short-lived Lambda log groups | $0.00 - $0.05 |
| **AWS IoT Core — second Region (MAR)** | One certificate registered + a few messages | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | Role/policy management | $0.00 |
| **Total Estimated** | **Complete run of all methods** | **$0.03 - $0.35** |

**Cost Management:**
- ✅ The cleanup script removes everything this topic creates (both Regions)
- ✅ Short-lived, small-scale demo resources
- ⚠️ **Remember to run the cleanup script — and delete the base-infrastructure stack — when you're finished**

**📊 Monitor costs:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 Quick Start

```bash
# 1. Clone and set up
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install BOTH planes (boto3 control plane + aws-iot-device-sdk-python-v2 device plane)
pip install -r requirements.txt

# 3. Configure AWS and confirm OpenSSL
aws configure
openssl version

# 4. Deploy the base infrastructure ONCE (creates the IAM roles + Lambda skeletons the scripts use)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. Run a method (example: Fleet Provisioning by claim). See "Recommended workflow" below.
```

## 🏗️ Base Infrastructure — Device Provisioning (deploy this first)

Unlike the *basics* sample — where one script creates all of its own infrastructure — the advanced scripts **assume a small set of pre-created "base" resources exist** (the roles AWS IoT assumes during provisioning, plus two Lambda skeletons and their execution roles). At an AWS-led event this stack is deployed for you; **running standalone you deploy it once** with the template shipped in this repo:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

Every resource it creates has a fixed, module-prefixed name (`ws-aws-iot-dm-adv-prov-*`), so the scripts resolve them by exact name — no stack-output plumbing. Capture the values the scripts need directly:

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

The stack creates: the **JITP registration role**, the **fleet provisioning role**, the **trusted-user role** (models the mobile app; you assume it), the **JITR handler** Lambda + role, the **pre-provisioning hook** Lambda + role, and their CloudWatch log groups. The Lambda skeletons return "not implemented" until you deploy the handler code (the JITR and hook scripts/steps do this). Delete the stack when finished (see Cleanup).

## 📚 Available Scripts

These are the **Device Provisioning End-to-End** scripts (Topic 1). Other topics' scripts will be listed here as they ship.

| Script | Provisioning method | Purpose |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (Section 2) | Register a custom CA with an embedded JITP provisioning template + registration-config role |
| **manage_jit_provisioning.py** | JITP / JITR (Section 2) | Manage the JITR topic rule, deploy the JITR handler code, and observe provisioned things |
| **fleet_provision_by_claim.py** | Fleet by claim (Section 3) | Create the claim cert + scoped policy, create/version the template (with hook), run the claim→RegisterThing MQTT exchange, observe |
| **fleet_provision_trusted_user.py** | Fleet by trusted user (Section 4) | Create the template, mint a short-lived claim as the trusted user, run the MQTT exchange, observe |
| **manage_multi_account_registration.py** | MAR (Section 5) | Register a certificate without a CA (or a CA in `SNI_ONLY`), get a Region's endpoint, and move (reconnect) the same certificate |
| **mqtt_connect.py** | All sections | Minimal Device SDK v2 client — connects (retrying the expected first-connect drop) and publishes telemetry |
| **rotate_certificate.py** | Certificate rotation (Section 6) | Device half of a backend-driven rotation — take the job execution, generate a new key pair + CSR locally, install the signed certificate, reconnect, and prove an authorized publish before reporting success (rolls back to the old certificate if the cutover fails) |
| **certificate_manager.py** | Helper | Interactive certificate lifecycle: create/register certificates, attach/detach policies, activate/deactivate |
| **cleanup_script.py** | Closing (Section 7) | Remove only this topic's resources by naming pattern, in dependency order, across both Regions |

Run any script with `-h` / `--help` to see its subcommands and arguments. Scripts that take a role or Lambda ARN accept it as an argument (for example `--provisioning-role-arn`, `--role-arn`, `--hook-arn`) — supply the values captured from the base stack above.

## 📖 Recommended Workflow

The scripts mirror the workshop's module order. Pick the method(s) you want to practice — each is self-contained once the base infrastructure is deployed.

```bash
# --- Fleet Provisioning by claim (Section 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (Section 5) ---
PROD_REGION=us-west-2   # your second Region (at an AWS-led event, the Region named in your session)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- Certificate rotation (Section 6) ---
# Device half of a backend-driven rotation. Add --pause to stop at each
# observable step (job IN_PROGRESS, the certificate overlap, the retirement)
# so you can inspect state in the console or with the AWS CLI before continuing.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- Cleanup (Section 7) ---
python3 scripts/cleanup_script.py                      # dry run (lists what it would remove)
python3 scripts/cleanup_script.py --execute            # main Region
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # second Region
```

## ⚙️ Configuration

**Environment Variables** (optional):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Set default language (en, es, fr, ja, ko, pt, zh, de, it)
```

**Script features**: native `boto3` control plane; reused Device SDK v2 MQTT construct; interactive language selection with English fallback; `--debug` on most scripts to show API calls/responses; workshop resource tagging for safe cleanup.

## 🌍 Internationalization

This learning path targets the 9 workshop locales: English (`en`), Spanish (`es`), Japanese (`ja`), Korean (`ko`), Portuguese (`pt`), Chinese (`zh`), German (`de`), Italian (`it`), and French (`fr`). Set `AWS_IOT_LANG` to skip the interactive prompt; scripts fall back to English when a translation is missing.

## 🧹 Resource Cleanup

**Remember to clean up when you're finished to avoid ongoing charges.** The cleanup script is **non-destructive by default** (dry run) and removes only resources matched by this topic's naming pattern, in dependency order.

```bash
# Preview (deletes nothing)
python3 scripts/cleanup_script.py

# Delete in your main Region (pauses for confirmation before CAs, templates, certificates)
python3 scripts/cleanup_script.py --execute

# Delete the second Region used by Multi-Account Registration
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# Finally, remove the base-infrastructure stack (roles, Lambdas, log groups)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ Troubleshooting

- **Credentials / Region**: configure via `aws configure`, environment variables, or IAM roles; MAR commands need a valid second Region in `--region`.
- **"Stack ... does not exist" or role/function not found**: deploy the base-infrastructure stack (see above) before running the method scripts.
- **`AccessDenied` on IAM/Lambda**: the base stack needs `CAPABILITY_NAMED_IAM`; the running identity needs permission to create roles and pass them to `iot.amazonaws.com` / `lambda.amazonaws.com`.
- **Certificate stuck in `PENDING_ACTIVATION`**: the provisioning template/registration role failed — check CloudTrail for the denied action (the workshop content's JITP section has a full runbook).
- **Debug mode**: pass `--debug` (or answer the debug prompt) to print all API calls and responses.

## 📁 Project Structure

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # Base infra: IAM roles + Lambda skeletons (deploy once)
├── scripts/                              # User-facing executable scripts
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # Internal helper package
│   └── utils/                            # Control-plane + device-plane constructs
│       ├── api_helpers.py                # safe_api_call wrapper
│       ├── device_simulator.py           # DeviceConnection MQTT construct
│       └── fleet_provisioning_templates/ # Provisioning template + policy JSON
├── lambdas/                              # Lambda code deployed to the skeletons
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   └── rotation_handler.py                # Section 6 — signs the CSR, retires the old cert
├── i18n/                                 # Internationalization (message catalogs + loader)
├── requirements.txt                      # Python dependencies (both planes)
└── README.md
```

## 📄 License

MIT No Attribution License.

## 🏷️ Tags

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
