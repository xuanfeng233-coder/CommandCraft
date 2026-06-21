"""冒烟测试：验证 pytest 环境与 backend 包可导入。"""


def test_harness_runs():
    assert True


async def test_async_harness_runs():
    # asyncio_mode=auto：无需 @pytest.mark.asyncio
    assert True


def test_backend_importable():
    import backend.config as config

    assert hasattr(config, "MODEL_TEMPERATURE")
