# AWS IoT Device Management - Learning Path - Advanced

> **⚠️ Esclusione di responsabilità:** questo esempio viene fornito solo a scopo dimostrativo e didattico e non è pensato per l'uso in produzione senza un'ulteriore revisione della sicurezza e test aggiuntivi.

Codice di esempio per il percorso di apprendimento avanzato di AWS IoT Device Management. Accompagna il workshop di Workshop Studio [**AWS IoT Device Management - Learning Path - Advanced**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (tutti i suoi argomenti) e, secondo il modello di un repository per percorso di apprendimento, è il repository gemello di [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) e [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics).

È il codice di esempio che accompagna **l'intero percorso di apprendimento avanzato**: un insieme di argomenti autonomi di AWS IoT Device Management (provisioning dei dispositivi, esecuzione di attività sulla flotta, ricerca e analisi della flotta, distribuzione del software / OTA, accesso remoto sicuro e osservabilità). Gli script combinano un **piano di controllo con boto3** e un **piano del dispositivo con AWS IoT Device SDK for Python v2**, così crei le risorse lato cloud e in più connetti un dispositivo simulato tramite MQTT. Gli script di ciascun argomento arrivano in questo repository man mano che viene pubblicato il contenuto del workshop di quell'argomento.

## 🌍 Lingue disponibili

| Lingua | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |
| 🇮🇹 Italiano | [README.it.md](README.it.md) |
| 🇧🇷 Português (Brasil) | [README.pt.md](README.pt.md) |
| 🇩🇪 Deutsch | [README.de.md](README.de.md) |

Anche gli script sono localizzati: imposta `AWS_IOT_LANG` (`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`) oppure scegli una lingua in modo interattivo alla prima esecuzione. Per ora i messaggi degli script sono disponibili in inglese, spagnolo, coreano, giapponese, cinese semplificato, italiano, portoghese brasiliano e tedesco; qualsiasi messaggio non ancora tradotto usa l'inglese come fallback.

## 🎯 Argomenti di questo percorso di apprendimento

Ogni argomento è autonomo: eseguili in ordine oppure scegli quelli che ti servono. Gli script vengono aggiunti qui man mano che viene pubblicato il contenuto pratico di ciascun argomento.

| # | Argomento | Stato | Script in questo repository |
|---|-------|--------|----------------------|
| 1 | **Provisioning dei dispositivi end-to-end**: JITP/JITR, Fleet Provisioning tramite claim e tramite utente attendibile, Multi-Account Registration | ✅ Disponibile | Sì, vedi [Script disponibili](#-script-disponibili) |
| 2 | **Fleet Task Execution**: AWS IoT Jobs e AWS IoT Commands su tutta la flotta | 🚧 In corso | Previsto |
| 3 | **Fleet Search & Analytics**: Fleet Indexing, aggregazioni, thing group | 🚧 In corso | Previsto |
| 4 | **Software Delivery / OTA**: Software Package Catalog, distribuzioni con versione tramite AWS IoT Jobs, SBOM | 🚧 In corso | Previsto |
| 5 | **Secure Remote Access**: AWS IoT Secure Tunneling e SSH attraverso un tunnel | 🚧 In corso | Previsto |
| 6 | **Observability & Troubleshooting**: logging di AWS IoT, Amazon CloudWatch, AWS CloudTrail | 🚧 In corso | Previsto |

> Il resto di questo README documenta l'**Argomento 1: Provisioning dei dispositivi end-to-end**, l'argomento i cui script sono disponibili oggi. Man mano che vengono pubblicati gli altri argomenti, i loro script (con le rispettive note sull'infrastruttura di base e sui costi) vengono aggiunti con la stessa struttura.

## 👥 Pubblico di destinazione

**Pubblico principale:** sviluppatori IoT, architetti di soluzioni e ingegneri DevOps che progettano l'onboarding dei dispositivi su larga scala in AWS IoT Core

**Prerequisiti:** conoscenza intermedia di AWS, fondamenti di AWS IoT Core (certificati, policy, MQTT), fondamenti di Python e uso della riga di comando

**Livello di apprendimento:** avanzato, un percorso pratico attraverso ogni metodo di provisioning e quando usare ciascuno

## 🎯 Provisioning dei dispositivi: obiettivi di apprendimento

Alla fine dell'Argomento 1 sarai in grado di:

- **CA personalizzata + JITP**: registrare un'autorità di certificazione ed effettuare automaticamente il provisioning dei dispositivi alla prima connessione con un template di provisioning incorporato
- **JITR**: guidare la registrazione a partire dall'evento `$aws/events/certificates/registered` con un handler Lambda e un controllo di sicurezza basato su un elenco di paesi consentiti (allow-list)
- **Fleet Provisioning tramite claim**: avviare i dispositivi con un certificato di claim (claim certificate) condiviso per lotto, scambiato con uno permanente tramite topic MQTT riservati
- **Pre-provisioning hook**: controllare `RegisterThing` con una Lambda sincrona che consente/nega e inserisce `parameterOverrides`
- **Fleet Provisioning tramite utente attendibile**: generare un provisioning claim di breve durata come identità IAM con ambito limitato (il modello dell'app mobile) e dimostrare il confine del privilegio minimo
- **Multi-Account Registration**: spostare un dispositivo in un'altra regione/account come cambio di endpoint riutilizzando lo stesso certificato, senza emetterne uno nuovo
- **Ciclo di vita dei certificati**: creare, registrare, attivare/disattivare, collegare/scollegare policy
- **Pulizia delle risorse**: rimuovere esattamente ciò che l'argomento ha creato, filtrando per pattern, lasciando intatto l'ambiente condiviso

## 🧩 Composizione a due piani

L'argomento di provisioning avanzato combina **due piani**:

- **Piano di controllo: `boto3`**: gestione dei dispositivi tramite le API `aws iot ...` (registrazione di autorità di certificazione, template di provisioning, pre-provisioning hook, Multi-Account Registration e così via), attraverso il costrutto condiviso `safe_api_call`.
- **Piano del dispositivo: `aws-iot-device-sdk-python-v2`**: un dispositivo simulato che si connette davvero tramite MQTT. Fornisce i pacchetti `awscrt` / `awsiot` e usa il costrutto di connessione **MQTT 5** (`awsiot.mqtt5_client_builder.mtls_from_path` su `awscrt.mqtt5`) per i passi di connessione nei flussi JITP, Fleet Provisioning, utente attendibile, Multi-Account Registration e rotazione dei certificati. La scelta di MQTT 5 è voluta: restituisce un **codice motivo (reason code)** in ogni conferma, così un dispositivo può distinguere un errore di autorizzazione (`NOT_AUTHORIZED`, 0x87: riprovare non servirà) da uno transitorio (`QUOTA_EXCEEDED`, 0x97: riprovare servirà). MQTT 3.1.1 non può proprio esprimerlo per una pubblicazione, perché il suo pacchetto PUBACK non ha un campo per il codice motivo.

Entrambi i piani si installano insieme da `requirements.txt`.

## 📋 Prerequisiti

- **Account AWS** con accesso amministrativo (lo stack dell'infrastruttura di base crea ruoli IAM con nome)
- Aver completato il workshop [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) (o esperienza equivalente)
- Aver completato il workshop [AWS IoT Device Management - Learning Path - Basic](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) (o esperienza equivalente)
- Una buona comprensione dei certificati X.509, delle autorità di certificazione (CA) e del TLS reciproco
- **Credenziali AWS** configurate (`aws configure`, variabili d'ambiente o ruoli IAM)
- **Python 3.10+** con pip
- **OpenSSL** nel PATH (usato negli esercizi sulla CA personalizzata e sulla richiesta di firma del certificato)
- **Git** per clonare il repository e installare l'SDK del piano del dispositivo

## 💰 Analisi dei costi: argomento Provisioning dei dispositivi

**Questo argomento crea risorse AWS reali che genereranno costi. Ecco cosa aspettarti per un'esecuzione completa:**

| Servizio | Utilizzo | Costo stimato (USD) |
|---------|-------|---------------------|
| **AWS IoT Core: messaggistica** | Alcune centinaia di messaggi MQTT in tutti i flussi | $0.01 - $0.10 |
| **AWS IoT Core: provisioning** | Certificati, thing, registrazioni di template di provisioning | $0.01 - $0.10 |
| **AWS Lambda** | Handler JITR + pre-provisioning hook (decine di invocazioni) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | Due gruppi di log Lambda di breve durata | $0.00 - $0.05 |
| **AWS IoT Core: seconda regione (MAR)** | Un certificato registrato + pochi messaggi | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | Gestione di ruoli/policy | $0.00 |
| **Totale stimato** | **Esecuzione completa di tutti i metodi** | **$0.03 - $0.35** |

**Gestione dei costi:**
- ✅ Lo script di pulizia rimuove tutto ciò che questo argomento crea (in entrambe le regioni)
- ✅ Risorse dimostrative di breve durata e su piccola scala
- ⚠️ **Ricordati di eseguire lo script di pulizia ed eliminare lo stack dell'infrastruttura di base quando hai finito**

**📊 Monitora i costi:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 Avvio rapido

```bash
# 1. Clona e configura
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # Su Windows: venv\Scripts\activate

# 2. Installa ENTRAMBI i piani (piano di controllo boto3 + piano del dispositivo aws-iot-device-sdk-python-v2)
pip install -r requirements.txt

# 3. Configura AWS e verifica OpenSSL
aws configure
openssl version

# 4. Distribuisci l'infrastruttura di base UNA VOLTA (crea i ruoli IAM + gli scheletri Lambda usati dagli script)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. Esegui un metodo (esempio: Fleet Provisioning tramite claim). Vedi "Flusso di lavoro consigliato" più avanti.
```

## 🏗️ Infrastruttura di base: Provisioning dei dispositivi (distribuiscila per prima)

A differenza dell'esempio *basics*, dove un solo script crea tutta la propria infrastruttura, gli script avanzati **presuppongono che esista già un piccolo insieme di risorse "di base" create in precedenza** (i ruoli che AWS IoT assume durante il provisioning, più due scheletri Lambda e i relativi ruoli di esecuzione). A un evento guidato da AWS questo stack è già distribuito per te; **se lavori in autonomia lo distribuisci una volta** con il template incluso in questo repository:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

Ogni risorsa che crea ha un nome fisso con il prefisso del modulo (`ws-aws-iot-dm-adv-prov-*`), così gli script la trovano tramite il nome esatto, senza dover passare per gli output dello stack. Acquisisci direttamente i valori che servono agli script:

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

Lo stack crea: il **ruolo di registrazione JITP**, il **ruolo di Fleet Provisioning**, il **ruolo dell'utente attendibile** (modella l'app mobile; sei tu ad assumerlo), la Lambda dell'**handler JITR** + il suo ruolo, la Lambda del **pre-provisioning hook** + il suo ruolo, e i relativi gruppi di log CloudWatch. Gli scheletri Lambda restituiscono "not implemented" finché non distribuisci il codice dell'handler (lo fanno gli script/i passi di JITR e dell'hook). Elimina lo stack quando hai finito (vedi Pulizia).

## 📚 Script disponibili

Questi sono gli script di **Provisioning dei dispositivi end-to-end** (Argomento 1). Gli script degli altri argomenti verranno elencati qui man mano che saranno disponibili.

| Script | Metodo di provisioning | Scopo |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (Sezione 2) | Registra una CA personalizzata con un template di provisioning JITP incorporato + il ruolo della configurazione di registrazione |
| **manage_jit_provisioning.py** | JITP / JITR (Sezione 2) | Gestisce la regola di topic (topic rule) JITR, distribuisce il codice dell'handler JITR e osserva i thing di cui è stato effettuato il provisioning |
| **fleet_provision_by_claim.py** | Fleet tramite claim (Sezione 3) | Crea il certificato di claim + la policy con ambito limitato, crea/versiona il template (con hook), esegue lo scambio MQTT claim→RegisterThing e osserva |
| **fleet_provision_trusted_user.py** | Fleet tramite utente attendibile (Sezione 4) | Crea il template, genera un claim di breve durata come utente attendibile, esegue lo scambio MQTT e osserva |
| **manage_multi_account_registration.py** | MAR (Sezione 5) | Registra un certificato senza CA (o una CA in `SNI_ONLY`), ottiene l'endpoint di una regione e sposta (riconnette) lo stesso certificato |
| **mqtt_connect.py** | Tutte le sezioni | Client minimo del Device SDK v2: si connette (riprovando dopo la disconnessione prevista alla prima connessione) e pubblica telemetria |
| **rotate_certificate.py** | Rotazione dei certificati (Sezione 6) | Parte del dispositivo in una rotazione guidata dal backend: prende l'esecuzione del job, genera localmente una nuova coppia di chiavi + CSR, installa il certificato firmato, si riconnette e dimostra una pubblicazione autorizzata prima di segnalare il successo (torna al certificato precedente se il passaggio non riesce) |
| **certificate_manager.py** | Helper | Ciclo di vita interattivo dei certificati: creare/registrare certificati, collegare/scollegare policy, attivare/disattivare |
| **cleanup_script.py** | Chiusura (Sezione 7) | Rimuove solo le risorse di questo argomento in base al pattern dei nomi, in ordine di dipendenza, in entrambe le regioni |

Esegui qualsiasi script con `-h` / `--help` per vederne i sottocomandi e gli argomenti. Gli script che richiedono l'ARN di un ruolo o di una Lambda lo accettano come argomento (ad esempio `--provisioning-role-arn`, `--role-arn`, `--hook-arn`): passa i valori acquisiti dallo stack di base qui sopra.

## 📖 Flusso di lavoro consigliato

Gli script seguono l'ordine dei moduli del workshop. Scegli il metodo o i metodi che vuoi mettere in pratica: ognuno è autonomo una volta distribuita l'infrastruttura di base.

```bash
# --- Fleet Provisioning tramite claim (Sezione 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (Sezione 5) ---
PROD_REGION=us-west-2   # la tua seconda regione (a un evento guidato da AWS, la regione indicata nella tua sessione)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- Rotazione dei certificati (Sezione 6) ---
# Parte del dispositivo in una rotazione guidata dal backend. Aggiungi --pause per fermarti a ogni
# punto osservabile (job IN_PROGRESS, la sovrapposizione dei certificati, il ritiro)
# così puoi ispezionare lo stato nella console o con la AWS CLI prima di continuare.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- Pulizia (Sezione 7) ---
python3 scripts/cleanup_script.py                      # simulazione (dry run): elenca cosa rimuoverebbe
python3 scripts/cleanup_script.py --execute            # regione principale
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # seconda regione
```

## ⚙️ Configurazione

**Variabili d'ambiente** (facoltative):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Imposta la lingua predefinita (en, es, fr, ja, ko, pt, zh, de, it)
```

**Funzionalità degli script**: piano di controllo nativo con `boto3`; costrutto MQTT del Device SDK v2 riutilizzato; selezione interattiva della lingua con l'inglese come fallback; `--debug` nella maggior parte degli script per mostrare chiamate/risposte delle API; tagging delle risorse del workshop per una pulizia sicura.

## 🌍 Internazionalizzazione

Questo percorso di apprendimento punta alle 9 lingue del workshop: inglese (`en`), spagnolo (`es`), giapponese (`ja`), coreano (`ko`), portoghese (`pt`), cinese (`zh`), tedesco (`de`), italiano (`it`) e francese (`fr`). Oggi i messaggi degli script sono disponibili in inglese, spagnolo, coreano, giapponese, cinese semplificato, italiano, portoghese brasiliano e tedesco (`i18n/en/`, `i18n/es/`, `i18n/ko/`, `i18n/ja/`, `i18n/zh/`, `i18n/it/`, `i18n/pt/`, `i18n/de/`); le altre lingue vengono aggiunte una alla volta. Imposta `AWS_IOT_LANG` per saltare la domanda interattiva; quando manca una traduzione, gli script usano l'inglese come fallback, messaggio per messaggio.

## 🧹 Pulizia delle risorse

**Ricordati di fare pulizia quando hai finito, per evitare costi continui.** Lo script di pulizia è **non distruttivo per impostazione predefinita** (simulazione) e rimuove solo le risorse che corrispondono al pattern dei nomi di questo argomento, in ordine di dipendenza.

```bash
# Anteprima (non elimina nulla)
python3 scripts/cleanup_script.py

# Elimina nella tua regione principale (si ferma a chiedere conferma prima di CA, template e certificati)
python3 scripts/cleanup_script.py --execute

# Elimina nella seconda regione usata da Multi-Account Registration
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# Infine, rimuovi lo stack dell'infrastruttura di base (ruoli, Lambda, gruppi di log)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ Risoluzione dei problemi

- **Credenziali / regione**: configurale con `aws configure`, variabili d'ambiente o ruoli IAM; i comandi MAR richiedono una seconda regione valida in `--region`.
- **"Stack ... does not exist" oppure ruolo/funzione non trovati**: distribuisci lo stack dell'infrastruttura di base (vedi sopra) prima di eseguire gli script dei metodi.
- **`AccessDenied` su IAM/Lambda**: lo stack di base richiede `CAPABILITY_NAMED_IAM`; l'identità in esecuzione deve avere l'autorizzazione a creare ruoli e a passarli a `iot.amazonaws.com` / `lambda.amazonaws.com`.
- **Certificato bloccato in `PENDING_ACTIVATION`**: il template di provisioning o il ruolo di registrazione non ha funzionato; controlla CloudTrail per trovare l'azione negata (la sezione JITP del contenuto del workshop ha un runbook completo).
- **Modalità di debug**: passa `--debug` (oppure rispondi alla domanda sul debug) per stampare tutte le chiamate e le risposte delle API.

## 📁 Struttura del progetto

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # Infrastruttura di base: ruoli IAM + scheletri Lambda (da distribuire una volta)
├── scripts/                              # Script eseguibili per l'utente
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # Pacchetto helper interno
│   └── utils/                            # Costrutti del piano di controllo + piano del dispositivo
│       ├── api_helpers.py                # Wrapper di safe_api_call
│       ├── device_simulator.py           # Costrutto MQTT DeviceConnection
│       └── fleet_provisioning_templates/ # JSON del template di provisioning + della policy
├── lambdas/                              # Codice Lambda distribuito negli scheletri
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # Sezione 6 — verifica + firma la CSR, ritira il certificato precedente
│   └── rotation_enroller.py               # Sezione 6 — solo di riferimento, non distribuito: trasforma un
│                                          #   risultato (finding) di età di Device Defender in un'iscrizione alla rotazione
├── i18n/                                 # Internazionalizzazione (cataloghi di messaggi + loader)
├── requirements.txt                      # Dipendenze Python (entrambi i piani)
└── README.md
```

## 📄 Licenza

Licenza MIT No Attribution.

## 🏷️ Tag

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
