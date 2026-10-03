# AWS IoT Device Management - 学习路径 - 高级

> **⚠️ 免责声明：** 本示例仅用于演示和教学目的，未经额外的安全审查和测试，不适合用于生产环境。

这是高级 AWS IoT Device Management 学习路径的示例代码。它配合 Workshop Studio 研讨会 [**AWS IoT Device Management - 学习路径 - 高级**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (涵盖其全部专题) 使用，并且遵循每个学习路径一个存储库的做法，是 [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) 和 [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics) 的姊妹存储库。

它是**整个高级学习路径**的示例代码配套资源，这条学习路径由一组彼此独立的 AWS IoT Device Management 专题组成 (设备预置、设备队列任务执行、设备队列搜索与分析、软件交付 / OTA、安全远程访问以及可观测性)。这些脚本把 **boto3 控制平面**和 **AWS IoT Device SDK for Python v2 设备平面**组合在一起，所以你既会创建云端资源，也会让模拟设备通过 MQTT 连接。每个专题的研讨会内容发布后，对应的脚本就会加入这个存储库。

## 🌍 可用语言

| 语言 | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |
| 🇮🇹 Italiano | [README.it.md](README.it.md) |

脚本本身也已本地化：设置 `AWS_IOT_LANG` (`en`、`es`、`ja`、`ko`、`pt`、`zh`、`de`、`it`、`fr`)，或者在首次运行时以交互方式选择语言。脚本消息目前提供英语、西班牙语、韩语、日语、简体中文和意大利语版本；尚未翻译的消息会回退到英语。

## 🎯 本学习路径中的专题

每个专题都是独立的，你可以按顺序学习，也可以只选需要的专题。每个专题的动手实践内容发布后，脚本就会添加到这里。

| # | 专题 | 状态 | 本存储库中的脚本 |
|---|-------|--------|----------------------|
| 1 | **端到端设备预置** — JITP/JITR、通过声明和通过可信用户进行 Fleet Provisioning、Multi-Account Registration | ✅ 可用 | 有，请参阅[可用脚本](#-可用脚本) |
| 2 | **设备队列任务执行** — 在整个设备队列中使用 AWS IoT Jobs 和 AWS IoT Commands | 🚧 进行中 | 计划中 |
| 3 | **设备队列搜索与分析** — Fleet Indexing、聚合、thing group | 🚧 进行中 | 计划中 |
| 4 | **软件交付 / OTA** — Software Package Catalog、通过 AWS IoT Jobs 进行版本化部署、SBOM | 🚧 进行中 | 计划中 |
| 5 | **安全远程访问** — AWS IoT Secure Tunneling 和通过隧道的 SSH | 🚧 进行中 | 计划中 |
| 6 | **可观测性与故障排除** — AWS IoT 日志记录、Amazon CloudWatch、AWS CloudTrail | 🚧 进行中 | 计划中 |

> 本 README 的其余部分介绍**专题 1 — 端到端设备预置**，也就是目前已提供脚本的专题。其他专题发布后，它们的脚本 (以及各自的基础架构和成本说明) 会按相同的结构添加进来。

## 👥 目标受众

**主要受众：** 在 AWS IoT Core 上设计大规模设备接入的 IoT 开发人员、解决方案架构师和 DevOps 工程师

**先决条件：** 中级 AWS 知识、AWS IoT Core 基础知识 (证书、策略、MQTT)、Python 基础知识以及命令行使用经验

**学习级别：** 高级 — 动手体验每一种预置方法，并了解各自的适用场景

## 🎯 设备预置 - 学习目标

学完专题 1 后，你将能够：

- **自定义 CA + JITP**：注册证书颁发机构，并通过嵌入的预置模板在设备首次连接时自动预置设备
- **JITR**：通过 Lambda 处理程序和国家/地区允许列表防护措施，由 `$aws/events/certificates/registered` 事件驱动注册
- **通过声明进行 Fleet Provisioning**：使用按批次共享的声明证书引导设备，并通过预留 MQTT 主题将其换成永久证书
- **Pre-provisioning hook**：使用同步 Lambda 对 `RegisterThing` 进行把关，允许/拒绝请求并注入 `parameterOverrides`
- **通过可信用户进行 Fleet Provisioning**：以限定范围的 IAM 身份 (移动应用模型) 生成短期声明，并验证最小权限边界
- **Multi-Account Registration**：将设备迁移到另一个区域/账户，这只是一次端点变更，证书保持不变，无需重新生成
- **证书生命周期**：创建、注册、激活/停用证书，附加/分离策略
- **资源清理**：按命名模式精确删除该专题创建的资源，保持通用环境不变

## 🧩 双平面组合

高级预置专题组合了**两个平面**:

- **控制平面 — `boto3`** — 通过 `aws iot ...` API 进行设备管理 (注册证书颁发机构、预置模板、pre-provisioning hook、Multi-Account Registration 等)，统一使用共享的 `safe_api_call` 构造。
- **设备平面 — `aws-iot-device-sdk-python-v2`** — 一个真正通过 MQTT 连接的模拟设备。它提供 `awscrt` / `awsiot` 软件包，并在 JITP、Fleet Provisioning、可信用户、Multi-Account Registration 和证书轮换流程的连接步骤中使用 **MQTT 5** 连接构造 (基于 `awscrt.mqtt5` 的 `awsiot.mqtt5_client_builder.mtls_from_path`)。选择 MQTT 5 是有意为之：它会在每个确认中返回**原因码**，这样设备就能区分授权失败 (`NOT_AUTHORIZED`，0x87，重试也无济于事) 和暂时性失败 (`QUOTA_EXCEEDED`，0x97，重试会有效)。MQTT 3.1.1 根本无法针对发布表达这一点，因为它的 PUBACK 数据包没有原因码字段。

两个平面都通过 `requirements.txt` 一起安装。

## 📋 先决条件

- 具有管理员访问权限的 **AWS 账户** (基础架构堆栈会创建具名 IAM 角色)
- 已完成 [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) 研讨会 (或具有同等经验)
- 已完成 [AWS IoT Device Management - Learning Path - Basics](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) 研讨会 (或具有同等经验)
- 扎实理解 X.509 证书、证书颁发机构 (CA) 和双向 TLS
- 已配置 **AWS 凭证** (`aws configure`、环境变量或 IAM 角色)
- **Python 3.10+** 及 pip
- PATH 中有 **OpenSSL** (用于自定义 CA 和证书签名请求练习)
- **Git**，用于克隆存储库和安装设备平面 SDK

## 💰 成本分析 - 设备预置专题

**此专题会创建真实的 AWS 资源并产生费用。完整运行一遍的预期费用如下：**

| 服务 | 用量 | 预估成本 (USD) |
|---------|-------|---------------------|
| **AWS IoT Core — 消息传递** | 各流程合计几百条 MQTT 消息 | $0.01 - $0.10 |
| **AWS IoT Core — 预置** | 证书、thing、预置模板注册 | $0.01 - $0.10 |
| **AWS Lambda** | JITR 处理程序 + pre-provisioning hook (几十次调用) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | 两个短期存在的 Lambda 日志组 | $0.00 - $0.05 |
| **AWS IoT Core — 第二个区域 (MAR)** | 注册一个证书 + 少量消息 | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | 角色/策略管理 | $0.00 |
| **预估总计** | **完整运行所有方法** | **$0.03 - $0.35** |

**成本管理：**
- ✅ 清理脚本会删除此专题创建的所有资源 (两个区域)
- ✅ 短期、小规模的演示资源
- ⚠️ **完成后记得运行清理脚本，并删除基础架构堆栈**

**📊 监控成本：** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 快速入门

```bash
# 1. 克隆并完成设置
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # Windows 上: venv\Scripts\activate

# 2. 安装两个平面 (boto3 控制平面 + aws-iot-device-sdk-python-v2 设备平面)
pip install -r requirements.txt

# 3. 配置 AWS 并确认 OpenSSL 可用
aws configure
openssl version

# 4. 部署一次基础架构 (创建脚本使用的 IAM 角色和 Lambda 骨架)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. 运行一种方法 (示例: 通过声明进行 Fleet Provisioning)。请参阅下面的“推荐工作流”。
```

## 🏗️ 基础架构 - 设备预置 (请先部署)

*basics* 示例由一个脚本创建自己需要的全部基础架构，高级脚本则不同，它们**假设已经存在一小组预先创建的“基础”资源** (AWS IoT 在预置期间代入的角色，以及两个 Lambda 骨架和它们的执行角色)。在 AWS 主导的活动中，这个堆栈已为你部署好；**独立运行时，你需要**使用本存储库附带的模板**部署一次**:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

它创建的每个资源都有固定的、带模块前缀的名称 (`ws-aws-iot-dm-adv-prov-*`)，因此脚本按确切名称解析它们，无需读取堆栈输出。直接获取脚本需要的值：

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

该堆栈会创建：**JITP 注册角色**、**Fleet Provisioning 角色**、**可信用户角色** (模拟移动应用；由你代入)、**JITR 处理程序** Lambda + 角色、**pre-provisioning hook** Lambda + 角色，以及它们的 CloudWatch 日志组。在你部署处理程序代码之前，Lambda 骨架会返回 "not implemented" (JITR 和 hook 的脚本/步骤会完成部署)。完成后请删除该堆栈 (请参阅“资源清理”)。

## 📚 可用脚本

以下是**端到端设备预置**的脚本 (专题 1)。其他专题的脚本发布后会在这里列出。

| 脚本 | 预置方法 | 用途 |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (第 2 节) | 使用嵌入的 JITP 预置模板 + 注册配置角色注册自定义 CA |
| **manage_jit_provisioning.py** | JITP / JITR (第 2 节) | 管理 JITR 主题规则、部署 JITR 处理程序代码，并查看已预置的 thing |
| **fleet_provision_by_claim.py** | 通过声明的 Fleet Provisioning (第 3 节) | 创建声明证书 + 限定范围的策略，创建模板并管理版本 (带 hook)，运行声明→RegisterThing 的 MQTT 交换，并查看结果 |
| **fleet_provision_trusted_user.py** | 通过可信用户的 Fleet Provisioning (第 4 节) | 创建模板，以可信用户身份生成短期声明，运行 MQTT 交换，并查看结果 |
| **manage_multi_account_registration.py** | MAR (第 5 节) | 不使用 CA 注册证书 (或以 `SNI_ONLY` 模式注册 CA)，获取某个区域的端点，并迁移 (重新连接) 同一个证书 |
| **mqtt_connect.py** | 所有章节 | 最小化的 Device SDK v2 客户端 — 连接 (对首次连接时预期的断开进行重试) 并发布遥测数据 |
| **rotate_certificate.py** | 证书轮换 (第 6 节) | 后端驱动的轮换中设备端的部分 — 领取作业执行，在本地生成新的密钥对 + CSR，安装签名后的证书，重新连接，并在报告成功之前证明发布已获授权 (如果切换失败，则回滚到旧证书) |
| **certificate_manager.py** | 辅助工具 | 交互式证书生命周期管理：创建/注册证书、附加/分离策略、激活/停用 |
| **cleanup_script.py** | 收尾 (第 7 节) | 按命名模式、依照依赖关系顺序，在两个区域中只删除此专题的资源 |

使用 `-h` / `--help` 运行任何脚本，即可查看它的子命令和参数。需要角色或 Lambda ARN 的脚本以参数形式接收它 (例如 `--provisioning-role-arn`、`--role-arn`、`--hook-arn`)，请传入上面从基础堆栈获取的值。

## 📖 推荐工作流

这些脚本与研讨会的模块顺序一致。选择你想练习的方法；部署好基础架构后，每种方法都可以独立运行。

```bash
# --- 通过声明进行 Fleet Provisioning (第 3 节) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (第 5 节) ---
PROD_REGION=us-west-2   # 你的第二个区域 (在 AWS 主导的活动中，使用你的会话中指定的区域)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- 证书轮换 (第 6 节) ---
# 后端驱动的轮换中设备端的部分。添加 --pause 后，会在每个
# 可观察的步骤 (作业 IN_PROGRESS、证书重叠、停用) 停下，
# 方便你在继续之前通过控制台或 AWS CLI 检查状态。
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- 清理 (第 7 节) ---
python3 scripts/cleanup_script.py                      # 试运行 (列出将要删除的内容)
python3 scripts/cleanup_script.py --execute            # 主区域
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # 第二个区域
```

## ⚙️ 配置

**环境变量** (可选)：

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # 设置默认语言 (en, es, fr, ja, ko, pt, zh, de, it)
```

**脚本功能**：原生 `boto3` 控制平面；复用的 Device SDK v2 MQTT 构造；带英语回退的交互式语言选择；大多数脚本支持 `--debug`，可显示 API 调用/响应；为安全清理而添加的研讨会资源标签。

## 🌍 国际化

此学习路径面向研讨会的 9 种语言区域：英语 (`en`)、西班牙语 (`es`)、日语 (`ja`)、韩语 (`ko`)、葡萄牙语 (`pt`)、中文 (`zh`)、德语 (`de`)、意大利语 (`it`) 和法语 (`fr`)。脚本消息目前提供英语、西班牙语、韩语、日语、简体中文和意大利语版本 (`i18n/en/`、`i18n/es/`、`i18n/ko/`、`i18n/ja/`、`i18n/zh/`、`i18n/it/`)；其他语言会逐一添加。设置 `AWS_IOT_LANG` 可以跳过交互式提示；缺少翻译时，脚本会逐条消息回退到英语。

## 🧹 资源清理

**完成后记得清理，以免持续产生费用。** 清理脚本**默认不具破坏性** (试运行)，只会按依赖关系顺序删除与此专题命名模式匹配的资源。

```bash
# 预览 (不删除任何内容)
python3 scripts/cleanup_script.py

# 在主区域中删除 (删除 CA、模板、证书之前会暂停并请你确认)
python3 scripts/cleanup_script.py --execute

# 删除 Multi-Account Registration 使用的第二个区域中的资源
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# 最后，删除基础架构堆栈 (角色、Lambda、日志组)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ 故障排除

- **凭证 / 区域**：通过 `aws configure`、环境变量或 IAM 角色进行配置；MAR 命令需要在 `--region` 中指定有效的第二个区域。
- **"Stack ... does not exist" 或找不到角色/函数**：运行各方法的脚本之前，请先部署基础架构堆栈 (见上文)。
- **IAM/Lambda 上出现 `AccessDenied`**：基础堆栈需要 `CAPABILITY_NAMED_IAM`；运行身份需要有创建角色并将其传递给 `iot.amazonaws.com` / `lambda.amazonaws.com` 的权限。
- **证书卡在 `PENDING_ACTIVATION`**：预置模板/注册角色失败了，请在 CloudTrail 中查找被拒绝的操作 (研讨会内容的 JITP 章节有完整的操作手册)。
- **调试模式**：传入 `--debug` (或回答调试提示) 即可打印所有 API 调用和响应。

## 📁 项目结构

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # 基础架构: IAM 角色 + Lambda 骨架 (部署一次)
├── scripts/                              # 面向用户的可执行脚本
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # 内部辅助软件包
│   └── utils/                            # 控制平面 + 设备平面构造
│       ├── api_helpers.py                # safe_api_call 包装器
│       ├── device_simulator.py           # DeviceConnection MQTT 构造
│       └── fleet_provisioning_templates/ # 预置模板 + 策略 JSON
├── lambdas/                              # 部署到骨架中的 Lambda 代码
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # 第 6 节 — 对 CSR 进行把关并签名，停用旧证书
│   └── rotation_enroller.py               # 第 6 节 — 仅供参考，不部署: 将 Device Defender
│                                          #   的证书使用期限发现结果转换为轮换加入
├── i18n/                                 # 国际化 (消息目录 + 加载器)
├── requirements.txt                      # Python 依赖项 (两个平面)
└── README.md
```

## 📄 许可证

MIT No Attribution License.

## 🏷️ 标签

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
