# AWS IoT Device Management - Learning Path - Advanced

> **⚠️ 면책 조항:** 이 샘플은 데모 및 교육 목적으로만 제공되며, 추가적인 보안 검토와 테스트 없이 프로덕션 환경에서 사용하도록 의도된 것이 아니에요.

Advanced AWS IoT Device Management 학습 경로의 샘플 코드예요. [**AWS IoT Device Management - Learning Path - Advanced**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) Workshop Studio 워크숍(모든 주제)과 함께 사용하며, 학습 경로당 리포지토리 하나라는 원칙에 따라 [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) 및 [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics)와 짝을 이루는 리포지토리예요.

이 리포지토리는 **고급 학습 경로 전체**를 위한 샘플 코드예요. 이 학습 경로는 독립적으로 구성된 AWS IoT Device Management 주제(디바이스 프로비저닝, 플릿 작업 실행, 플릿 검색 및 분석, 소프트웨어 배포 / OTA, 보안 원격 액세스, 관찰성)로 이루어져 있어요. 스크립트는 **boto3 컨트롤 플레인**과 **AWS IoT Device SDK for Python v2 디바이스 플레인**을 조합하기 때문에, 클라우드 측 리소스를 만드는 것과 시뮬레이션된 디바이스를 MQTT로 연결하는 것을 모두 해볼 수 있어요. 각 주제의 스크립트는 해당 주제의 워크숍 콘텐츠가 게시될 때 이 리포지토리에 추가돼요.

## 🌍 사용 가능한 언어

| 언어 | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |

스크립트 자체도 현지화되어 있어요. `AWS_IOT_LANG`(`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`)을 설정하거나 처음 실행할 때 대화형으로 언어를 선택하세요. 스크립트 메시지는 현재 영어, 스페인어, 한국어, 일본어, 중국어 간체로 제공되며, 아직 번역되지 않은 메시지는 영어로 폴백돼요.

## 🎯 이 학습 경로의 주제

각 주제는 독립적으로 구성되어 있어요. 순서대로 진행해도 되고 필요한 주제만 골라도 돼요. 각 주제의 실습 콘텐츠가 게시되면 스크립트가 여기에 추가돼요.

| # | 주제 | 상태 | 이 리포지토리의 스크립트 |
|---|-------|--------|----------------------|
| 1 | **엔드투엔드 디바이스 프로비저닝** — JITP/JITR, 클레임 기반 및 신뢰할 수 있는 사용자 기반 Fleet Provisioning, Multi-Account Registration | ✅ 사용 가능 | 예 — [사용 가능한 스크립트](#-사용-가능한-스크립트) 참조 |
| 2 | **플릿 작업 실행** — 플릿 전체에 대한 AWS IoT Jobs 및 AWS IoT Commands | 🚧 진행 중 | 예정 |
| 3 | **플릿 검색 및 분석** — Fleet Indexing, 집계, thing group | 🚧 진행 중 | 예정 |
| 4 | **소프트웨어 배포 / OTA** — Software Package Catalog, AWS IoT Jobs를 통한 버전 관리 배포, SBOM | 🚧 진행 중 | 예정 |
| 5 | **보안 원격 액세스** — AWS IoT Secure Tunneling 및 터널을 통한 SSH | 🚧 진행 중 | 예정 |
| 6 | **관찰성 및 문제 해결** — AWS IoT 로깅, Amazon CloudWatch, AWS CloudTrail | 🚧 진행 중 | 예정 |

> 이 README의 나머지 부분은 현재 스크립트가 제공되는 주제인 **주제 1 — 엔드투엔드 디바이스 프로비저닝**을 설명해요. 다른 주제가 게시되면 해당 스크립트(그리고 각 주제의 기본 인프라 및 비용 안내)가 같은 구조로 추가돼요.

## 👥 대상 독자

**주요 대상:** AWS IoT Core에서 대규모 디바이스 온보딩을 설계하는 IoT 개발자, 솔루션 아키텍트, DevOps 엔지니어

**사전 요구 사항:** 중급 수준의 AWS 지식, AWS IoT Core 기본 사항(인증서, 정책, MQTT), Python 기초, 명령줄 사용 경험

**학습 수준:** 고급 — 모든 프로비저닝 방법과 각 방법을 언제 사용하는지 살펴보는 실습 투어

## 🎯 디바이스 프로비저닝 — 학습 목표

주제 1을 마치면 다음을 할 수 있어요.

- **사용자 지정 CA + JITP**: 인증 기관을 등록하고, 내장된 프로비저닝 템플릿으로 첫 연결 시 디바이스를 자동으로 프로비저닝해요
- **JITR**: Lambda 핸들러와 국가 허용 목록 가이드라인을 사용해 `$aws/events/certificates/registered` 이벤트로 등록을 진행해요
- **클레임 기반 Fleet Provisioning**: 배치별로 공유되는 클레임 인증서(claim certificate)로 디바이스를 부트스트랩하고, 예약된 MQTT 토픽을 통해 영구 인증서로 교환해요
- **Pre-provisioning hook**: 허용/거부를 결정하고 `parameterOverrides`를 주입하는 동기식 Lambda로 `RegisterThing`을 통제해요
- **신뢰할 수 있는 사용자 기반 Fleet Provisioning**: 범위가 제한된 IAM ID(모바일 앱 모델)로 수명이 짧은 클레임을 발급하고 최소 권한 경계를 증명해요
- **Multi-Account Registration**: 같은 인증서를 재사용하는 엔드포인트 변경으로 디바이스를 다른 리전/계정으로 이동해요. 인증서를 다시 발급하지 않아요
- **인증서 수명 주기**: 인증서를 생성, 등록, 활성화/비활성화하고 정책을 연결/분리해요
- **리소스 정리**: 공유 환경은 그대로 두고, 이 주제에서 만든 리소스만 이름 패턴 범위로 정확히 제거해요

## 🧩 두 플레인 구성

고급 프로비저닝 주제는 **두 개의 플레인**으로 구성돼요.

- **컨트롤 플레인 — `boto3`** — 공유 `safe_api_call` 구성 요소를 통해 `aws iot ...` API로 디바이스를 관리해요(인증 기관 등록, 프로비저닝 템플릿, pre-provisioning hook, Multi-Account Registration 등).
- **디바이스 플레인 — `aws-iot-device-sdk-python-v2`** — 실제로 MQTT로 연결하는 시뮬레이션된 디바이스예요. `awscrt` / `awsiot` 패키지를 제공하며, JITP, Fleet Provisioning, 신뢰할 수 있는 사용자, Multi-Account Registration, 인증서 교체 흐름의 연결 단계에서 **MQTT 5** 연결 구성 요소(`awscrt.mqtt5` 위의 `awsiot.mqtt5_client_builder.mtls_from_path`)를 사용해요. MQTT 5는 의도적으로 선택한 거예요. 모든 확인 응답(acknowledgement)마다 **이유 코드**를 반환하므로, 디바이스가 권한 부여 실패(`NOT_AUTHORIZED`, 0x87 — 재시도해도 소용없음)와 일시적인 실패(`QUOTA_EXCEEDED`, 0x97 — 재시도하면 도움이 됨)를 구분할 수 있어요. MQTT 3.1.1은 PUBACK 패킷에 이유 코드 필드가 없기 때문에 게시에 대해서는 이를 전혀 표현할 수 없어요.

두 플레인 모두 `requirements.txt`에서 함께 설치돼요.

## 📋 사전 요구 사항

- 관리자 액세스 권한이 있는 **AWS 계정**(기본 인프라 스택이 이름이 지정된 IAM 역할을 생성해요)
- [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) 워크숍 수료(또는 동등한 경험)
- [AWS IoT Device Management - Learning Path - Basics](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) 워크숍 수료(또는 동등한 경험)
- X.509 인증서, 인증 기관(CA), 상호 TLS에 대한 탄탄한 이해
- 구성된 **AWS 자격 증명**(`aws configure`, 환경 변수 또는 IAM 역할)
- pip가 포함된 **Python 3.10+**
- PATH에 있는 **OpenSSL**(사용자 지정 CA 및 인증서 서명 요청 실습에 사용)
- 리포지토리를 클론하고 디바이스 플레인 SDK를 설치하기 위한 **Git**

## 💰 비용 분석 — 디바이스 프로비저닝 주제

**이 주제는 요금이 발생하는 실제 AWS 리소스를 생성해요. 전체 실행 시 예상되는 비용은 다음과 같아요.**

| 서비스 | 사용량 | 예상 비용(USD) |
|---------|-------|---------------------|
| **AWS IoT Core — 메시징** | 전체 흐름에서 수백 개의 MQTT 메시지 | $0.01 - $0.10 |
| **AWS IoT Core — 프로비저닝** | 인증서, thing, 프로비저닝 템플릿 등록 | $0.01 - $0.10 |
| **AWS Lambda** | JITR 핸들러 + pre-provisioning hook(수십 회 호출) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | 수명이 짧은 Lambda 로그 그룹 2개 | $0.00 - $0.05 |
| **AWS IoT Core — 두 번째 리전(MAR)** | 등록된 인증서 1개 + 메시지 몇 개 | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | 역할/정책 관리 | $0.00 |
| **총 예상 비용** | **모든 방법의 전체 실행** | **$0.03 - $0.35** |

**비용 관리:**
- ✅ 정리 스크립트가 이 주제에서 만든 모든 리소스를 제거해요(두 리전 모두)
- ✅ 수명이 짧은 소규모 데모 리소스
- ⚠️ **작업을 마치면 정리 스크립트를 실행하고 기본 인프라 스택도 삭제하는 것을 잊지 마세요**

**📊 비용 모니터링:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 빠른 시작

```bash
# 1. 클론 및 설정
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # Windows에서는: venv\Scripts\activate

# 2. 두 플레인 모두 설치(boto3 컨트롤 플레인 + aws-iot-device-sdk-python-v2 디바이스 플레인)
pip install -r requirements.txt

# 3. AWS 구성 및 OpenSSL 확인
aws configure
openssl version

# 4. 기본 인프라를 한 번만 배포(스크립트가 사용하는 IAM 역할 + Lambda 스켈레톤 생성)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. 방법 하나를 실행(예: 클레임 기반 Fleet Provisioning). 아래 "권장 워크플로"를 참조하세요.
```

## 🏗️ 기본 인프라 — 디바이스 프로비저닝(먼저 배포하세요)

스크립트 하나가 필요한 인프라를 모두 직접 만드는 *basics* 샘플과 달리, 고급 스크립트는 **미리 생성된 소수의 "기본" 리소스가 존재한다고 가정해요**(프로비저닝 중에 AWS IoT가 수임하는 역할, 그리고 Lambda 스켈레톤 2개와 해당 실행 역할). AWS 주도 이벤트에서는 이 스택이 미리 배포되어 있어요. **단독으로 실행할 때는** 이 리포지토리에 포함된 템플릿으로 **한 번 배포하세요**.

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

이 스택이 만드는 모든 리소스에는 모듈 접두사가 붙은 고정된 이름(`ws-aws-iot-dm-adv-prov-*`)이 있어서, 스크립트가 정확한 이름으로 리소스를 찾아요. 스택 출력을 따로 연결할 필요가 없어요. 스크립트에 필요한 값은 다음과 같이 직접 가져오세요.

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

이 스택은 **JITP 등록 역할**, **Fleet Provisioning 역할**, **신뢰할 수 있는 사용자 역할**(모바일 앱을 모델링하며, 여러분이 수임해요), **JITR 핸들러** Lambda + 역할, **pre-provisioning hook** Lambda + 역할, 그리고 해당 CloudWatch 로그 그룹을 만들어요. Lambda 스켈레톤은 핸들러 코드를 배포할 때까지 "not implemented"를 반환해요(JITR 및 hook 스크립트/단계에서 배포해요). 작업을 마치면 스택을 삭제하세요(정리 참조).

## 📚 사용 가능한 스크립트

다음은 **엔드투엔드 디바이스 프로비저닝** 스크립트(주제 1)예요. 다른 주제의 스크립트는 제공되는 대로 여기에 추가돼요.

| 스크립트 | 프로비저닝 방법 | 목적 |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP(섹션 2) | 내장 JITP 프로비저닝 템플릿 + 등록 구성 역할과 함께 사용자 지정 CA를 등록해요 |
| **manage_jit_provisioning.py** | JITP / JITR(섹션 2) | JITR 토픽 규칙을 관리하고, JITR 핸들러 코드를 배포하고, 프로비저닝된 thing을 관찰해요 |
| **fleet_provision_by_claim.py** | 클레임 기반 Fleet(섹션 3) | 클레임 인증서 + 범위가 제한된 정책을 만들고, 템플릿을 생성/버전 관리하고(hook 포함), 클레임→RegisterThing MQTT 교환을 실행하고 관찰해요 |
| **fleet_provision_trusted_user.py** | 신뢰할 수 있는 사용자 기반 Fleet(섹션 4) | 템플릿을 만들고, 신뢰할 수 있는 사용자로서 수명이 짧은 클레임을 발급하고, MQTT 교환을 실행하고 관찰해요 |
| **manage_multi_account_registration.py** | MAR(섹션 5) | CA 없이(또는 `SNI_ONLY`의 CA로) 인증서를 등록하고, 리전의 엔드포인트를 가져오고, 같은 인증서를 이동(다시 연결)해요 |
| **mqtt_connect.py** | 모든 섹션 | 최소한의 Device SDK v2 클라이언트예요. 연결하고(예상되는 첫 연결 끊김 시 재시도), 텔레메트리를 게시해요 |
| **rotate_certificate.py** | 인증서 교체(섹션 6) | 백엔드 주도 교체의 디바이스 측 절반이에요. 작업 실행을 받아 새 키 페어 + CSR을 로컬에서 생성하고, 서명된 인증서를 설치하고, 다시 연결한 다음, 성공을 보고하기 전에 권한이 부여된 게시를 증명해요(전환에 실패하면 이전 인증서로 롤백해요) |
| **certificate_manager.py** | 헬퍼 | 대화형 인증서 수명 주기: 인증서 생성/등록, 정책 연결/분리, 활성화/비활성화 |
| **cleanup_script.py** | 마무리(섹션 7) | 이 주제의 리소스만 이름 패턴으로 찾아 종속성 순서대로 두 리전 모두에서 제거해요 |

스크립트를 `-h` / `--help`와 함께 실행하면 하위 명령과 인수를 볼 수 있어요. 역할 또는 Lambda ARN을 받는 스크립트는 이를 인수로 받아요(예: `--provisioning-role-arn`, `--role-arn`, `--hook-arn`). 위에서 기본 스택으로부터 가져온 값을 넣어 주세요.

## 📖 권장 워크플로

스크립트는 워크숍의 모듈 순서를 그대로 따라요. 연습하고 싶은 방법을 고르세요. 기본 인프라를 배포하고 나면 각 방법은 독립적으로 실행할 수 있어요.

```bash
# --- 클레임 기반 Fleet Provisioning(섹션 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration(섹션 5) ---
PROD_REGION=us-west-2   # 두 번째 리전(AWS 주도 이벤트에서는 세션에 지정된 리전)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- 인증서 교체(섹션 6) ---
# 백엔드 주도 교체의 디바이스 측 절반이에요. --pause를 추가하면 관찰 가능한
# 각 단계(작업 IN_PROGRESS, 인증서 중첩, 폐기)에서 멈추므로, 계속하기 전에
# 콘솔이나 AWS CLI로 상태를 확인할 수 있어요.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- 정리(섹션 7) ---
python3 scripts/cleanup_script.py                      # 드라이 런(제거할 항목 나열)
python3 scripts/cleanup_script.py --execute            # 기본 리전
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # 두 번째 리전
```

## ⚙️ 구성

**환경 변수**(선택 사항):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # 기본 언어 설정(en, es, fr, ja, ko, pt, zh, de, it)
```

**스크립트 기능**: 네이티브 `boto3` 컨트롤 플레인, 재사용되는 Device SDK v2 MQTT 구성 요소, 영어 폴백이 있는 대화형 언어 선택, 대부분의 스크립트에서 API 호출/응답을 보여 주는 `--debug`, 안전한 정리를 위한 워크숍 리소스 태그 지정.

## 🌍 국제화

이 학습 경로는 9개의 워크숍 로캘을 대상으로 해요. 영어(`en`), 스페인어(`es`), 일본어(`ja`), 한국어(`ko`), 포르투갈어(`pt`), 중국어(`zh`), 독일어(`de`), 이탈리아어(`it`), 프랑스어(`fr`)예요. 스크립트 메시지는 현재 영어, 스페인어, 한국어, 일본어, 중국어 간체(`i18n/en/`, `i18n/es/`, `i18n/ko/`, `i18n/ja/`, `i18n/zh/`)로 제공되며, 다른 언어는 하나씩 추가돼요. 대화형 프롬프트를 건너뛰려면 `AWS_IOT_LANG`을 설정하세요. 번역이 없으면 스크립트는 메시지 단위로 영어로 폴백해요.

## 🧹 리소스 정리

**계속 요금이 발생하지 않도록 작업을 마치면 리소스를 정리하세요.** 정리 스크립트는 **기본적으로 아무것도 삭제하지 않으며**(드라이 런), 이 주제의 이름 패턴과 일치하는 리소스만 종속성 순서대로 제거해요.

```bash
# 미리 보기(아무것도 삭제하지 않음)
python3 scripts/cleanup_script.py

# 기본 리전에서 삭제(CA, 템플릿, 인증서를 삭제하기 전에 확인을 위해 일시 중지)
python3 scripts/cleanup_script.py --execute

# Multi-Account Registration에서 사용한 두 번째 리전 삭제
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# 마지막으로 기본 인프라 스택 제거(역할, Lambda, 로그 그룹)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ 문제 해결

- **자격 증명 / 리전**: `aws configure`, 환경 변수 또는 IAM 역할로 구성하세요. MAR 명령에는 `--region`에 유효한 두 번째 리전이 필요해요.
- **"Stack ... does not exist" 또는 역할/함수를 찾을 수 없음**: 방법별 스크립트를 실행하기 전에 기본 인프라 스택을 배포하세요(위 참조).
- **IAM/Lambda에서 `AccessDenied`**: 기본 스택에는 `CAPABILITY_NAMED_IAM`이 필요하고, 실행하는 ID에는 역할을 만들고 이를 `iot.amazonaws.com` / `lambda.amazonaws.com`에 전달할 권한이 필요해요.
- **인증서가 `PENDING_ACTIVATION` 상태에서 멈춤**: 프로비저닝 템플릿/등록 역할이 실패한 거예요. CloudTrail에서 거부된 작업을 확인하세요(워크숍 콘텐츠의 JITP 섹션에 전체 런북이 있어요).
- **디버그 모드**: `--debug`를 전달하거나 디버그 프롬프트에 응답하면 모든 API 호출과 응답이 출력돼요.

## 📁 프로젝트 구조

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # 기본 인프라: IAM 역할 + Lambda 스켈레톤(한 번 배포)
├── scripts/                              # 사용자가 실행하는 스크립트
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # 내부 헬퍼 패키지
│   └── utils/                            # 컨트롤 플레인 + 디바이스 플레인 구성 요소
│       ├── api_helpers.py                # safe_api_call 래퍼
│       ├── device_simulator.py           # DeviceConnection MQTT 구성 요소
│       └── fleet_provisioning_templates/ # 프로비저닝 템플릿 + 정책 JSON
├── lambdas/                              # 스켈레톤에 배포되는 Lambda 코드
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # 섹션 6 — CSR을 검증하고 서명하며, 이전 인증서를 폐기
│   └── rotation_enroller.py               # 섹션 6 — 참고용이며 배포하지 않음:
│                                          #   Device Defender 수명 결과(finding)를 교체 등록으로 변환
├── i18n/                                 # 국제화(메시지 카탈로그 + 로더)
├── requirements.txt                      # Python 종속성(두 플레인 모두)
└── README.md
```

## 📄 라이선스

MIT No Attribution License.

## 🏷️ 태그

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
