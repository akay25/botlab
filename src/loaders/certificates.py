"""Make the self-signed certificate the local test origin serves."""

import datetime
import os

from .config import config
from .logging import get_logger

logger = get_logger("loaders.certificates")


def ensure_certificate() -> None:
    if os.path.exists(config.cert_file) and os.path.exists(config.key_file):
        return

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    logger.info("Generating a self-signed certificate for the test origin")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "botlab.local")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("botlab.local"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with open(config.key_file, "wb") as handle:
        handle.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(config.cert_file, "wb") as handle:
        handle.write(certificate.public_bytes(serialization.Encoding.PEM))
