# AWS IoT Device Management - Learning Path - Advanced

> **⚠️ Aviso legal:** Este ejemplo se proporciona únicamente con fines de demostración y educativos, y no está pensado para uso en producción sin una revisión de seguridad y pruebas adicionales.

Código de ejemplo para la ruta de aprendizaje avanzada de AWS IoT Device Management. Acompaña al taller de Workshop Studio [**AWS IoT Device Management - Learning Path - Advanced**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (todos sus temas) y, siguiendo el modelo de un repositorio por ruta de aprendizaje, es el repositorio hermano de [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) y [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics).

Es el código de ejemplo complementario de **toda la ruta de aprendizaje avanzada**: un conjunto de temas autocontenidos de AWS IoT Device Management (aprovisionamiento de dispositivos, ejecución de tareas en la flota, búsqueda y análisis de la flota, entrega de software / OTA, acceso remoto seguro y observabilidad). Los scripts combinan un **plano de control con boto3** y un **plano de dispositivo con AWS IoT Device SDK for Python v2**, así que creas los recursos del lado de la nube y además conectas un dispositivo simulado por MQTT. Los scripts de cada tema llegan a este repositorio a medida que se publica el contenido del taller de ese tema.

## 🌍 Idiomas disponibles

| Idioma | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |

Los propios scripts están localizados: define `AWS_IOT_LANG` (`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`) o elige un idioma de forma interactiva en la primera ejecución. Por ahora, los mensajes de los scripts están disponibles en inglés y español; cualquier mensaje que aún no esté traducido usa el inglés como alternativa (fallback).

## 🎯 Temas de esta ruta de aprendizaje

Cada tema es autocontenido: ejecútalos en orden o elige los que necesites. Los scripts se añaden aquí a medida que se publica el contenido práctico de cada tema.

| # | Tema | Estado | Scripts en este repositorio |
|---|-------|--------|----------------------|
| 1 | **Aprovisionamiento de dispositivos de principio a fin**: JITP/JITR, Fleet Provisioning mediante reclamación y mediante usuario de confianza, Multi-Account Registration | ✅ Disponible | Sí, consulta [Scripts disponibles](#-scripts-disponibles) |
| 2 | **Fleet Task Execution**: AWS IoT Jobs y AWS IoT Commands en toda una flota | 🚧 En curso | Previsto |
| 3 | **Fleet Search & Analytics**: Fleet Indexing, agregaciones, thing groups | 🚧 En curso | Previsto |
| 4 | **Software Delivery / OTA**: Software Package Catalog, despliegues versionados mediante AWS IoT Jobs, SBOM | 🚧 En curso | Previsto |
| 5 | **Secure Remote Access**: AWS IoT Secure Tunneling y SSH a través de un túnel | 🚧 En curso | Previsto |
| 6 | **Observability & Troubleshooting**: logging de AWS IoT, Amazon CloudWatch, AWS CloudTrail | 🚧 En curso | Previsto |

> El resto de este README documenta el **Tema 1: Aprovisionamiento de dispositivos de principio a fin**, el tema cuyos scripts se publican hoy. A medida que se publiquen los demás temas, sus scripts (y sus propias notas de infraestructura base y de costos) se añadirán con la misma estructura.

## 👥 Público objetivo

**Público principal:** desarrolladores de IoT, arquitectos de soluciones e ingenieros de DevOps que diseñan la incorporación (onboarding) de dispositivos a escala en AWS IoT Core

**Requisitos previos:** conocimientos intermedios de AWS, fundamentos de AWS IoT Core (certificados, políticas, MQTT), fundamentos de Python y uso de la línea de comandos

**Nivel de aprendizaje:** avanzado, un recorrido práctico por cada método de aprovisionamiento y cuándo usar cada uno

## 🎯 Aprovisionamiento de dispositivos: objetivos de aprendizaje

Al terminar el Tema 1 podrás:

- **CA personalizada + JITP**: registrar una autoridad de certificación y aprovisionar dispositivos automáticamente en su primera conexión con una plantilla de aprovisionamiento integrada
- **JITR**: impulsar el registro a partir del evento `$aws/events/certificates/registered` con un handler (controlador) de Lambda y una comprobación de seguridad basada en una lista de países permitidos
- **Fleet Provisioning mediante reclamación**: arrancar dispositivos con un certificado de reclamación (claim certificate) compartido por lote que se intercambia por uno permanente a través de topics MQTT reservados
- **Pre-provisioning hook**: controlar `RegisterThing` con una Lambda síncrona que permite/deniega e inyecta `parameterOverrides`
- **Fleet Provisioning mediante usuario de confianza**: generar una reclamación de aprovisionamiento (provisioning claim) de corta duración como una identidad de IAM con alcance limitado (el modelo de la aplicación móvil) y demostrar el límite de mínimo privilegio
- **Multi-Account Registration**: mover un dispositivo a otra Región/cuenta como un cambio de endpoint reutilizando el mismo certificado, sin volver a emitirlo
- **Ciclo de vida de los certificados**: crear, registrar, activar/desactivar, asociar/desasociar políticas
- **Limpieza de recursos**: eliminar exactamente lo que creó el tema, acotado por patrón, dejando intacto el entorno compartido

## 🧩 Composición de dos planos

El tema de aprovisionamiento avanzado combina **dos planos**:

- **Plano de control: `boto3`**: gestión de dispositivos mediante las API `aws iot ...` (registro de autoridades de certificación, plantillas de aprovisionamiento, pre-provisioning hooks, Multi-Account Registration, etc.), a través de la construcción compartida `safe_api_call`.
- **Plano de dispositivo: `aws-iot-device-sdk-python-v2`**: un dispositivo simulado que se conecta de verdad por MQTT. Proporciona los paquetes `awscrt` / `awsiot` y usa la construcción de conexión **MQTT 5** (`awsiot.mqtt5_client_builder.mtls_from_path` sobre `awscrt.mqtt5`) para los pasos de conexión en los flujos de JITP, Fleet Provisioning, usuario de confianza, Multi-Account Registration y rotación de certificados. La elección de MQTT 5 es deliberada: devuelve un **código de motivo** en cada confirmación, así que un dispositivo puede distinguir un fallo de autorización (`NOT_AUTHORIZED`, 0x87: reintentar no servirá) de uno transitorio (`QUOTA_EXCEEDED`, 0x97: reintentar sí servirá). MQTT 3.1.1 no puede expresar esto en absoluto para una publicación, porque su paquete PUBACK no tiene campo de código de motivo.

Ambos planos se instalan juntos desde `requirements.txt`.

## 📋 Requisitos previos

- **Cuenta de AWS** con acceso de administrador (el stack de infraestructura base crea roles de IAM con nombre)
- Haber completado el taller [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) (o experiencia equivalente)
- Haber completado el taller [AWS IoT Device Management - Learning Path - Basics](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) (o experiencia equivalente)
- Comprensión sólida de los certificados X.509, las autoridades de certificación (CA) y TLS mutuo
- **Credenciales de AWS** configuradas (`aws configure`, variables de entorno o roles de IAM)
- **Python 3.10+** con pip
- **OpenSSL** en el PATH (se usa en los ejercicios de CA personalizada y de solicitud de firma de certificado)
- **Git** para clonar el repositorio e instalar el SDK del plano de dispositivo

## 💰 Análisis de costos: tema de aprovisionamiento de dispositivos

**Este tema crea recursos reales de AWS que generarán cargos. Esto es lo que puedes esperar en una ejecución completa:**

| Servicio | Uso | Costo estimado (USD) |
|---------|-------|---------------------|
| **AWS IoT Core: mensajería** | Unos cientos de mensajes MQTT en todos los flujos | $0.01 - $0.10 |
| **AWS IoT Core: aprovisionamiento** | Certificados, things, registros de plantillas de aprovisionamiento | $0.01 - $0.10 |
| **AWS Lambda** | Handler de JITR + pre-provisioning hook (decenas de invocaciones) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | Dos grupos de logs de Lambda de corta duración | $0.00 - $0.05 |
| **AWS IoT Core: segunda Región (MAR)** | Un certificado registrado + unos pocos mensajes | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | Gestión de roles/políticas | $0.00 |
| **Total estimado** | **Ejecución completa de todos los métodos** | **$0.03 - $0.35** |

**Gestión de costos:**
- ✅ El script de limpieza elimina todo lo que crea este tema (en ambas Regiones)
- ✅ Recursos de demostración de corta duración y a pequeña escala
- ⚠️ **Recuerda ejecutar el script de limpieza y eliminar el stack de infraestructura base cuando termines**

**📊 Supervisa los costos:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 Inicio rápido

```bash
# 1. Clona y configura
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 2. Instala AMBOS planos (plano de control boto3 + plano de dispositivo aws-iot-device-sdk-python-v2)
pip install -r requirements.txt

# 3. Configura AWS y confirma OpenSSL
aws configure
openssl version

# 4. Despliega la infraestructura base UNA VEZ (crea los roles de IAM + los esqueletos de Lambda que usan los scripts)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. Ejecuta un método (ejemplo: Fleet Provisioning mediante reclamación). Consulta "Flujo de trabajo recomendado" más abajo.
```

## 🏗️ Infraestructura base: aprovisionamiento de dispositivos (despliégala primero)

A diferencia del ejemplo *basics*, donde un script crea toda su propia infraestructura, los scripts avanzados **dan por hecho que existe un pequeño conjunto de recursos "base" creados previamente** (los roles que AWS IoT asume durante el aprovisionamiento, además de dos esqueletos de Lambda y sus roles de ejecución). En un evento dirigido por AWS, este stack ya está desplegado para ti; **si lo ejecutas por tu cuenta, lo despliegas una vez** con la plantilla incluida en este repositorio:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

Cada recurso que crea tiene un nombre fijo con el prefijo del módulo (`ws-aws-iot-dm-adv-prov-*`), así que los scripts los resuelven por su nombre exacto, sin tener que manejar las salidas del stack. Captura directamente los valores que necesitan los scripts:

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

El stack crea: el **rol de registro de JITP**, el **rol de Fleet Provisioning**, el **rol de usuario de confianza** (modela la aplicación móvil; tú lo asumes), la Lambda del **handler de JITR** + su rol, la Lambda del **pre-provisioning hook** + su rol, y sus grupos de logs de CloudWatch. Los esqueletos de Lambda devuelven "not implemented" hasta que despliegues el código del handler (los scripts/pasos de JITR y del hook lo hacen). Elimina el stack cuando termines (consulta Limpieza).

## 📚 Scripts disponibles

Estos son los scripts de **Aprovisionamiento de dispositivos de principio a fin** (Tema 1). Los scripts de los demás temas se listarán aquí a medida que se publiquen.

| Script | Método de aprovisionamiento | Propósito |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (Sección 2) | Registra una CA personalizada con una plantilla de aprovisionamiento de JITP integrada + el rol de la configuración de registro |
| **manage_jit_provisioning.py** | JITP / JITR (Sección 2) | Gestiona la regla de tema (topic rule) de JITR, despliega el código del handler de JITR y observa los things aprovisionados |
| **fleet_provision_by_claim.py** | Fleet mediante reclamación (Sección 3) | Crea el certificado de reclamación + la política con alcance limitado, crea/versiona la plantilla (con hook), ejecuta el intercambio MQTT reclamación→RegisterThing y observa |
| **fleet_provision_trusted_user.py** | Fleet mediante usuario de confianza (Sección 4) | Crea la plantilla, genera una reclamación de aprovisionamiento de corta duración como usuario de confianza, ejecuta el intercambio MQTT y observa |
| **manage_multi_account_registration.py** | MAR (Sección 5) | Registra un certificado sin CA (o una CA en `SNI_ONLY`), obtiene el endpoint de una Región y mueve (reconecta) el mismo certificado |
| **mqtt_connect.py** | Todas las secciones | Cliente mínimo del Device SDK v2: se conecta (reintentando la desconexión esperada de la primera conexión) y publica telemetría |
| **rotate_certificate.py** | Rotación de certificados (Sección 6) | Parte del dispositivo en una rotación impulsada por el backend: toma la ejecución del job, genera localmente un nuevo par de claves + CSR, instala el certificado firmado, se reconecta y demuestra una publicación autorizada antes de notificar el éxito (revierte al certificado anterior si el cambio de certificado falla) |
| **certificate_manager.py** | Auxiliar | Ciclo de vida interactivo de certificados: crear/registrar certificados, asociar/desasociar políticas, activar/desactivar |
| **cleanup_script.py** | Cierre (Sección 7) | Elimina solo los recursos de este tema por patrón de nombres, en orden de dependencias, en ambas Regiones |

Ejecuta cualquier script con `-h` / `--help` para ver sus subcomandos y argumentos. Los scripts que reciben un ARN de rol o de Lambda lo aceptan como argumento (por ejemplo `--provisioning-role-arn`, `--role-arn`, `--hook-arn`): proporciona los valores capturados del stack base más arriba.

## 📖 Flujo de trabajo recomendado

Los scripts siguen el orden de los módulos del taller. Elige el método o los métodos que quieras practicar: cada uno es autocontenido una vez desplegada la infraestructura base.

```bash
# --- Fleet Provisioning mediante reclamación (Sección 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (Sección 5) ---
PROD_REGION=us-west-2   # tu segunda Región (en un evento dirigido por AWS, la Región indicada en tu sesión)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- Rotación de certificados (Sección 6) ---
# Parte del dispositivo en una rotación impulsada por el backend. Añade --pause para detenerte en cada
# paso observable (job IN_PROGRESS, el solapamiento de certificados, la retirada)
# y así inspeccionar el estado en la consola o con la AWS CLI antes de continuar.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- Limpieza (Sección 7) ---
python3 scripts/cleanup_script.py                      # simulación (dry run): lista lo que eliminaría
python3 scripts/cleanup_script.py --execute            # Región principal
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # segunda Región
```

## ⚙️ Configuración

**Variables de entorno** (opcionales):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Define el idioma predeterminado (en, es, fr, ja, ko, pt, zh, de, it)
```

**Características de los scripts**: plano de control nativo con `boto3`; construcción MQTT del Device SDK v2 reutilizada; selección interactiva de idioma con inglés como alternativa; `--debug` en la mayoría de los scripts para mostrar llamadas/respuestas de la API; etiquetado de los recursos del taller para una limpieza segura.

## 🌍 Internacionalización

Esta ruta de aprendizaje apunta a los 9 idiomas del taller: inglés (`en`), español (`es`), japonés (`ja`), coreano (`ko`), portugués (`pt`), chino (`zh`), alemán (`de`), italiano (`it`) y francés (`fr`). Los mensajes de los scripts se publican hoy en inglés y español (`i18n/en/`, `i18n/es/`); los demás idiomas se añaden de uno en uno. Define `AWS_IOT_LANG` para omitir la pregunta interactiva; los scripts usan el inglés como alternativa, mensaje por mensaje, cuando falta una traducción.

## 🧹 Limpieza de recursos

**Recuerda hacer la limpieza cuando termines para evitar cargos continuos.** El script de limpieza es **no destructivo de forma predeterminada** (simulación) y elimina solo los recursos que coinciden con el patrón de nombres de este tema, en orden de dependencias.

```bash
# Vista previa (no elimina nada)
python3 scripts/cleanup_script.py

# Elimina en tu Región principal (se detiene para pedir confirmación antes de las CA, las plantillas y los certificados)
python3 scripts/cleanup_script.py --execute

# Elimina la segunda Región usada por Multi-Account Registration
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# Por último, elimina el stack de infraestructura base (roles, Lambdas, grupos de logs)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ Solución de problemas

- **Credenciales / Región**: configúralas con `aws configure`, variables de entorno o roles de IAM; los comandos de MAR necesitan una segunda Región válida en `--region`.
- **"Stack ... does not exist" o rol/función no encontrados**: despliega el stack de infraestructura base (consulta más arriba) antes de ejecutar los scripts de los métodos.
- **`AccessDenied` en IAM/Lambda**: el stack base necesita `CAPABILITY_NAMED_IAM`; la identidad en ejecución necesita permiso para crear roles y pasarlos a `iot.amazonaws.com` / `lambda.amazonaws.com`.
- **Certificado atascado en `PENDING_ACTIVATION`**: la plantilla de aprovisionamiento o el rol de registro fallaron; revisa CloudTrail para encontrar la acción denegada (la sección de JITP del contenido del taller tiene un runbook completo).
- **Modo de depuración**: pasa `--debug` (o responde a la pregunta de depuración) para imprimir todas las llamadas y respuestas de la API.

## 📁 Estructura del proyecto

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # Infra base: roles de IAM + esqueletos de Lambda (desplegar una vez)
├── scripts/                              # Scripts ejecutables para el usuario
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # Paquete auxiliar interno
│   └── utils/                            # Construcciones del plano de control + plano de dispositivo
│       ├── api_helpers.py                # Envoltorio (wrapper) de safe_api_call
│       ├── device_simulator.py           # Construcción MQTT DeviceConnection
│       └── fleet_provisioning_templates/ # JSON de la plantilla de aprovisionamiento + la política
├── lambdas/                              # Código de Lambda desplegado en los esqueletos
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # Sección 6 — valida + firma la CSR, retira el certificado anterior
│   └── rotation_enroller.py               # Sección 6 — solo de referencia, no se despliega: convierte un
│                                          #   hallazgo de antigüedad de Device Defender en una inscripción de rotación
├── i18n/                                 # Internacionalización (catálogos de mensajes + cargador)
├── requirements.txt                      # Dependencias de Python (ambos planos)
└── README.md
```

## 📄 Licencia

Licencia MIT No Attribution.

## 🏷️ Etiquetas

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
