"""出站 URL 的 SSRF 防护。

动态模型发现会用调用方提供的 base_url 发起服务端 GET（见 catalog.py），
而后端经 Cloudflare Tunnel 暴露在公网、同机又跑着仅 loopback 可达的内部服务
（wxpay/admin/后端自身）。若不校验，攻击者可借此让服务器探测内网或云元数据
（169.254.169.254）。本模块在发起请求前校验 URL：

1. scheme 仅允许 http/https（挡掉 file://、gopher:// 等 SSRF 向量）；
2. 解析主机名，若任一解析 IP 属于 私有/环回/链路本地/保留/组播/未指定 段则拒绝；
3. 调用方（catalog）保持 follow_redirects=False，避免 3xx 跳转绕过本校验。

局限：DNS rebinding（解析后到真正连接之间 DNS 变化）无法完全杜绝，但对本应用的
威胁级别，getaddrinfo 预校验是相称的防御。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """目标 URL 未通过 SSRF 安全校验。"""


def _resolve_host(host: str, port: int | None) -> list[str]:
    """把主机名解析为 IP 字符串列表（A + AAAA）。"""
    infos = socket.getaddrinfo(host, port or 0, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _is_blocked_ip(ip_str: str, *, allow_loopback: bool = False) -> bool:
    """判断 IP 是否落在禁止的内部/特殊网段。

    allow_loopback=True 时，环回地址（127.x.x.x / ::1）被放行；
    私有/链路本地/保留/组播/未指定段在任何情况下都拒绝。
    """
    ip = ipaddress.ip_address(ip_str)
    if allow_loopback and ip.is_loopback:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global   # CGNAT(100.64/10) 等非全局段一并拦截
    )


def assert_safe_outbound_url(url: str, *, resolver=None, allow_loopback: bool = False) -> None:
    """校验出站 URL，不安全则抛 UnsafeURLError。

    resolver 可注入（测试用），签名 (host, port) -> list[str ip]。
    allow_loopback=True 允许环回地址（127.x / ::1），用于运营方配置的本地 SearXNG；
    其余受限段（私有/链路本地/保留/组播/未指定）仍拒绝，默认 False（既有行为不变）。
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"不支持的 URL scheme: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL 缺少主机名")

    resolve = resolver or _resolve_host
    try:
        ips = resolve(host, parsed.port)
    except OSError as exc:
        raise UnsafeURLError(f"无法解析主机 {host}：{exc}") from exc

    if not ips:
        raise UnsafeURLError(f"主机 {host} 未解析到任何 IP")

    for ip in ips:
        if _is_blocked_ip(ip, allow_loopback=allow_loopback):
            raise UnsafeURLError(f"URL 指向受限地址 {ip}（host={host}）")
