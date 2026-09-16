#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
AWS IoT Core certificate provider — self-managed certificate signing (AWS Lambda).

This is the signing function for the OPTIONAL "certificate provider" lab in
Module 3, "Fleet Provisioning by Claim". An AWS IoT Core *certificate provider*
references this Lambda function; once the provider exists, every fleet-provisioning
``CreateCertificateFromCsr`` call in the account invokes THIS function with the
device's Certificate Signing Request (CSR) and uses whatever certificate it
returns — instead of AWS IoT Core signing the CSR with the Amazon CA.

    device --CSR--> AWS IoT Core --{certificateSigningRequest}--> THIS Lambda
                                 <--{certificatePem}------------- signs with a CA you control

Input event delivered by AWS IoT Core (see the AWS IoT Core Developer Guide,
"Self-managed certificate signing using AWS IoT Core certificate provider"):

    {
      "certificateSigningRequest": "<PEM CSR>",
      "principalId": "<id of the principal that connected>",
      "clientId": "<MQTT client id of the requesting device>"
    }

Return contract:

    { "certificatePem": "<PEM of the signed client certificate>" }

Hard rules AWS IoT Core enforces on the returned certificate:

- It MUST carry the SAME subject name and the SAME public key as the CSR.
  (This function copies both straight from the CSR, so that always holds.)
- The function MUST return within 5 seconds.
- The function MUST be in the same AWS account and Region as the certificate
  provider, and AWS IoT Core must be granted permission to invoke it.

WHY A SIMULATED CA (READ THIS)
------------------------------
To keep the workshop free of charge, this function signs with a **simulated
private CA that it generates in memory at cold start** — there is *no* AWS
Private Certificate Authority behind it (AWS Private CA bills per CA per month
plus per issued certificate). That trade-off is deliberate and is called out in
the module content. The CA private key therefore:

- lives only in this function's memory (it is NOT committed anywhere), and
- is regenerated whenever the function cold-starts — which is fine for a
  single-session lab but is exactly what you must NOT do in production.

In production you would keep the CA private key in an HSM-backed authority such
as **AWS Private CA** and call ``acm-pca:IssueCertificate`` here instead (see the
"own-account AWS Private CA variant" in the module content). The rest of the flow
— the certificate provider, the ``CreateCertificateFromCsr`` path, and the device
experience — is identical; only the signing backend changes.

This function is pre-created as a fail-closed skeleton by
``provisioning-base.yaml`` under the name
``ws-aws-iot-dm-adv-prov-cert-provider-signer`` (handler ``index.handler``).
Because it needs the third-party ``cryptography`` library, you deploy this real
code WITH its dependencies bundled (see the module content):

    mkdir -p build && cp ../lambdas/certificate_provider_signer.py build/index.py
    pip install --target build cryptography
    (cd build && zip -qr ../signer.zip .)
    aws lambda update-function-code \\
      --function-name ws-aws-iot-dm-adv-prov-cert-provider-signer \\
      --zip-file fileb://signer.zip

Build the zip on a Linux x86_64 host (the VS Code Server, or WSL2/Linux on your
own machine): ``cryptography`` ships a native wheel that must match the Lambda
runtime's Linux x86_64 architecture.
"""

import datetime
import logging

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Subject of the simulated manufacturing CA. This is what you will see as the
# certificate ISSUER after provisioning — proof the device certificate was signed
# by *your* CA and not by the Amazon CA.
_CA_COMMON_NAME = "AnyCompany Simulated Manufacturing CA"
_CA_ORGANIZATION = "AnyCompany"

# Issued device certificates are valid for one year, matching the AWS Private CA
# example in the AWS documentation. Tune this to your device's service life in a
# real self-managed authority.
_CERT_VALIDITY_DAYS = 365

# Cold-start cache: the simulated CA (private key + self-signed CA certificate).
# Generated once per execution environment and reused across warm invocations, so
# every certificate the function issues in a session chains to the same issuer.
_CA_KEY = None
_CA_CERT = None


def _get_ca():
    """Return the simulated CA (key, cert), generating it once per cold start.

    Uses an EC P-256 CA so key generation is effectively instant, keeping the
    function comfortably inside the 5-second certificate-provider budget even on
    a cold start. The private key is never persisted or logged.
    """
    global _CA_KEY, _CA_CERT
    if _CA_KEY is not None and _CA_CERT is not None:
        return _CA_KEY, _CA_CERT

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, _CA_ORGANIZATION),
        x509.NameAttribute(NameOID.COMMON_NAME, _CA_COMMON_NAME),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)  # self-signed root
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _CA_KEY, _CA_CERT = ca_key, ca_cert
    logger.info("Initialized simulated manufacturing CA: %s", _CA_COMMON_NAME)
    return _CA_KEY, _CA_CERT


def _sign_csr(csr_pem: str) -> str:
    """Sign a CSR with the simulated CA and return the client certificate PEM.

    The issued certificate copies the CSR's subject and public key verbatim (an
    AWS IoT Core requirement) and is signed by the simulated CA, so its issuer is
    the CA above rather than the Amazon CA.
    """
    csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    if not csr.is_signature_valid:  # nosemgrep: is-function-without-parentheses -- cryptography lib property, not a method
        raise ValueError("CSR signature is not valid")

    ca_key, ca_cert = _get_ca()
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)              # same subject as the CSR (required)
        .issuer_name(ca_cert.subject)           # signed by the simulated CA
        .public_key(csr.public_key())           # same public key as the CSR (required)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=True, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")


def handler(event, context):
    """Entry point invoked by AWS IoT Core for each CreateCertificateFromCsr call."""
    client_id = event.get("clientId", "")
    principal_id = event.get("principalId", "")
    logger.info(
        "Certificate provider invoked (clientId=%s, principalId=%s)",
        client_id, principal_id,
    )

    csr_pem = event.get("certificateSigningRequest")
    if not csr_pem:
        # Fail closed: no CSR means nothing to sign. Raising rejects the
        # provisioning request rather than returning an invalid certificate.
        raise ValueError("Missing 'certificateSigningRequest' in event")

    certificate_pem = _sign_csr(csr_pem)
    logger.info("Issued a certificate signed by the simulated manufacturing CA")
    return {"certificatePem": certificate_pem}
