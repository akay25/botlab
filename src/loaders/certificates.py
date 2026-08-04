"""Make the self-signed certificate the local test origin serves."""

import datetime
import ipaddress
import os

from .config import config
from .logging import get_logger

logger = get_logger("loaders.certificates")

LOOPBACK = (ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1"))


def _san_entries(host: str):
    """Return every name and address the certificate has to cover.

    A browser matches an IP literal in a URL against an iPAddress entry only:
    DNS:localhost does not cover https://127.0.0.1:8443, which is the URL the
    README and every example default to. Without the address here the browser
    rejects the certificate, and because a fetch gets no interstitial to click
    through, the page's own report fails with what looks like a CORS error.
    """
    from cryptography import x509

    entries = [x509.DNSName("localhost"), x509.DNSName("botlab.local")]
    entries += [x509.IPAddress(address) for address in LOOPBACK]

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host and host not in ("localhost", "botlab.local"):
            entries.append(x509.DNSName(host))
    else:
        if address not in LOOPBACK:
            entries.append(x509.IPAddress(address))
    return entries


def _covers(cert_file: str, host: str) -> bool:
    """Return whether the stored certificate is valid for the host we serve.

    A certificate generated for a different APP_HOST is worse than none: it
    loads, then fails in the browser for a reason that reads as CORS.
    """
    from cryptography import x509

    try:
        with open(cert_file, "rb") as handle:
            certificate = x509.load_pem_x509_certificate(handle.read())
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host in san.get_values_for_type(x509.DNSName)
    return address in san.get_values_for_type(x509.IPAddress)


def ensure_certificate() -> None:
    stored = os.path.exists(config.cert_file) and os.path.exists(config.key_file)
    if stored and _covers(config.cert_file, config.APP_HOST):
        return
    if stored:
        logger.warning(
            "The stored certificate does not cover %s. A browser rejects it, and the "
            "task page's own fetch then fails with what reads as a CORS error. "
            "Generating one that covers it; accept the new certificate in your browser.",
            config.APP_HOST)

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
            x509.SubjectAlternativeName(_san_entries(config.APP_HOST)),
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
