# AWS IoT Device Management - Learning Path - Advanced

> **⚠️ Aviso de isenção de responsabilidade:** este exemplo é fornecido apenas para fins de demonstração e educacionais e não se destina ao uso em produção sem revisão de segurança e testes adicionais.

Código de exemplo para o learning path avançado do AWS IoT Device Management. Ele acompanha o workshop do Workshop Studio [**AWS IoT Device Management - Learning Path - Advanced**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (todos os seus temas) e, no modelo de um repositório por learning path, é o repositório irmão de [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) e [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics).

É o código de exemplo que acompanha **todo o learning path avançado**: um conjunto de temas independentes do AWS IoT Device Management (provisionamento de dispositivos, execução de tarefas na frota, busca e análise da frota, entrega de software / OTA, acesso remoto seguro e observabilidade). Os scripts combinam um **plano de controle com boto3** e um **plano do dispositivo com o AWS IoT Device SDK for Python v2**, para que você crie os recursos do lado da nuvem e também conecte um dispositivo simulado via MQTT. Os scripts de cada tema chegam a este repositório à medida que o conteúdo do workshop desse tema é publicado.

## 🌍 Idiomas disponíveis

| Idioma | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |
| 🇮🇹 Italiano | [README.it.md](README.it.md) |
| 🇧🇷 Português (Brasil) | [README.pt.md](README.pt.md) |

Os próprios scripts são localizados: defina `AWS_IOT_LANG` (`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`) ou escolha um idioma de forma interativa na primeira execução. No momento, as mensagens dos scripts estão disponíveis em inglês, espanhol, coreano, japonês, chinês simplificado, italiano e português (Brasil); qualquer mensagem ainda não traduzida usa o inglês como fallback.

## 🎯 Temas deste learning path

Cada tema é independente: execute-os em ordem ou escolha os que você precisa. Os scripts são adicionados aqui à medida que o conteúdo prático de cada tema é publicado.

| # | Tema | Status | Scripts neste repositório |
|---|-------|--------|----------------------|
| 1 | **Provisionamento de dispositivos de ponta a ponta**: JITP/JITR, Fleet Provisioning por claim e por usuário confiável, Multi-Account Registration | ✅ Disponível | Sim, veja [Scripts disponíveis](#-scripts-disponíveis) |
| 2 | **Fleet Task Execution**: AWS IoT Jobs e AWS IoT Commands em toda a frota | 🚧 Em andamento | Planejado |
| 3 | **Fleet Search & Analytics**: Fleet Indexing, agregações, thing groups | 🚧 Em andamento | Planejado |
| 4 | **Software Delivery / OTA**: Software Package Catalog, implantações versionadas via AWS IoT Jobs, SBOM | 🚧 Em andamento | Planejado |
| 5 | **Secure Remote Access**: AWS IoT Secure Tunneling e SSH por um túnel | 🚧 Em andamento | Planejado |
| 6 | **Observability & Troubleshooting**: logging do AWS IoT, Amazon CloudWatch, AWS CloudTrail | 🚧 Em andamento | Planejado |

> O restante deste README documenta o **Tema 1: Provisionamento de dispositivos de ponta a ponta**, o tema cujos scripts já estão disponíveis hoje. À medida que os outros temas forem publicados, os scripts deles (com suas próprias observações sobre infraestrutura base e custos) serão adicionados na mesma estrutura.

## 👥 Público-alvo

**Público principal:** desenvolvedores de IoT, arquitetos de soluções e engenheiros de DevOps que projetam o onboarding de dispositivos em escala no AWS IoT Core

**Pré-requisitos:** conhecimento intermediário de AWS, fundamentos do AWS IoT Core (certificados, políticas, MQTT), fundamentos de Python e uso da linha de comando

**Nível de aprendizagem:** avançado, um percurso prático por todos os métodos de provisionamento e quando usar cada um

## 🎯 Provisionamento de dispositivos: objetivos de aprendizagem

Ao final do Tema 1, você será capaz de:

- **CA personalizada + JITP**: registrar uma autoridade de certificação e provisionar dispositivos automaticamente na primeira conexão com um template de provisionamento incorporado
- **JITR**: conduzir o registro a partir do evento `$aws/events/certificates/registered` com um handler Lambda e uma diretriz baseada em uma lista de permissões (allow-list) de países
- **Fleet Provisioning por claim**: inicializar dispositivos com um certificado de claim (claim certificate) compartilhado por lote, trocado por um certificado permanente por meio de tópicos MQTT reservados
- **Pre-provisioning hook**: controlar o `RegisterThing` com uma Lambda síncrona que permite/nega e injeta `parameterOverrides`
- **Fleet Provisioning por usuário confiável**: gerar um claim de curta duração como uma identidade do IAM com escopo restrito (o modelo do aplicativo móvel) e comprovar o limite de privilégio mínimo
- **Multi-Account Registration**: mover um dispositivo para outra região/conta como uma mudança de endpoint reutilizando o mesmo certificado, sem emitir um novo
- **Ciclo de vida dos certificados**: criar, registrar, ativar/desativar, anexar/desanexar políticas
- **Limpeza de recursos**: remover exatamente o que o tema criou, filtrando por padrão de nomenclatura, mantendo intacto o ambiente compartilhado

## 🧩 Composição em dois planos

O tema de provisionamento avançado combina **dois planos**:

- **Plano de controle: `boto3`**: gerenciamento de dispositivos pelas APIs `aws iot ...` (registro de autoridades de certificação, templates de provisionamento, pre-provisioning hooks, Multi-Account Registration e assim por diante), por meio do construto compartilhado `safe_api_call`.
- **Plano do dispositivo: `aws-iot-device-sdk-python-v2`**: um dispositivo simulado que de fato se conecta via MQTT. Ele fornece os pacotes `awscrt` / `awsiot` e usa o construto de conexão **MQTT 5** (`awsiot.mqtt5_client_builder.mtls_from_path` sobre `awscrt.mqtt5`) nas etapas de conexão dos fluxos de JITP, Fleet Provisioning, usuário confiável, Multi-Account Registration e rotação de certificados. A escolha do MQTT 5 é proposital: ele retorna um **código de motivo (reason code)** em cada confirmação, então o dispositivo consegue diferenciar uma falha de autorização (`NOT_AUTHORIZED`, 0x87: tentar novamente não vai ajudar) de uma falha transitória (`QUOTA_EXCEEDED`, 0x97: tentar novamente vai ajudar). O MQTT 3.1.1 simplesmente não consegue expressar isso para uma publicação, porque o pacote PUBACK dele não tem campo de código de motivo.

Os dois planos são instalados juntos a partir de `requirements.txt`.

## 📋 Pré-requisitos

- **Conta AWS** com acesso administrativo (o stack da infraestrutura base cria funções do IAM com nome fixo)
- Conclusão do workshop [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) (ou experiência equivalente)
- Conclusão do workshop [AWS IoT Device Management - Learning Path - Basic](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) (ou experiência equivalente)
- Boa compreensão de certificados X.509, autoridades de certificação (CAs) e TLS mútuo
- **Credenciais AWS** configuradas (`aws configure`, variáveis de ambiente ou funções do IAM)
- **Python 3.10+** com pip
- **OpenSSL** no PATH (usado nos exercícios de CA personalizada e de solicitação de assinatura de certificado)
- **Git** para clonar o repositório e instalar o SDK do plano do dispositivo

## 💰 Análise de custos: tema Provisionamento de dispositivos

**Este tema cria recursos reais da AWS que vão gerar cobranças. Veja o que esperar de uma execução completa:**

| Serviço | Uso | Custo estimado (USD) |
|---------|-------|---------------------|
| **AWS IoT Core: mensagens** | Algumas centenas de mensagens MQTT em todos os fluxos | $0.01 - $0.10 |
| **AWS IoT Core: provisionamento** | Certificados, things, registros de templates de provisionamento | $0.01 - $0.10 |
| **AWS Lambda** | Handler do JITR + pre-provisioning hook (dezenas de invocações) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | Dois grupos de logs Lambda de curta duração | $0.00 - $0.05 |
| **AWS IoT Core: segunda região (MAR)** | Um certificado registrado + algumas mensagens | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | Gerenciamento de funções/políticas | $0.00 |
| **Total estimado** | **Execução completa de todos os métodos** | **$0.03 - $0.35** |

**Gerenciamento de custos:**
- ✅ O script de limpeza remove tudo o que este tema cria (nas duas regiões)
- ✅ Recursos de demonstração de curta duração e em pequena escala
- ⚠️ **Lembre-se de executar o script de limpeza e excluir o stack da infraestrutura base quando terminar**

**📊 Monitore os custos:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 Início rápido

```bash
# 1. Clone e configure
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# 2. Instale OS DOIS planos (plano de controle boto3 + plano do dispositivo aws-iot-device-sdk-python-v2)
pip install -r requirements.txt

# 3. Configure a AWS e confirme o OpenSSL
aws configure
openssl version

# 4. Implante a infraestrutura base UMA VEZ (cria as funções do IAM + os esqueletos Lambda que os scripts usam)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. Execute um método (exemplo: Fleet Provisioning por claim). Veja "Fluxo de trabalho recomendado" abaixo.
```

## 🏗️ Infraestrutura base: Provisionamento de dispositivos (implante primeiro)

Ao contrário do exemplo *basics*, em que um único script cria toda a própria infraestrutura, os scripts avançados **pressupõem que já existe um pequeno conjunto de recursos "base" criados previamente** (as funções que o AWS IoT assume durante o provisionamento, mais dois esqueletos Lambda e suas funções de execução). Em um evento conduzido pela AWS, este stack já está implantado para você; **se você estiver trabalhando por conta própria, implante-o uma vez** com o template incluído neste repositório:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

Cada recurso que ele cria tem um nome fixo com o prefixo do módulo (`ws-aws-iot-dm-adv-prov-*`), então os scripts os encontram pelo nome exato, sem depender dos outputs do stack. Capture diretamente os valores de que os scripts precisam:

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

O stack cria: a **função de registro do JITP**, a **função de Fleet Provisioning**, a **função do usuário confiável** (modela o aplicativo móvel; é você quem a assume), a Lambda do **handler do JITR** + sua função, a Lambda do **pre-provisioning hook** + sua função, e os respectivos grupos de logs do CloudWatch. Os esqueletos Lambda retornam "not implemented" até você implantar o código do handler (os scripts/etapas do JITR e do hook fazem isso). Exclua o stack quando terminar (veja Limpeza).

## 📚 Scripts disponíveis

Estes são os scripts de **Provisionamento de dispositivos de ponta a ponta** (Tema 1). Os scripts dos outros temas serão listados aqui à medida que forem disponibilizados.

| Script | Método de provisionamento | Finalidade |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (Seção 2) | Registra uma CA personalizada com um template de provisionamento JITP incorporado + a função da configuração de registro |
| **manage_jit_provisioning.py** | JITP / JITR (Seção 2) | Gerencia a regra de tópico (topic rule) do JITR, implanta o código do handler do JITR e observa os things provisionados |
| **fleet_provision_by_claim.py** | Fleet por claim (Seção 3) | Cria o certificado de claim + a política com escopo restrito, cria/versiona o template (com hook), executa a troca de mensagens MQTT claim→RegisterThing e observa |
| **fleet_provision_trusted_user.py** | Fleet por usuário confiável (Seção 4) | Cria o template, gera um claim de curta duração como o usuário confiável, executa a troca de mensagens MQTT e observa |
| **manage_multi_account_registration.py** | MAR (Seção 5) | Registra um certificado sem CA (ou uma CA em `SNI_ONLY`), obtém o endpoint de uma região e move (reconecta) o mesmo certificado |
| **mqtt_connect.py** | Todas as seções | Cliente mínimo do Device SDK v2: conecta-se (tentando novamente após a desconexão esperada na primeira conexão) e publica telemetria |
| **rotate_certificate.py** | Rotação de certificados (Seção 6) | Parte do dispositivo em uma rotação conduzida pelo backend: assume a execução do job, gera localmente um novo par de chaves + CSR, instala o certificado assinado, reconecta-se e comprova uma publicação autorizada antes de reportar sucesso (reverte para o certificado antigo se a troca falhar) |
| **certificate_manager.py** | Helper | Ciclo de vida interativo dos certificados: criar/registrar certificados, anexar/desanexar políticas, ativar/desativar |
| **cleanup_script.py** | Encerramento (Seção 7) | Remove apenas os recursos deste tema pelo padrão de nomenclatura, em ordem de dependência, nas duas regiões |

Execute qualquer script com `-h` / `--help` para ver os subcomandos e argumentos dele. Os scripts que recebem o ARN de uma função ou de uma Lambda aceitam esse valor como argumento (por exemplo, `--provisioning-role-arn`, `--role-arn`, `--hook-arn`): informe os valores capturados do stack base acima.

## 📖 Fluxo de trabalho recomendado

Os scripts seguem a ordem dos módulos do workshop. Escolha o método ou os métodos que você quer praticar: cada um é independente depois que a infraestrutura base estiver implantada.

```bash
# --- Fleet Provisioning por claim (Seção 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (Seção 5) ---
PROD_REGION=us-west-2   # sua segunda região (em um evento conduzido pela AWS, a região indicada na sua sessão)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- Rotação de certificados (Seção 6) ---
# Parte do dispositivo em uma rotação conduzida pelo backend. Adicione --pause para parar em cada
# etapa observável (job IN_PROGRESS, a sobreposição de certificados, a retirada)
# e assim inspecionar o estado no console ou com a AWS CLI antes de continuar.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- Limpeza (Seção 7) ---
python3 scripts/cleanup_script.py                      # simulação (dry run): lista o que seria removido
python3 scripts/cleanup_script.py --execute            # região principal
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # segunda região
```

## ⚙️ Configuração

**Variáveis de ambiente** (opcionais):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Define o idioma padrão (en, es, fr, ja, ko, pt, zh, de, it)
```

**Recursos dos scripts**: plano de controle nativo com `boto3`; construto MQTT do Device SDK v2 reutilizado; seleção interativa de idioma com o inglês como fallback; `--debug` na maioria dos scripts para mostrar chamadas/respostas das APIs; marcação (tagging) dos recursos do workshop para uma limpeza segura.

## 🌍 Internacionalização

Este learning path atende aos 9 idiomas do workshop: inglês (`en`), espanhol (`es`), japonês (`ja`), coreano (`ko`), português (`pt`), chinês (`zh`), alemão (`de`), italiano (`it`) e francês (`fr`). Hoje, as mensagens dos scripts estão disponíveis em inglês, espanhol, coreano, japonês, chinês simplificado, italiano e português (Brasil) (`i18n/en/`, `i18n/es/`, `i18n/ko/`, `i18n/ja/`, `i18n/zh/`, `i18n/it/`, `i18n/pt/`); os outros idiomas são adicionados um de cada vez. Defina `AWS_IOT_LANG` para pular a pergunta interativa; quando falta uma tradução, os scripts usam o inglês como fallback, mensagem por mensagem.

## 🧹 Limpeza de recursos

**Lembre-se de fazer a limpeza quando terminar, para evitar cobranças contínuas.** O script de limpeza **não é destrutivo por padrão** (simulação) e remove apenas os recursos que correspondem ao padrão de nomenclatura deste tema, em ordem de dependência.

```bash
# Pré-visualização (não exclui nada)
python3 scripts/cleanup_script.py

# Exclui na sua região principal (pausa para pedir confirmação antes de CAs, templates e certificados)
python3 scripts/cleanup_script.py --execute

# Exclui na segunda região usada pelo Multi-Account Registration
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# Por fim, remova o stack da infraestrutura base (funções, Lambdas, grupos de logs)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ Solução de problemas

- **Credenciais / região**: configure com `aws configure`, variáveis de ambiente ou funções do IAM; os comandos de MAR precisam de uma segunda região válida em `--region`.
- **"Stack ... does not exist" ou função (role)/função Lambda não encontrada**: implante o stack da infraestrutura base (veja acima) antes de executar os scripts dos métodos.
- **`AccessDenied` no IAM/Lambda**: o stack base precisa de `CAPABILITY_NAMED_IAM`; a identidade em execução precisa de permissão para criar funções e passá-las para `iot.amazonaws.com` / `lambda.amazonaws.com`.
- **Certificado preso em `PENDING_ACTIVATION`**: o template de provisionamento ou a função de registro falhou; verifique no CloudTrail a ação negada (a seção de JITP do conteúdo do workshop tem um runbook completo).
- **Modo de depuração**: passe `--debug` (ou responda à pergunta sobre depuração) para exibir todas as chamadas e respostas das APIs.

## 📁 Estrutura do projeto

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # Infraestrutura base: funções do IAM + esqueletos Lambda (implantar uma vez)
├── scripts/                              # Scripts executáveis para o usuário
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # Pacote helper interno
│   └── utils/                            # Construtos do plano de controle + plano do dispositivo
│       ├── api_helpers.py                # Wrapper de safe_api_call
│       ├── device_simulator.py           # Construto MQTT DeviceConnection
│       └── fleet_provisioning_templates/ # JSON do template de provisionamento + da política
├── lambdas/                              # Código Lambda implantado nos esqueletos
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # Seção 6 — valida + assina a CSR, retira o certificado antigo
│   └── rotation_enroller.py               # Seção 6 — apenas referência, não implantado: transforma uma
│                                          #   descoberta (finding) de idade do Device Defender em uma inscrição na rotação
├── i18n/                                 # Internacionalização (catálogos de mensagens + loader)
├── requirements.txt                      # Dependências Python (os dois planos)
└── README.md
```

## 📄 Licença

Licença MIT No Attribution.

## 🏷️ Tags

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
