import pytest

from bottrading.strategy import (
    Signal,
    crossover_signals,
    donchian_signals,
    simple_moving_average,
    trend_filter_signals,
    validate_windows,
)

B, S, H = Signal.BUY, Signal.SELL, Signal.HOLD

# Serie sintética determinista: bajada, subida, bajada.
CLOSES = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 7, 6]


def test_sma_values_and_warmup():
    assert simple_moving_average([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_sma_window_one_is_identity():
    assert simple_moving_average([3.0, 1.0], 1) == [3.0, 1.0]


def test_sma_shorter_than_window_is_all_none():
    assert simple_moving_average([1, 2], 3) == [None, None]


@pytest.mark.parametrize("window", [0, -1, 1.5, True])
def test_sma_rejects_invalid_window(window):
    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], window)


def test_crossover_signals_on_synthetic_series():
    # fast=2, slow=3. Diferencia fast-slow por índice (desde i=2):
    # 2..5 negativa, 6..10 positiva, 11..14 negativa.
    signals = crossover_signals(CLOSES, fast=2, slow=3)
    fast_ma = simple_moving_average(CLOSES, 2)
    slow_ma = simple_moving_average(CLOSES, 3)
    # Comprobación independiente de los índices esperados:
    # i=5: fast 6.5 vs slow 6.67 -> abajo; i=6: fast 7.5 vs slow 7.0 -> arriba.
    assert fast_ma[5] < slow_ma[5] and fast_ma[6] > slow_ma[6]
    # i=10: fast 10.5 vs slow 10.33 -> arriba; i=11: fast 9.5 vs slow 10 -> abajo.
    assert fast_ma[10] > slow_ma[10] and fast_ma[11] < slow_ma[11]
    expected = [H] * len(CLOSES)
    expected[6] = B
    expected[11] = S
    assert signals == expected


def test_no_signals_during_warmup():
    signals = crossover_signals(CLOSES, fast=2, slow=5)
    assert signals[:5] == [H] * 5


def test_flat_series_has_no_signals():
    assert crossover_signals([5.0] * 20, fast=3, slow=7) == [H] * 20


def test_cross_from_below():
    closes = [3, 2, 1, 2, 3]  # fast=1 (el cierre), slow=3
    # i=3: fast 2 > slow 1.67, antes 1 < 2 -> BUY
    assert crossover_signals(closes, fast=1, slow=3) == [H, H, H, B, H]


def test_cross_through_a_tie_signals_once_after_the_tie():
    # fast=1, slow=2. diff: i1 -0.5, i2 0 (empate), i3 +0.5 -> BUY en i3.
    assert crossover_signals([2, 1, 1, 2], fast=1, slow=2) == [H, H, H, B]


def test_touch_from_below_and_back_is_not_a_signal():
    # diff: i1 -0.5, i2 0 (toca), i3 -0.25 (vuelve abajo) -> sin señales.
    assert crossover_signals([2, 1, 1, 0.5], fast=1, slow=2) == [H] * 4


def test_touch_from_above_and_back_is_not_a_signal():
    # diff: i1 +0.5, i2 0 (toca), i3 +0.5 (vuelve arriba) -> sin señales.
    assert crossover_signals([1, 2, 2, 3], fast=1, slow=2) == [H] * 4


def test_rise_after_flat_start_is_a_buy():
    # Empate desde el inicio y luego por encima -> BUY.
    assert crossover_signals([1, 1, 1, 2], fast=1, slow=2) == [H, H, H, B]


def test_drop_after_flat_start_is_a_sell():
    # Simétrico al caso anterior: empate al final del calentamiento y
    # luego por debajo -> SELL (el motor la ignora si no hay posición).
    assert crossover_signals([2, 2, 2, 1], fast=1, slow=2) == [H, H, H, S]


def test_already_above_at_start_is_not_a_buy():
    # Tendencia alcista desde el inicio: no hay cruce, no hay BUY.
    assert crossover_signals([1, 2, 3, 4, 5], fast=1, slow=2) == [H] * 5


def test_series_shorter_than_slow_window():
    assert crossover_signals([1.0, 2.0], fast=1, slow=5) == [H, H]


def test_empty_series():
    assert crossover_signals([], fast=1, slow=2) == []


def test_signals_do_not_use_future_data():
    # Sin look-ahead: la señal en i no cambia al añadir velas posteriores.
    full = crossover_signals(CLOSES, fast=2, slow=4)
    for k in range(len(CLOSES) + 1):
        assert crossover_signals(CLOSES[:k], fast=2, slow=4) == full[:k]


@pytest.mark.parametrize(
    ("fast", "slow", "message"),
    [
        (5, 5, "menor que slow"),
        (10, 5, "menor que slow"),
        (0, 5, ">= 1"),
        (2.0, 5, "entero"),
        (True, 5, "entero"),
    ],
)
def test_invalid_windows_are_rejected(fast, slow, message):
    with pytest.raises(ValueError, match=message):
        validate_windows(fast, slow)


# --- estrategias adicionales (T015) ---------------------------------------------------


def test_trend_filter_is_price_versus_its_average():
    closes = [5, 4, 3, 4, 6, 7, 5, 3]
    # Media de 3: i2=4, i3=3.67, i4=4.33, i5=5.67, i6=6, i7=5.
    # Cierre - media: i2 -1 | i3 +0.33 (BUY) | i4..i5 + | i6 -1 (SELL) | i7 -2.
    assert trend_filter_signals(closes, 3) == [H, H, H, B, H, H, S, H]


def test_trend_filter_rejects_window_one():
    with pytest.raises(ValueError, match="menor que slow"):
        trend_filter_signals([1, 2, 3], 1)


def test_donchian_breakouts():
    closes = [10, 11, 12, 11, 13, 12, 9, 10, 14]
    # entry=3: compra si supera el máximo de los 3 cierres anteriores.
    # exit=2: vende si cae bajo el mínimo de los 2 anteriores.
    # i=3: 11 vs max(10,11,12)=12 no; vs min(11,12)=11 no -> H
    # i=4: 13 > 12 -> B; i=5: 12 vs max 13 no, min(11,13)=11 no -> H
    # i=6: 9 < min(13,12) -> S; i=7: 10 vs max(13,12,9) no, min(12,9)=9 no -> H
    # i=8: 14 > max(12,9,10) -> B
    assert donchian_signals(closes, 3, 2) == [H, H, H, H, B, H, S, H, B]


def test_donchian_buy_needs_only_entry_warmup():
    # Revisión de Codex: con entry < exit, la compra no espera a exit.
    closes = list(range(1, 12))  # siempre nuevos máximos
    signals = donchian_signals(closes, 2, 5)
    assert signals[:2] == [H] * 2
    assert signals[2:] == [B] * 9


def test_donchian_sell_needs_only_exit_warmup():
    closes = list(range(11, 0, -1))  # siempre nuevos mínimos
    signals = donchian_signals(closes, 5, 2)
    assert signals[:2] == [H] * 2
    assert signals[2:] == [S] * 9


def test_donchian_equal_close_is_not_a_breakout():
    assert donchian_signals([5, 5, 5, 5], 2, 2) == [H] * 4


@pytest.mark.parametrize(("entry", "exit"), [(0, 2), (2, 0), (1.5, 2), (True, 2)])
def test_donchian_rejects_invalid_windows(entry, exit):
    with pytest.raises(ValueError):
        donchian_signals([1, 2, 3], entry, exit)


@pytest.mark.parametrize(
    "signal_function",
    [
        lambda closes: trend_filter_signals(closes, 4),
        lambda closes: donchian_signals(closes, 3, 2),
    ],
)
def test_new_strategies_do_not_use_future_data(signal_function):
    # Igual que para el cruce: cada prefijo da las mismas señales.
    closes = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 7, 6, 8, 12, 11]
    full = signal_function(closes)
    for k in range(len(closes) + 1):
        assert signal_function(closes[:k]) == full[:k]
