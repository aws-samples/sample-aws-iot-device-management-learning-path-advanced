# AWS IoT Device Management - Learning Path - Advanced

> **⚠️ Haftungsausschluss:** Dieses Beispiel dient ausschließlich Demonstrations- und Schulungszwecken und ist ohne zusätzliche Sicherheitsprüfung und Tests nicht für den Produktionseinsatz vorgesehen.

Beispielcode für den fortgeschrittenen AWS IoT Device Management Learning Path. Er begleitet den Workshop-Studio-Workshop [**AWS IoT Device Management - Learning Path - Advanced**](https://catalog.us-east-1.prod.workshops.aws/workshops/67a686fb-7984-4254-ac25-927838c99f72) (alle seine Themen) und ist nach dem Prinzip „ein Repository pro Learning Path“ das Schwester-Repository von [`sample-aws-iot-core-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-core-learning-path-basics) und [`sample-aws-iot-device-management-learning-path-basics`](https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-basics).

Es ist der Beispielcode-Begleiter für den **gesamten fortgeschrittenen Learning Path**: eine Reihe in sich abgeschlossener AWS IoT Device Management-Themen (Geräte-Provisionierung, Aufgabenausführung in der Flotte, Flottensuche und -analyse, Softwareauslieferung / OTA, sicherer Fernzugriff und Observability). Die Skripte kombinieren eine **Steuerungsebene mit boto3** und eine **Geräteebene mit dem AWS IoT Device SDK for Python v2**, sodass du sowohl die cloudseitigen Ressourcen erstellst als auch ein simuliertes Gerät über MQTT verbindest. Die Skripte für jedes Thema kommen in dieses Repository, sobald die Workshop-Inhalte des jeweiligen Themas veröffentlicht sind.

## 🌍 Verfügbare Sprachen

| Sprache | README |
|----------|--------|
| 🇺🇸 English | [README.md](README.md) |
| 🇪🇸 Español | [README.es.md](README.es.md) |
| 🇰🇷 한국어 | [README.ko.md](README.ko.md) |
| 🇯🇵 日本語 | [README.ja.md](README.ja.md) |
| 🇨🇳 简体中文 | [README.zh.md](README.zh.md) |
| 🇮🇹 Italiano | [README.it.md](README.it.md) |
| 🇧🇷 Português (Brasil) | [README.pt.md](README.pt.md) |
| 🇩🇪 Deutsch | [README.de.md](README.de.md) |

Die Skripte selbst sind lokalisiert: Setze `AWS_IOT_LANG` (`en`, `es`, `ja`, `ko`, `pt`, `zh`, `de`, `it`, `fr`) oder wähle beim ersten Start interaktiv eine Sprache aus. Die Skriptmeldungen sind derzeit auf Englisch, Spanisch, Koreanisch, Japanisch, vereinfachtem Chinesisch, Italienisch, brasilianischem Portugiesisch und Deutsch verfügbar; jede noch nicht übersetzte Meldung fällt auf Englisch zurück.

## 🎯 Themen in diesem Learning Path

Jedes Thema ist in sich abgeschlossen: Arbeite sie der Reihe nach durch oder wähle die aus, die du brauchst. Die Skripte werden hier ergänzt, sobald die praktischen Inhalte des jeweiligen Themas veröffentlicht sind.

| # | Thema | Status | Skripte in diesem Repository |
|---|-------|--------|----------------------|
| 1 | **Geräte-Provisionierung von Anfang bis Ende**: JITP/JITR, Fleet Provisioning per Claim und per vertrauenswürdigem Benutzer, Multi-Account Registration | ✅ Verfügbar | Ja, siehe [Verfügbare Skripte](#-verfügbare-skripte) |
| 2 | **Fleet Task Execution**: AWS IoT Jobs und AWS IoT Commands in der gesamten Flotte | 🚧 In Arbeit | Geplant |
| 3 | **Fleet Search & Analytics**: Fleet Indexing, Aggregationen, Thing Groups | 🚧 In Arbeit | Geplant |
| 4 | **Software Delivery / OTA**: Software Package Catalog, versionierte Bereitstellungen über AWS IoT Jobs, SBOM | 🚧 In Arbeit | Geplant |
| 5 | **Secure Remote Access**: AWS IoT Secure Tunneling und SSH über einen Tunnel | 🚧 In Arbeit | Geplant |
| 6 | **Observability & Troubleshooting**: AWS IoT-Logging, Amazon CloudWatch, AWS CloudTrail | 🚧 In Arbeit | Geplant |

> Der Rest dieses README dokumentiert **Thema 1: Geräte-Provisionierung von Anfang bis Ende**, das Thema, dessen Skripte schon heute verfügbar sind. Sobald die anderen Themen veröffentlicht sind, werden ihre Skripte (zusammen mit ihren eigenen Hinweisen zu Basisinfrastruktur und Kosten) in derselben Struktur ergänzt.

## 👥 Zielgruppe

**Primäre Zielgruppe:** IoT-Entwickler, Lösungsarchitekten und DevOps-Engineers, die das Onboarding von Geräten in großem Maßstab auf AWS IoT Core entwerfen

**Voraussetzungen:** AWS-Kenntnisse auf mittlerem Niveau, AWS IoT Core-Grundlagen (Zertifikate, Richtlinien, MQTT), Python-Grundlagen und Umgang mit der Befehlszeile

**Lernniveau:** Fortgeschritten, ein praktischer Rundgang durch jede Provisionierungsmethode und wann du welche einsetzt

## 🎯 Geräte-Provisionierung: Lernziele

Am Ende von Thema 1 kannst du:

- **Eigene CA + JITP**: eine Zertifizierungsstelle registrieren und Geräte bei der ersten Verbindung mit einem eingebetteten Provisioning-Template automatisch provisionieren
- **JITR**: die Registrierung über das Ereignis `$aws/events/certificates/registered` mit einem Lambda-Handler und einer Leitplanke auf Basis einer Länder-Positivliste (allow-list) steuern
- **Fleet Provisioning per Claim**: Geräte mit einem gemeinsamen Claim-Zertifikat (claim certificate) pro Charge initialisieren, das über reservierte MQTT-Topics gegen ein dauerhaftes Zertifikat getauscht wird
- **Pre-Provisioning-Hook**: `RegisterThing` mit einer synchronen Lambda absichern, die erlaubt/verweigert und `parameterOverrides` einfügt
- **Fleet Provisioning per vertrauenswürdigem Benutzer**: einen kurzlebigen Claim als eingeschränkte IAM-Identität (das Modell der mobilen App) ausstellen und die Grenze der geringsten Berechtigung nachweisen
- **Multi-Account Registration**: ein Gerät als Endpoint-Wechsel mit demselben, wiederverwendeten Zertifikat in eine andere Region bzw. ein anderes Konto umziehen, ohne ein neues auszustellen
- **Zertifikatslebenszyklus**: Zertifikate erstellen, registrieren, aktivieren/deaktivieren, Richtlinien anhängen/trennen
- **Ressourcenbereinigung**: genau das entfernen, was das Thema erstellt hat, eingegrenzt per Benennungsmuster, ohne die gemeinsame Umgebung anzutasten

## 🧩 Zusammenspiel zweier Ebenen

Das fortgeschrittene Provisionierungsthema kombiniert **zwei Ebenen**:

- **Steuerungsebene: `boto3`**: Geräteverwaltung über die `aws iot ...`-APIs (Registrieren von Zertifizierungsstellen, Provisioning-Templates, Pre-Provisioning-Hooks, Multi-Account Registration usw.) über das gemeinsame Konstrukt `safe_api_call`.
- **Geräteebene: `aws-iot-device-sdk-python-v2`**: ein simuliertes Gerät, das sich tatsächlich über MQTT verbindet. Es stellt die Pakete `awscrt` / `awsiot` bereit und nutzt das **MQTT 5**-Verbindungskonstrukt (`awsiot.mqtt5_client_builder.mtls_from_path` über `awscrt.mqtt5`) für die Verbindungsschritte in den Abläufen für JITP, Fleet Provisioning, vertrauenswürdigen Benutzer, Multi-Account Registration und Zertifikatsrotation. MQTT 5 ist bewusst gewählt: Es liefert bei jeder Bestätigung einen **Reason Code**, sodass ein Gerät einen Autorisierungsfehler (`NOT_AUTHORIZED`, 0x87: ein erneuter Versuch hilft nicht) von einem vorübergehenden Fehler (`QUOTA_EXCEEDED`, 0x97: ein erneuter Versuch hilft) unterscheiden kann. MQTT 3.1.1 kann das für eine Veröffentlichung überhaupt nicht ausdrücken, weil sein PUBACK-Paket kein Feld für einen Reason Code hat.

Beide Ebenen werden gemeinsam über `requirements.txt` installiert.

## 📋 Voraussetzungen

- **AWS-Konto** mit Administratorzugriff (der Stack der Basisinfrastruktur erstellt IAM-Rollen mit festen Namen)
- Abschluss des Workshops [AWS IoT Core Basics](https://catalog.workshops.aws/workshops/a007780e-1086-421b-a7e3-b7ac63e37089) (oder vergleichbare Erfahrung)
- Abschluss des Workshops [AWS IoT Device Management - Learning Path - Basic](https://catalog.workshops.aws/workshops/40b80218-bf1d-45d6-b8bb-022f6d316a52) (oder vergleichbare Erfahrung)
- Solides Verständnis von X.509-Zertifikaten, Zertifizierungsstellen (CAs) und gegenseitigem TLS
- **AWS-Anmeldeinformationen** konfiguriert (`aws configure`, Umgebungsvariablen oder IAM-Rollen)
- **Python 3.10+** mit pip
- **OpenSSL** im PATH (wird für die Übungen zur eigenen CA und zur Zertifikatsignieranforderung (Certificate Signing Request, CSR) verwendet)
- **Git** zum Klonen des Repositorys und zum Installieren des SDK der Geräteebene

## 💰 Kostenanalyse: Thema Geräte-Provisionierung

**Dieses Thema erstellt echte AWS-Ressourcen, für die Gebühren anfallen. Damit kannst du bei einem vollständigen Durchlauf rechnen:**

| Service | Nutzung | Geschätzte Kosten (USD) |
|---------|-------|---------------------|
| **AWS IoT Core: Messaging** | Einige hundert MQTT-Nachrichten über alle Abläufe | $0.01 - $0.10 |
| **AWS IoT Core: Provisionierung** | Zertifikate, Things, Registrierungen von Provisioning-Templates | $0.01 - $0.10 |
| **AWS Lambda** | JITR-Handler + Pre-Provisioning-Hook (einige Dutzend Aufrufe) | $0.00 - $0.05 |
| **Amazon CloudWatch Logs** | Zwei kurzlebige Lambda-Protokollgruppen | $0.00 - $0.05 |
| **AWS IoT Core: zweite Region (MAR)** | Ein registriertes Zertifikat + einige Nachrichten | $0.01 - $0.05 |
| **AWS Identity and Access Management (IAM)** | Verwaltung von Rollen/Richtlinien | $0.00 |
| **Geschätzte Gesamtkosten** | **Vollständiger Durchlauf aller Methoden** | **$0.03 - $0.35** |

**Kostenmanagement:**
- ✅ Das Bereinigungsskript entfernt alles, was dieses Thema erstellt (in beiden Regionen)
- ✅ Kurzlebige Demo-Ressourcen in kleinem Maßstab
- ⚠️ **Denk daran, das Bereinigungsskript auszuführen und den Stack der Basisinfrastruktur zu löschen, wenn du fertig bist**

**📊 Kosten überwachen:** [AWS Billing Dashboard](https://console.aws.amazon.com/billing/)

## 🚀 Schnellstart

```bash
# 1. Klonen und einrichten
git clone https://github.com/aws-samples/sample-aws-iot-device-management-learning-path-advanced.git
cd sample-aws-iot-device-management-learning-path-advanced
python3 -m venv venv
source venv/bin/activate  # Unter Windows: venv\Scripts\activate

# 2. BEIDE Ebenen installieren (Steuerungsebene boto3 + Geräteebene aws-iot-device-sdk-python-v2)
pip install -r requirements.txt

# 3. AWS konfigurieren und OpenSSL prüfen
aws configure
openssl version

# 4. Die Basisinfrastruktur EINMAL bereitstellen (erstellt die IAM-Rollen + Lambda-Gerüste, die die Skripte nutzen)
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM

# 5. Eine Methode ausführen (Beispiel: Fleet Provisioning per Claim). Siehe „Empfohlener Arbeitsablauf“ unten.
```

## 🏗️ Basisinfrastruktur: Geräte-Provisionierung (zuerst bereitstellen)

Anders als beim *basics*-Beispiel, bei dem ein einziges Skript seine gesamte Infrastruktur selbst erstellt, **setzen die fortgeschrittenen Skripte voraus, dass eine kleine Menge vorab erstellter „Basis“-Ressourcen existiert** (die Rollen, die AWS IoT während der Provisionierung übernimmt, sowie zwei Lambda-Gerüste und ihre Ausführungsrollen). Bei einer von AWS geleiteten Veranstaltung ist dieser Stack bereits für dich bereitgestellt; **arbeitest du eigenständig, stellst du ihn einmal bereit**, mit dem Template, das in diesem Repository enthalten ist:

```bash
aws cloudformation deploy \
  --template-file infrastructure/provisioning-base.yaml \
  --stack-name ws-aws-iot-dm-adv-prov-base \
  --capabilities CAPABILITY_NAMED_IAM
```

Jede Ressource, die er erstellt, hat einen festen Namen mit dem Modulpräfix (`ws-aws-iot-dm-adv-prov-*`), sodass die Skripte sie über den exakten Namen finden, ohne Umweg über Stack-Outputs. Erfasse die Werte, die die Skripte brauchen, direkt:

```bash
FLEET_ROLE_ARN=$(aws iam get-role   --role-name ws-aws-iot-dm-adv-prov-fleet-provisioning-role --query 'Role.Arn' --output text)
JITP_ROLE_ARN=$(aws iam get-role    --role-name ws-aws-iot-dm-adv-prov-jitp-registration-role  --query 'Role.Arn' --output text)
HOOK_ARN=$(aws lambda get-function  --function-name ws-aws-iot-dm-adv-prov-pre-provisioning-hook --query 'Configuration.FunctionArn' --output text)
```

Der Stack erstellt: die **JITP-Registrierungsrolle**, die **Fleet-Provisioning-Rolle**, die **Rolle des vertrauenswürdigen Benutzers** (modelliert die mobile App; du übernimmst sie), die Lambda des **JITR-Handlers** + Rolle, die Lambda des **Pre-Provisioning-Hooks** + Rolle sowie die zugehörigen CloudWatch-Protokollgruppen. Die Lambda-Gerüste geben „not implemented“ zurück, bis du den Handler-Code bereitstellst (das erledigen die Skripte/Arbeitsschritte für JITR und den Hook). Lösche den Stack, wenn du fertig bist (siehe Bereinigung).

## 📚 Verfügbare Skripte

Das sind die Skripte für **Geräte-Provisionierung von Anfang bis Ende** (Thema 1). Die Skripte der anderen Themen werden hier aufgeführt, sobald sie verfügbar sind.

| Skript | Provisionierungsmethode | Zweck |
|--------|--------------------|---------|
| **register_custom_ca.py** | JITP (Abschnitt 2) | Registriert eine eigene CA mit einem eingebetteten JITP-Provisioning-Template + der Rolle der Registrierungskonfiguration |
| **manage_jit_provisioning.py** | JITP / JITR (Abschnitt 2) | Verwaltet die JITR-Topic-Regel (topic rule), stellt den Code des JITR-Handlers bereit und beobachtet die provisionierten Things |
| **fleet_provision_by_claim.py** | Fleet per Claim (Abschnitt 3) | Erstellt das Claim-Zertifikat + die eingeschränkte Richtlinie, erstellt/versioniert das Template (mit Hook), führt den MQTT-Nachrichtenaustausch Claim→RegisterThing aus und beobachtet |
| **fleet_provision_trusted_user.py** | Fleet per vertrauenswürdigem Benutzer (Abschnitt 4) | Erstellt das Template, stellt als vertrauenswürdiger Benutzer einen kurzlebigen Claim aus, führt den MQTT-Nachrichtenaustausch aus und beobachtet |
| **manage_multi_account_registration.py** | MAR (Abschnitt 5) | Registriert ein Zertifikat ohne CA (oder eine CA in `SNI_ONLY`), ermittelt den Endpoint einer Region und zieht dasselbe Zertifikat um (verbindet es erneut) |
| **mqtt_connect.py** | Alle Abschnitte | Minimaler Device SDK v2-Client: verbindet sich (mit erneutem Versuch nach der erwarteten Trennung bei der ersten Verbindung) und veröffentlicht Telemetrie |
| **rotate_certificate.py** | Zertifikatsrotation (Abschnitt 6) | Geräteseite einer vom Backend gesteuerten Rotation: übernimmt die Job-Ausführung, erzeugt lokal ein neues Schlüsselpaar + CSR, installiert das signierte Zertifikat, verbindet sich erneut und weist eine autorisierte Veröffentlichung nach, bevor es Erfolg meldet (setzt auf das alte Zertifikat zurück, wenn die Umstellung fehlschlägt) |
| **certificate_manager.py** | Hilfsskript | Interaktiver Zertifikatslebenszyklus: Zertifikate erstellen/registrieren, Richtlinien anhängen/trennen, aktivieren/deaktivieren |
| **cleanup_script.py** | Zusammenfassung und Bereinigung pro Thema (Abschnitt 7) | Entfernt nur die Ressourcen dieses Themas anhand des Benennungsmusters, in Abhängigkeitsreihenfolge, in beiden Regionen |

Führe ein beliebiges Skript mit `-h` / `--help` aus, um seine Unterbefehle und Argumente zu sehen. Skripte, die den ARN einer Rolle oder Lambda benötigen, nehmen ihn als Argument entgegen (zum Beispiel `--provisioning-role-arn`, `--role-arn`, `--hook-arn`): Übergib die Werte, die du oben aus dem Basis-Stack erfasst hast.

## 📖 Empfohlener Arbeitsablauf

Die Skripte folgen der Modulreihenfolge des Workshops. Wähle die Methode(n) aus, die du üben möchtest: Jede ist in sich abgeschlossen, sobald die Basisinfrastruktur bereitgestellt ist.

```bash
# --- Fleet Provisioning per Claim (Abschnitt 3) ---
python3 scripts/fleet_provision_by_claim.py create-claim --policy-name FleetClaimPolicy
python3 scripts/fleet_provision_by_claim.py create-template \
  --template-name FleetClaimTemplate \
  --provisioning-role-arn "$FLEET_ROLE_ARN" --hook-arn "$HOOK_ARN"
python3 scripts/fleet_provision_by_claim.py provision \
  --template-name FleetClaimTemplate \
  --claim-cert claim.pem --claim-key claim.private.key \
  --serial-number Vehicle-VIN-777 --model-type SUVVehicle

# --- Multi-Account Registration (Abschnitt 5) ---
PROD_REGION=us-west-2   # deine zweite Region (bei einer von AWS geleiteten Veranstaltung die in deiner Sitzung genannte Region)
python3 scripts/manage_multi_account_registration.py register-without-ca \
  --region "$PROD_REGION" --certificate-pem device.pem \
  --policy-name MARProductionDevicePolicy --thing-name Vehicle-VIN-MAR-001

# --- Zertifikatsrotation (Abschnitt 6) ---
# Geräteseite einer vom Backend gesteuerten Rotation. Füge --pause hinzu, um bei jedem
# beobachtbaren Arbeitsschritt anzuhalten (Job IN_PROGRESS, die Zertifikatsüberlappung, die Außerbetriebnahme),
# damit du den Zustand in der Konsole oder mit der AWS CLI prüfen kannst, bevor du weitermachst.
python3 scripts/rotate_certificate.py \
  --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \
  --cert AnyCompany-Sensor-9001.old.cert.pem \
  --key AnyCompany-Sensor-9001.old.private.key \
  --ca AmazonRootCA1.pem --pause

# --- Bereinigung (Abschnitt 7) ---
python3 scripts/cleanup_script.py                      # Probelauf (dry run): listet auf, was entfernt würde
python3 scripts/cleanup_script.py --execute            # Hauptregion
python3 scripts/cleanup_script.py --execute --mar-region "$PROD_REGION"   # zweite Region
```

## ⚙️ Konfiguration

**Umgebungsvariablen** (optional):

```bash
export AWS_DEFAULT_REGION=us-east-1
export AWS_IOT_LANG=en   # Standardsprache festlegen (en, es, fr, ja, ko, pt, zh, de, it)
```

**Skriptfunktionen**: native `boto3`-Steuerungsebene; wiederverwendetes MQTT-Konstrukt des Device SDK v2; interaktive Sprachauswahl mit Englisch als Fallback; `--debug` in den meisten Skripten, um API-Aufrufe/-Antworten anzuzeigen; Tagging der Workshop-Ressourcen für eine sichere Bereinigung.

## 🌍 Internationalisierung

Dieser Learning Path richtet sich an die 9 Workshop-Sprachen: Englisch (`en`), Spanisch (`es`), Japanisch (`ja`), Koreanisch (`ko`), Portugiesisch (`pt`), Chinesisch (`zh`), Deutsch (`de`), Italienisch (`it`) und Französisch (`fr`). Skriptmeldungen gibt es heute auf Englisch, Spanisch, Koreanisch, Japanisch, vereinfachtem Chinesisch, Italienisch, brasilianischem Portugiesisch und Deutsch (`i18n/en/`, `i18n/es/`, `i18n/ko/`, `i18n/ja/`, `i18n/zh/`, `i18n/it/`, `i18n/pt/`, `i18n/de/`); die übrigen Sprachen kommen nach und nach hinzu. Setze `AWS_IOT_LANG`, um die interaktive Abfrage zu überspringen; fehlt eine Übersetzung, fallen die Skripte Meldung für Meldung auf Englisch zurück.

## 🧹 Ressourcenbereinigung

**Denk daran, nach dem Abschluss aufzuräumen, um laufende Gebühren zu vermeiden.** Das Bereinigungsskript ist **standardmäßig nicht destruktiv** (Probelauf) und entfernt nur Ressourcen, die zum Benennungsmuster dieses Themas passen, in Abhängigkeitsreihenfolge.

```bash
# Vorschau (löscht nichts)
python3 scripts/cleanup_script.py

# In deiner Hauptregion löschen (hält vor CAs, Templates und Zertifikaten für eine Bestätigung an)
python3 scripts/cleanup_script.py --execute

# Die zweite Region löschen, die Multi-Account Registration verwendet
python3 scripts/cleanup_script.py --execute --mar-region us-west-2

# Zum Schluss den Stack der Basisinfrastruktur entfernen (Rollen, Lambdas, Protokollgruppen)
aws cloudformation delete-stack --stack-name ws-aws-iot-dm-adv-prov-base
```

## 🛠️ Fehlerbehebung

- **Anmeldeinformationen / Region**: Konfiguriere sie über `aws configure`, Umgebungsvariablen oder IAM-Rollen; MAR-Befehle brauchen in `--region` eine gültige zweite Region.
- **„Stack ... does not exist“ oder Rolle/Funktion nicht gefunden**: Stelle den Stack der Basisinfrastruktur bereit (siehe oben), bevor du die Methodenskripte ausführst.
- **`AccessDenied` bei IAM/Lambda**: Der Basis-Stack braucht `CAPABILITY_NAMED_IAM`; die ausführende Identität braucht die Berechtigung, Rollen zu erstellen und sie an `iot.amazonaws.com` / `lambda.amazonaws.com` zu übergeben.
- **Zertifikat hängt in `PENDING_ACTIVATION` fest**: Das Provisioning-Template bzw. die Registrierungsrolle ist fehlgeschlagen; suche in CloudTrail nach der verweigerten Aktion (der JITP-Abschnitt der Workshop-Inhalte enthält ein vollständiges Runbook).
- **Debug-Modus**: Übergib `--debug` (oder beantworte die Debug-Abfrage), um alle API-Aufrufe und -Antworten auszugeben.

## 📁 Projektstruktur

```
sample-aws-iot-device-management-learning-path-advanced/
├── infrastructure/
│   └── provisioning-base.yaml            # Basisinfrastruktur: IAM-Rollen + Lambda-Gerüste (einmal bereitstellen)
├── scripts/                              # Ausführbare Skripte für Benutzer
│   ├── register_custom_ca.py
│   ├── manage_jit_provisioning.py
│   ├── fleet_provision_by_claim.py
│   ├── fleet_provision_trusted_user.py
│   ├── manage_multi_account_registration.py
│   ├── mqtt_connect.py
│   ├── rotate_certificate.py
│   ├── certificate_manager.py
│   └── cleanup_script.py
├── iot_helpers/                          # Internes Helper-Paket
│   └── utils/                            # Konstrukte der Steuerungs- + Geräteebene
│       ├── api_helpers.py                # Wrapper safe_api_call
│       ├── device_simulator.py           # MQTT-Konstrukt DeviceConnection
│       └── fleet_provisioning_templates/ # JSON für Provisioning-Template + Richtlinie
├── lambdas/                              # Lambda-Code, der in den Gerüsten bereitgestellt wird
│   ├── jitr_registration_handler.py
│   ├── pre_provisioning_hook.py
│   ├── certificate_provider_signer.py
│   ├── rotation_handler.py                # Abschnitt 6 — prüft + signiert die CSR, nimmt das alte Zertifikat außer Betrieb
│   └── rotation_enroller.py               # Abschnitt 6 — nur als Referenz, nicht bereitgestellt: macht aus einem
│                                          #   Altersbefund (finding) von Device Defender eine Aufnahme in die Rotation
├── i18n/                                 # Internationalisierung (Meldungskataloge + Loader)
├── requirements.txt                      # Python-Abhängigkeiten (beide Ebenen)
└── README.md
```

## 📄 Lizenz

MIT No Attribution License.

## 🏷️ Tags

`aws` `aws-iot` `device-management` `device-provisioning` `fleet-provisioning` `jitp` `jitr` `multi-account-registration` `python` `iot`
