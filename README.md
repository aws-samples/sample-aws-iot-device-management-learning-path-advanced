# AWS IoT Device Management - Learning Path - Advanced

Sample code for the **ADVANCED** AWS IoT Device Management learning path. This
repository accompanies the **Advanced Device Provisioning End-to-End** workshop
topic (L300/L400) and is the one-repo-per-learning-path sibling of
[`sample-aws-iot-core-learning-path-basics`](../sample-aws-iot-core-learning-path-basics)
and
[`sample-aws-iot-device-management-learning-path-basics`](../sample-aws-iot-device-management-learning-path-basics).

> **Status:** repository skeleton. Construct code (control-plane and
> device-plane helpers, scripts, and Lambda functions) is added incrementally by
> the workshop authoring tasks. This scaffold establishes the directory layout
> and dependencies so the structure is buildable.

## 🧩 Two-Plane Composition

The advanced provisioning topic simulates real device onboarding by composing
**two planes**:

- **Control plane — `boto3`** — device management via the `aws iot ...` APIs
  (registering certificate authorities, provisioning templates, pre-provisioning
  hooks, Multi-Account Registration, and so on).
- **Device plane — `aws-iot-device-sdk-python-v2`** — a simulated device that
  actually connects over MQTT. It provides the `awscrt` / `awsiot` packages and
  reuses the AWS IoT Core Learning SDK MQTT connection construct
  (`awsiot.mqtt_connection_builder.mtls_from_path` over `awscrt.mqtt`) for the
  connect steps in the JITP, fleet-provisioning, trusted-user, and
  Multi-Account Registration modules.

Both planes are installed together from `requirements.txt` (see below).

## 📋 Prerequisites

- **AWS Account** with administrative access
- **AWS credentials** configured (`aws configure`, environment variables, or IAM roles)
- **Python 3.10+** with pip
- **OpenSSL** available on the PATH (used for custom Certificate Authority and
  Certificate Signing Request exercises)
- **Git** for cloning the repository and installing the device-plane SDK

## 🚀 Quick Start

```bash
# 1. Clone and set up
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install BOTH planes (boto3 control plane + aws-iot-device-sdk-python-v2 device plane)
pip install -r requirements.txt

# 3. Configure AWS
aws configure

# 4. Confirm OpenSSL is available
openssl version
```

## ⚙️ Configuration

**Environment Variables** (optional):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Set default language (en, es, fr, ja, ko, pt, zh, de, it)
```

## 📁 Project Structure

```
sample-aws-iot-device-management-learning-path-advanced/
├── scripts/                              # User-facing executable scripts
├── iot_helpers/                          # Internal helper package
│   └── utils/                            # Utility modules (control-plane constructs)
│       └── fleet_provisioning_templates/ # Provisioning template JSON files
├── lambdas/                              # AWS Lambda functions (JITR, pre-provisioning hooks)
├── i18n/                                 # Internationalization (message catalogs + loader)
├── requirements.txt                      # Python dependencies (both planes)
└── README.md
```

## 🌍 Internationalization

This learning path supports the 9 workshop locales: English (`en`), Spanish
(`es`), Japanese (`ja`), Korean (`ko`), Portuguese (`pt`), Chinese (`zh`),
German (`de`), Italian (`it`), and French (`fr`). Scripts fall back to English
when a translation is missing.

## 📄 License

MIT No Attribution License.

## 🏷️ Tags

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning`
`jitp` `jitr` `multi-account-registration` `python` `iot`
