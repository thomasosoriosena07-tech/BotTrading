import pytest

from bottrading.config import BacktestConfig


def test_defaults():
    config = BacktestConfig(initial_capital=1000)
    assert config.commission_rate == 0.001
    assert config.slippage_rate == 0.0005
    assert config.max_position_fraction == 1.0


@pytest.mark.parametrize("capital", [0, -1, float("nan"), float("inf"), True, "1000"])
def test_invalid_capital_is_rejected(capital):
    with pytest.raises(ValueError, match="initial_capital"):
        BacktestConfig(initial_capital=capital)


@pytest.mark.parametrize("field", ["commission_rate", "slippage_rate"])
@pytest.mark.parametrize("value", [-0.001, 1, 2, float("nan"), None])
def test_invalid_rates_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        BacktestConfig(initial_capital=1000, **{field: value})


@pytest.mark.parametrize("value", [0, -0.5, 1.01, float("inf"), "1"])
def test_invalid_position_fraction_is_rejected(value):
    with pytest.raises(ValueError, match="max_position_fraction"):
        BacktestConfig(initial_capital=1000, max_position_fraction=value)


def test_zero_costs_are_allowed():
    config = BacktestConfig(1000, commission_rate=0, slippage_rate=0)
    assert config.commission_rate == 0 and config.slippage_rate == 0
