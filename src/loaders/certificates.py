"""Make the self-signed certificate the local test origin serves."""

import datetime
import ipaddress
import os
import socket

from .config import config
from .logging import get_logger

logger = get_logger("loaders.certificates")

LOOPBACK = (ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1"))


def _routed_address():
    """Return the address this machine would use to reach the local network.

    Connecting a UDP socket only fixes a route; no packet is ever sent. The
    target is TEST-NET-1 from RFC 5737, reserved for documentation and never
    routable, so nothing leaves the machine either way.

    This is the reliable half of the detection. A hostname often resolves to
    loopback alone, or on a machine with several adapters to whichever one the
    resolver happens to prefer, which need not be the one clients arrive on.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _local_addresses():
    """Return the names and addresses this machine answers on.

    Only needed for a wildcard bind. APP_HOST is then 0.0.0.0, which is not an
    address any client connects to: they reach the harness on a real address
    such as 192.168.1.50, and a certificate naming 0.0.0.0 covers none of them.

    Neither method here is exhaustive. A machine with more than one adapter —
    a laptop sharing a connection, a host on two subnets — may answer on an
    address that shows up in neither, and clients arriving on that address will
    be handed a certificate that does not cover them. Name it in CERT_HOSTS, or
    pass --cert-host, when that happens.
    """
    names, addresses = set(), set()
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    if hostname:
        names.add(hostname)
        try:
            for info in socket.getaddrinfo(hostname, None):
                addresses.add(info[4][0])
        except (socket.gaierror, OSError):
            logger.debug("Could not resolve %s to list this machine's addresses",
                         hostname)

    routed = _routed_address()
    if routed:
        addresses.add(routed)
    return names, addresses


def _wanted(host: str):
    """Return the (dns names, ip addresses) the certificate has to cover.

    A browser matches an IP literal in a URL against an iPAddress entry only:
    DNS:localhost does not cover https://127.0.0.1:8443, which is the URL the
    README and every example default to. Without the address here the browser
    rejects the certificate, and because a fetch gets no interstitial to click
    through, the page's own report fails with what looks like a CORS error.
    """
    names = {"localhost", "botlab.local"}
    addresses = set(LOOPBACK)

    candidates = [host] + [part.strip() for part in config.CERT_HOSTS.split(",")]
    if config.binds_wildcard:
        extra_names, extra_addresses = _local_addresses()
        names |= extra_names
        candidates += list(extra_addresses)

    for candidate in candidates:
        if not candidate or candidate in ("0.0.0.0", "::"):
            continue                       # a bind wildcard, never a destination
        try:
            addresses.add(ipaddress.ip_address(candidate))
        except ValueError:
            names.add(candidate)
    return names, addresses


def certificate_hosts():
    """Return the (names, addresses) the certificate covers, as strings.

    The entry point prints these, so a reader can see which URLs will work
    before a client is pointed at one.
    """
    names, addresses = _wanted(config.APP_HOST)
    return names, {str(address) for address in addresses}


def _san_entries(host: str):
    """Return the SubjectAlternativeName entries for this configuration."""
    from cryptography import x509

    names, addresses = _wanted(host)
    return ([x509.DNSName(name) for name in sorted(names)]
            + [x509.IPAddress(address) for address in
               sorted(addresses, key=lambda a: (a.version, str(a)))])


def _covers(cert_file: str, host: str) -> bool:
    """Return whether the stored certificate covers everything it needs to.

    A certificate generated for a different APP_HOST is worse than none: it
    loads, then fails in the browser for a reason that reads as CORS. Comparing
    the whole required set rather than one host also means a laptop that moved
    to another network regenerates automatically, because the address clients
    now reach it on is no longer in the certificate.
    """
    from cryptography import x509

    try:
        with open(cert_file, "rb") as handle:
            certificate = x509.load_pem_x509_certificate(handle.read())
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False

    names, addresses = _wanted(host)
    stored_names = set(san.get_values_for_type(x509.DNSName))
    stored_addresses = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    missing = (names - stored_names) | ({str(a) for a in addresses} - stored_addresses)
    if missing:
        logger.debug("The stored certificate is missing %s", ", ".join(sorted(missing)))
    return not missing


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
