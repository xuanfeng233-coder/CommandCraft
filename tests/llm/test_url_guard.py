import pytest

from backend.llm.url_guard import UnsafeURLError, assert_safe_outbound_url


def _resolver(*ips):
    def resolve(host, port):
        return list(ips)

    return resolve


def test_allows_public_https():
    # 解析到公网 IP → 放行（不抛）
    assert_safe_outbound_url(
        "https://api.deepseek.com/v1/models", resolver=_resolver("1.2.3.4")
    )


def test_rejects_non_http_scheme():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("file:///etc/passwd", resolver=_resolver("1.2.3.4"))
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("gopher://x/_", resolver=_resolver("1.2.3.4"))


def test_rejects_missing_host():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https:///models", resolver=_resolver("1.2.3.4"))


def test_rejects_loopback():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/models", resolver=_resolver("127.0.0.1"))
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/models", resolver=_resolver("::1"))


def test_rejects_link_local_metadata():
    # 云元数据地址 169.254.169.254
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/models", resolver=_resolver("169.254.169.254")
        )


def test_rejects_private_ranges():
    for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.1"):
        with pytest.raises(UnsafeURLError):
            assert_safe_outbound_url("http://x/models", resolver=_resolver(ip))


def test_rejects_unspecified():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/models", resolver=_resolver("0.0.0.0"))


def test_rejects_if_any_resolved_ip_blocked():
    # 一个公网 + 一个环回（DNS rebinding 式）→ 仍拒绝
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/models", resolver=_resolver("1.2.3.4", "127.0.0.1")
        )


def test_resolver_failure_is_unsafe():
    def boom(host, port):
        raise OSError("nxdomain")

    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://nope.invalid/models", resolver=boom)


def test_default_resolver_blocks_ip_literal():
    # 用真实默认 resolver（IP 字面量无需网络）：环回字面量被拒
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://127.0.0.1:8003/v1/models")


def test_allow_loopback_permits_127():
    # allow_loopback=True：环回放行（用于运营方配置的本地 SearXNG）
    assert_safe_outbound_url(
        "http://127.0.0.1:8888/search", resolver=_resolver("127.0.0.1"), allow_loopback=True
    )


def test_allow_loopback_still_blocks_private():
    # 即便 allow_loopback，私有/链路本地仍拒绝
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/search", resolver=_resolver("10.0.0.1"), allow_loopback=True
        )
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/search", resolver=_resolver("169.254.169.254"), allow_loopback=True
        )


def test_default_still_blocks_loopback():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/m", resolver=_resolver("127.0.0.1"))
