"""Infer a coarse region locally from an address supplied by the reverse proxy."""

import ipaddress
import json
import unicodedata
from pathlib import Path


def name_key(name):
    name = unicodedata.normalize('NFKD', name.casefold())
    return ''.join(char for char in name if char.isalnum())


def index_chinese_names():
    data = json.loads(Path(__file__).with_name('china_regions.json').read_text(encoding='utf-8'))
    provinces = {}
    cities_by_province = {}
    cities_without_province = {}
    for province, region in data.items():
        province_names = [name_key(name) for name in [province] + region['aliases']]
        provinces.update((name, province) for name in province_names)
        city_names = {}
        cities_by_province[province] = city_names
        if not region['cities']:
            for name in province_names:
                cities_without_province.setdefault(name, set()).add(province)
        for city, aliases in region['cities'].items():
            for alias in [city] + aliases:
                key = name_key(alias)
                city_names.setdefault(key, set()).add(city)
                cities_without_province.setdefault(key, set()).add(province + city)
    return provinces, cities_by_province, cities_without_province


PROVINCES, CITIES_BY_PROVINCE, CITIES_WITHOUT_PROVINCE = index_chinese_names()
SPECIAL_REGIONS = {'HK': '香港特别行政区', 'MO': '澳门特别行政区', 'TW': '台湾省'}


def localized_names(record):
    names = record.get('names', {})
    return [names[lang] for lang in ('zh-CN', 'en') if names.get(lang)]


def city_match(cities, names):
    for name in names:
        key = name_key(name)
        matches = cities.get(key)
        if not matches and key.endswith('city'):
            matches = cities.get(key[:-4])
        if matches and len(matches) == 1:
            return next(iter(matches))
    return None


def chinese_region(province_names, city_names, country=None):
    province = SPECIAL_REGIONS.get(country)
    if province is None:
        for name in province_names:
            province = PROVINCES.get(name_key(name))
            if province:
                break
    if province:
        return province + (city_match(CITIES_BY_PROVINCE[province], city_names) or '')
    if country == 'CN':
        return city_match(CITIES_WITHOUT_PROVINCE, city_names)
    return None


def localize_saved_region(region):
    """Convert old records only when the province identifies a Chinese region."""
    province, separator, city = region.partition(' / ')
    return chinese_region([province], [city] if separator else []) or region


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
    province_names = localized_names(subdivisions[0]) if subdivisions else []
    city_names = localized_names(record.get('city', {}))
    country = record.get('country', {}).get('iso_code')
    if country == 'CN' or country in SPECIAL_REGIONS:
        return chinese_region(province_names, city_names, country)
    province = province_names[0] if province_names else None
    city = city_names[0] if city_names else None
    return ' / '.join(dict.fromkeys(name for name in (province, city) if name)) or None
