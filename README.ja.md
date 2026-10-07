# AWS IoT Device Management - 学習パス - 上級

> **⚠️ 免責事項:** このサンプルはデモと学習のみを目的として提供しています。追加のセキュリティレビューとテストを行わずに本番環境で使うことは想定していません。

AWS IoT Device Management の上級学習パス用のサンプルコードです。Workshop Studio のワークショップ [**AWS IoT Device Management - 学習パス - 上級**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (そのすべてのテーマ) と組み合わせて使います。学習パスごとに 1 つのリポジトリという方針で、[`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) と [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics) の兄弟リポジトリにあたります。

このリポジトリは**上級学習パス全体**のサンプルコードです。上級学習パスは、それぞれ独立した AWS IoT Device Management のテーマ (デバイスプロビジョニング、フリートタスクの実行、フリートの検索と分析、ソフトウェア配信 / OTA、セキュアなリモートアクセス、オブザーバビリティ) で構成されています。スクリプトは **boto3 のコントロールプレーン**と **AWS IoT Device SDK for Python v2 のデバイスプレーン**を組み合わせているので、クラウド側のリソースを作成することと、シミュレートしたデバイスを MQTT で接続することの両方を体験できます。各テーマのスクリプトは、そのテーマのワークショップコンテンツが公開された時点でこのリポジトリに追加されます。

## 🌍 利用可能な言語

| 言語 | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |
| 🇮🇹 Italiano | [README.it.md](README.it.md) |
| 🇧🇷 Português (Brasil) | [README.pt.md](README.pt.md) |

スクリプト自体もローカライズされています。`AWS_IOT_LANG` (`en`、`es`、`ja`、`ko`、`pt`、`zh`、`de`、`it`、`fr`) を設定するか、初回実行時に対話形式で言語を選んでください。スクリプトのメッセージは現在、英語、スペイン語、韓国語、日本語、簡体字中国語、イタリア語、ブラジルポルトガル語で利用できます。まだ翻訳されていないメッセージは英語にフォールバックします。

## 🎯 この学習パスのテーマ

各テーマは独立しているので、順番に進めても、必要なテーマだけを選んでもかまいません。スクリプトは、各テーマのハンズオンコンテンツが公開された時点でここに追加されます。

| # | テーマ | ステータス | このリポジトリのスクリプト |
|---|-------|--------|----------------------|
| 1 | **エンドツーエンドのデバイスプロビジョニング**: JITP/JITR、クレームによる Fleet Provisioning と信頼できるユーザーによる Fleet Provisioning、Multi-Account Registration | ✅ 利用可能 | あり。[利用可能なスクリプト](#-利用可能なスクリプト)を参照 |
| 2 | **フリートタスクの実行**: フリート全体での AWS IoT Jobs と AWS IoT Commands | 🚧 作成中 | 予定 |
| 3 | **フリートの検索と分析**: Fleet Indexing、集計、thing group | 🚧 作成中 | 予定 |
| 4 | **ソフトウェア配信 / OTA**: Software Package Catalog、AWS IoT Jobs によるバージョン管理されたデプロイ、SBOM | 🚧 作成中 | 予定 |
| 5 | **セキュアなリモートアクセス**: AWS IoT Secure Tunneling とトンネル経由の SSH | 🚧 作成中 | 予定 |
| 6 | **オブザーバビリティとトラブルシューティング**: AWS IoT のロギング、Amazon CloudWatch、AWS CloudTrail | 🚧 作成中 | 予定 |

> この README の残りの部分では、現在スクリプトを提供している**テーマ 1: エンドツーエンドのデバイスプロビジョニング**について説明します。ほかのテーマが公開されると、そのスクリプト (と、それぞれのベースインフラストラクチャやコストに関する注記) が同じ構成で追加されます。

## 👥 対象者

**主な対象者:** AWS IoT Core で大規模なデバイスオンボーディングを設計する IoT 開発者、ソリューションアーキテクト、DevOps エンジニア

**前提条件:** AWS の中級レベルの知識、AWS IoT Core の基礎 (証明書、ポリシー、MQTT)、Python の基礎、コマンドラインの使い方

**学習レベル:** 上級。すべてのプロビジョニング方式と、それぞれをいつ使うべきかを実際に手を動かしながら一通り学びます

## 🎯 デバイスプロビジョニング: 学習目標

テーマ 1 を終えると、次のことができるようになります。

- **カスタム CA + JITP**: 認証局を登録し、埋め込みのプロビジョニングテンプレートを使って、初回接続時にデバイスを自動でプロビジョニングする
- **JITR**: Lambda ハンドラーと国の許可リストによるガードレールを使って、`$aws/events/certificates/registered` イベントから登録を実行する
- **クレームによる Fleet Provisioning**: バッチ単位で共有するクレーム証明書でデバイスをブートストラップし、予約済みの MQTT トピック経由で永続的な証明書と交換する
- **Pre-provisioning hook**: 許可/拒否を判断して `parameterOverrides` を挿入する同期型の Lambda で `RegisterThing` をゲートする
- **信頼できるユーザーによる Fleet Provisioning**: スコープを絞った IAM ID (モバイルアプリのモデル) として有効期間の短いクレームを発行し、最小権限の境界を確かめる
- **Multi-Account Registration**: 同じ証明書を再利用したエンドポイントの変更として、デバイスを別のリージョン/アカウントに移動する (証明書の再発行は不要)
- **証明書のライフサイクル**: 証明書の作成、登録、有効化/無効化、ポリシーのアタッチ/デタッチ
- **リソースのクリーンアップ**: このテーマで作成したものだけをパターンで絞り込んで削除し、共通の環境はそのまま残す

## 🧩 2 つのプレーンの構成

上級のプロビジョニングテーマは **2 つのプレーン**で構成されています。

- **コントロールプレーン: `boto3`**。共通の `safe_api_call` コンストラクトを通じて、`aws iot ...` API でデバイスを管理します (認証局、プロビジョニングテンプレート、pre-provisioning hook の登録、Multi-Account Registration など)。
- **デバイスプレーン: `aws-iot-device-sdk-python-v2`**。実際に MQTT で接続する、シミュレートしたデバイスです。`awscrt` / `awsiot` パッケージを提供し、JITP、Fleet Provisioning、信頼できるユーザー、Multi-Account Registration、証明書のローテーションの各フローの接続ステップで **MQTT 5** の接続コンストラクト (`awscrt.mqtt5` 上の `awsiot.mqtt5_client_builder.mtls_from_path`) を使います。MQTT 5 を使うのには理由があります。すべての確認応答で**理由コード**が返るので、デバイスは認可の失敗 (`NOT_AUTHORIZED`、0x87。再試行しても解決しません) と一時的な失敗 (`QUOTA_EXCEEDED`、0x97。再試行で解決します) を区別できます。MQTT 3.1.1 の PUBACK パケットには理由コードのフィールドがないので、パブリッシュについてはこれをまったく表現できません。

どちらのプレーンも `requirements.txt` からまとめてインストールされます。

## 📋 前提条件

- 管理者アクセス権限のある **AWS アカウント** (ベースインフラストラクチャのスタックが名前付きの IAM ロールを作成します)
- [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) ワークショップの修了 (または同等の経験)
- [AWS IoT Device Management - Learning Path - Basics](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) ワークショップの修了 (または同等の経験)
- X.509 証明書、認証局 (CA)、相互 TLS についての十分な理解
- 設定済みの **AWS 認証情報** (`aws configure`、環境変数、または IAM ロール)
- pip が使える **Python 3.10 以降**
- PATH 上の **OpenSSL** (カスタム CA と証明書署名リクエストの演習で使います)
- リポジトリのクローンとデバイスプレーン SDK のインストールに使う **Git**

## 💰 コスト分析: デバイスプロビジョニングのテーマ

**このテーマでは実際の AWS リソースを作成するので、料金が発生します。一通り実行した場合の目安は次のとおりです。**

| サービス | 使用量 | 推定コスト (USD) |
|---------|-------|---------------------|
| **AWS IoT Core: メッセージング** | 各フロー全体で数百件の MQTT メッセージ | $0.01 - $0.10 |
| **AWS IoT Core: プロビジョニング** | 証明書、thing、プロビジョニングテンプレートの登録 | $0.01 - $0.10 |
| **AWS Lambda** | JITR ハンドラー + pre-provisioning hook (数十回の呼び出し) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | 短期間だけ使う Lambda のロググループ 2 つ | $0.00 - $0.05 |
| **AWS IoT Core: 2 番目のリージョン (MAR)** | 登録した証明書 1 つ + 数件のメッセージ | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | ロール/ポリシーの管理 | $0.00 |
| **推定合計** | **すべての方式を一通り実行** | **$0.03 - $0.35** |

**コスト管理:**
- ✅ クリーンアップスクリプトは、このテーマで作成したものをすべて削除します (両方のリージョン)
- ✅ 短期間だけ使う、小規模なデモ用リソースです
- ⚠️ **終わったら、クリーンアップスクリプトを実行し、ベースインフラストラクチャのスタックも削除するのを忘れないでください**

**📊 コストの監視:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 クイックスタート

```bash
# 1. クローンしてセットアップする
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # Windows の場合: venv\Scripts\activate

# 2. 両方のプレーンをインストールする (boto3 のコントロールプレーン + aws-iot-device-sdk-python-v2 のデバイスプレーン)
pip install -r requirements.txt

# 3. AWS を設定し、OpenSSL を確認する
aws configure
openssl version

# 4. ベースインフラストラクチャを 1 回だけデプロイする (スクリプトが使う IAM ロールと Lambda スケルトンを作成)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. 方式を 1 つ実行する (例: クレームによる Fleet Provisioning)。下の「推奨ワークフロー」を参照してください。
```

## 🏗️ ベースインフラストラクチャ: デバイスプロビジョニング (最初にデプロイ)

*basics* のサンプルでは 1 つのスクリプトが自分のインフラストラクチャをすべて作成しますが、上級のスクリプトは**事前に作成された少数の「ベース」リソースがあることを前提にしています** (プロビジョニング中に AWS IoT が引き受けるロールと、2 つの Lambda スケルトンとその実行ロール)。AWS 主催イベントではこのスタックはデプロイ済みです。**単独で実行する場合は**、このリポジトリに同梱のテンプレートで **1 回だけデプロイします**。

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

作成されるリソースにはすべて、モジュールのプレフィックスが付いた固定の名前 (`ws-aws-iot-dm-adv-prov-*`) があるので、スクリプトは正確な名前でリソースを特定します。スタック出力を受け渡す仕組みは必要ありません。スクリプトが必要とする値を直接取得してください。

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

このスタックが作成するのは、**JITP 登録ロール**、**Fleet Provisioning ロール**、**信頼できるユーザーのロール** (モバイルアプリをモデル化したもので、これを引き受けます)、**JITR ハンドラー**の Lambda + ロール、**pre-provisioning hook** の Lambda + ロール、そしてそれらの CloudWatch ロググループです。Lambda スケルトンは、ハンドラーのコードをデプロイするまで「not implemented」を返します (JITR と hook のスクリプト/ステップでデプロイします)。終わったらスタックを削除してください (「クリーンアップ」を参照)。

## 📚 利用可能なスクリプト

ここにあるのは**エンドツーエンドのデバイスプロビジョニング** (テーマ 1) のスクリプトです。ほかのテーマのスクリプトは、提供され次第ここに追加されます。

| スクリプト | プロビジョニング方式 | 目的 |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (セクション 2) | 埋め込みの JITP プロビジョニングテンプレートと登録設定ロールを指定して、カスタム CA を登録する |
| **manage_jit_provisioning.py** | JITP / JITR (セクション 2) | JITR トピックルールを管理し、JITR ハンドラーのコードをデプロイして、プロビジョニングされた thing を確認する |
| **fleet_provision_by_claim.py** | クレームによるフリート (セクション 3) | クレーム証明書とスコープを絞ったポリシーを作成し、テンプレートを作成/バージョン管理し (hook 付き)、クレーム→RegisterThing の MQTT のやり取りを実行して確認する |
| **fleet_provision_trusted_user.py** | 信頼できるユーザーによるフリート (セクション 4) | テンプレートを作成し、信頼できるユーザーとして有効期間の短いクレームを発行し、MQTT のやり取りを実行して確認する |
| **manage_multi_account_registration.py** | MAR (セクション 5) | CA なしで証明書を登録し (または `SNI_ONLY` で CA を登録し)、リージョンのエンドポイントを取得して、同じ証明書を移動 (再接続) する |
| **mqtt_connect.py** | すべてのセクション | 最小構成の Device SDK v2 クライアント。接続し (想定どおりの初回接続の切断は再試行します)、テレメトリをパブリッシュする |
| **rotate_certificate.py** | 証明書のローテーション (セクション 6) | バックエンド主導のローテーションのデバイス側。ジョブ実行を取得し、新しいキーペアと CSR をローカルで生成し、署名済み証明書をインストールして再接続し、成功を報告する前に認可されたパブリッシュを確かめる (切り替えに失敗した場合は古い証明書にロールバックする) |
| **certificate_manager.py** | ヘルパー | 対話型の証明書ライフサイクル管理: 証明書の作成/登録、ポリシーのアタッチ/デタッチ、有効化/無効化 |
| **cleanup_script.py** | まとめ (セクション 7) | このテーマのリソースだけを命名パターンで特定し、依存関係の順に、両方のリージョンから削除する |

どのスクリプトも `-h` / `--help` を付けて実行すると、サブコマンドと引数を確認できます。ロールや Lambda の ARN を受け取るスクリプトは、それを引数として受け取ります (例: `--provisioning-role-arn`、`--role-arn`、`--hook-arn`)。上でベーススタックから取得した値を渡してください。

## 📖 推奨ワークフロー

スクリプトはワークショップのモジュールの順序に沿っています。練習したい方式を選んでください。ベースインフラストラクチャをデプロイすれば、各方式は単独で進められます。

```bash
# --- クレームによる Fleet Provisioning (セクション 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (セクション 5) ---
PROD_REGION=us-west-2   # 2 番目のリージョン (AWS 主催イベントでは、セッションで指定されたリージョン)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- 証明書のローテーション (セクション 6) ---
# バックエンド主導のローテーションのデバイス側です。--pause を付けると、観察できる
# 各ステップ (ジョブの IN_PROGRESS、証明書の重複、廃止) で停止するので、続行する前に
# コンソールや AWS CLI で状態を確認できます。
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- クリーンアップ (セクション 7) ---
python3 scripts/cleanup_script.py                      # ドライラン (削除される対象を一覧表示)
python3 scripts/cleanup_script.py --execute            # メインのリージョン
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # 2 番目のリージョン
```

## ⚙️ 設定

**環境変数** (オプション):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # デフォルトの言語を設定 (en, es, fr, ja, ko, pt, zh, de, it)
```

**スクリプトの機能**: ネイティブの `boto3` コントロールプレーン、再利用している Device SDK v2 の MQTT コンストラクト、英語へのフォールバック付きの対話型言語選択、API の呼び出し/レスポンスを表示する `--debug` (ほとんどのスクリプトで利用可能)、安全にクリーンアップするためのワークショップリソースのタグ付け。

## 🌍 国際化

この学習パスは、ワークショップの 9 つのロケールを対象にしています: 英語 (`en`)、スペイン語 (`es`)、日本語 (`ja`)、韓国語 (`ko`)、ポルトガル語 (`pt`)、中国語 (`zh`)、ドイツ語 (`de`)、イタリア語 (`it`)、フランス語 (`fr`)。スクリプトのメッセージは現在、英語、スペイン語、韓国語、日本語、簡体字中国語、イタリア語、ブラジルポルトガル語 (`i18n/en/`、`i18n/es/`、`i18n/ko/`、`i18n/ja/`、`i18n/zh/`、`i18n/it/`、`i18n/pt/`) で提供しています。ほかの言語は 1 つずつ追加していきます。`AWS_IOT_LANG` を設定すると対話形式のプロンプトをスキップできます。翻訳がない場合、スクリプトはメッセージ単位で英語にフォールバックします。

## 🧹 リソースのクリーンアップ

**継続的な料金が発生しないように、終わったら忘れずにクリーンアップしてください。** クリーンアップスクリプトは**デフォルトでは非破壊** (ドライラン) で、このテーマの命名パターンに一致するリソースだけを、依存関係の順に削除します。

```bash
# プレビュー (何も削除しない)
python3 scripts/cleanup_script.py

# メインのリージョンで削除する (CA、テンプレート、証明書を削除する前に確認のため一時停止)
python3 scripts/cleanup_script.py --execute

# Multi-Account Registration で使った 2 番目のリージョンで削除する
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# 最後に、ベースインフラストラクチャのスタック (ロール、Lambda、ロググループ) を削除する
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ トラブルシューティング

- **認証情報 / リージョン**: `aws configure`、環境変数、または IAM ロールで設定します。MAR のコマンドには、`--region` に有効な 2 番目のリージョンを指定する必要があります。
- **「Stack ... does not exist」やロール/関数が見つからない**: 各方式のスクリプトを実行する前に、ベースインフラストラクチャのスタックをデプロイしてください (上記を参照)。
- **IAM/Lambda での `AccessDenied`**: ベーススタックには `CAPABILITY_NAMED_IAM` が必要です。実行する ID には、ロールを作成して `iot.amazonaws.com` / `lambda.amazonaws.com` に渡すアクセス許可が必要です。
- **証明書が `PENDING_ACTIVATION` のまま**: プロビジョニングテンプレート/登録ロールが失敗しています。拒否されたアクションを CloudTrail で確認してください (ワークショップコンテンツの JITP セクションに詳しいランブックがあります)。
- **デバッグモード**: `--debug` を付ける (またはデバッグのプロンプトに答える) と、すべての API 呼び出しとレスポンスが表示されます。

## 📁 プロジェクト構成

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # ベースインフラ: IAM ロール + Lambda スケルトン (1 回だけデプロイ)
├── scripts/                              # ユーザーが実行するスクリプト
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # 内部ヘルパーパッケージ
│   └── utils/                            # コントロールプレーン + デバイスプレーンのコンストラクト
│       ├── api_helpers.py                # safe_api_call ラッパー
│       ├── device_simulator.py           # DeviceConnection MQTT コンストラクト
│       └── fleet_provisioning_templates/ # プロビジョニングテンプレート + ポリシー JSON
├── lambdas/                              # スケルトンにデプロイする Lambda コード
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # セクション 6: CSR をゲートして署名し、古い証明書を廃止
│   └── rotation_enroller.py               # セクション 6: 参考用でデプロイしない。Device Defender の
│                                          #   経過期間の検出結果をローテーション登録に変換
├── i18n/                                 # 国際化 (メッセージカタログ + ローダー)
├── requirements.txt                      # Python の依存関係 (両方のプレーン)
└── README.md
```

## 📄 ライセンス

MIT No Attribution License.

## 🏷️ タグ

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
