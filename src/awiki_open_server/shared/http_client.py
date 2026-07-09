from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from awiki_open_server.shared.errors import InvalidParams, NotFound


@dataclass(frozen=True)
class OutboundHttpPolicy:
    allowed_http_hosts: frozenset[str] = frozenset()
    timeout_seconds: int = 10
    not_found_message: str = "remote_resource_not_found"


def http_get_json_limited(url: str, max_bytes: int, *, policy: OutboundHttpPolicy | None = None) -> dict[str, Any]:
    policy = policy or OutboundHttpPolicy()
    validate_safe_url(url, allowed_http_hosts=policy.allowed_http_hosts)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=policy.timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status in {404, 410}:
                raise NotFound(policy.not_found_message)
            if status < 200 or status >= 300:
                raise InvalidParams("remote_resolution_failed", data={"url": url, "status": status})
            content_type = response.headers.get("content-type", "")
            if content_type and "json" not in content_type.lower():
                raise InvalidParams("remote_resolution_non_json", data={"url": url, "content_type": content_type})
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 410}:
            raise NotFound(policy.not_found_message) from exc
        raise InvalidParams("remote_resolution_failed", data={"url": url, "status": exc.code}) from exc
    except urllib.error.URLError as exc:
        raise NotFound("remote_resolution_failed", data={"url": url, "detail": str(exc)}) from exc
    if len(body) > max_bytes:
        raise InvalidParams("remote_resolution_response_too_large", data={"url": url, "max_bytes": max_bytes})
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise InvalidParams("remote_resolution_invalid_json", data={"url": url}) from exc
    if not isinstance(data, dict):
        raise InvalidParams("remote_resolution_must_be_object", data={"url": url})
    return data


def validate_safe_url(url: str, *, allowed_http_hosts: frozenset[str] = frozenset()) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise InvalidParams("https_url_required")
    host = parsed.hostname
    if not host:
        raise InvalidParams("url_host_required")
    if parsed.username or parsed.password:
        raise InvalidParams("url_userinfo_not_allowed")
    host = host.lower()
    if parsed.scheme == "http" and host not in allowed_http_hosts:
        raise InvalidParams("https_url_required")
    if host in allowed_http_hosts:
        return
    _reject_private_host(host)


def allowed_hosts_from_base_urls(*mappings: dict[str, str] | None) -> frozenset[str]:
    hosts: set[str] = set()
    for mapping in mappings:
        for base_url in (mapping or {}).values():
            parsed = urllib.parse.urlparse(base_url)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return frozenset(hosts)


def _reject_private_host(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
        if _ip_is_private(ip):
            raise InvalidParams("private_network_resolution_not_allowed")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NotFound("resolution_host_not_found", data={"host": host}) from exc
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _ip_is_private(ip):
            raise InvalidParams("private_network_resolution_not_allowed", data={"host": host, "address": address})


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
