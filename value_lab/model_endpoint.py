"""Fixed public, loopback or explicitly pinned intranet model destinations."""
import ipaddress
from urllib.parse import urlsplit

from .core import ValidationError


def validate_endpoint(config):
    try:
        endpoint = urlsplit(config['endpoint'])
        port = endpoint.port
    except (TypeError, ValueError) as exc:
        raise ValidationError('Invalid model endpoint') from exc
    scope = config.get('network_scope', 'public')
    pins = config.get('allowed_addresses', [])
    if (scope not in ('public', 'local', 'intranet') or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.path not in ('', '/') or endpoint.scheme not in ('http', 'https')
            or (port is not None and not 1 <= port <= 65535)):
        raise ValidationError('Model endpoint must be one explicit origin')
    if not isinstance(pins, list) or len(pins) != len(set(pins)):
        raise ValidationError('Invalid address pins')
    try:
        addresses = [ipaddress.ip_address(value) for value in pins]
    except ValueError as exc:
        raise ValidationError('Address pins must be literal IP addresses') from exc
    if scope == 'public':
        if endpoint.scheme != 'https' or port not in (None, 443) or pins:
            raise ValidationError('Public gateway requires HTTPS port 443 without private pins')
        try:
            address = ipaddress.ip_address(endpoint.hostname)
        except ValueError:
            address = None
        if ((address is not None and not address.is_global) or '.' not in endpoint.hostname
                or endpoint.hostname.endswith(('.localhost', '.local', '.internal'))):
            raise ValidationError('Private endpoint requires explicit local/intranet scope')
    else:
        if not addresses or any(not allowed_address(a, scope) for a in addresses):
            raise ValidationError('Freeze exact local/intranet addresses; metadata/link-local destinations refused')
        if scope == 'intranet' and endpoint.scheme != 'https':
            raise ValidationError('Intranet models require HTTPS')
    return endpoint


def allowed_address(address, scope):
    if scope == 'public':
        return address.is_global
    if scope == 'local':
        return address.is_loopback
    networks = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7')
    return any(address in ipaddress.ip_network(network) for network in networks)
