"""Infer a coarse region locally from an address supplied by the reverse proxy."""

import ipaddress


def localized_name(record):
    names = record.get('names', {})
    return names.get('zh-CN') or names.get('en')


def lookup_region(reader, address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return None

    record = reader.get(str(ip)) or {}
    subdivisions = record.get('subdivisions', [])
    province = localized_name(subdivisions[0]) if subdivisions else None
    city = localized_name(record.get('city', {}))
    return ' / '.join(dict.fromkeys(name for name in (province, city) if name)) or None
