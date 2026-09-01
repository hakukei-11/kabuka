# scoring.py

"""反発確度スコアの共通計算処理。"""


def calc_rebound_score(
    is_25ma_touch: bool,
    is_box_bottom_touch: bool,
    rsi: float,
    macd: float,
    signal: float,
    close_today: float,
    close_yesterday: float,
) -> int:
    """過去検証で確認した補正を含む反発確度スコアを計算する。

    基本配点:
    - 25MA付近かつ終値上昇・下落・横ばい: 40・20・30点
    - 20日安値付近かつ終値上昇・下落等: 40・20点
    - RSI 25以下・30以下・40以下: 25・20・10点
    - MACDがSignalを上回る: 20点（差0.1未満は30点）
    - MACDがSignalを下回り差0.1未満: 5点

    過去5年・20営業日・利確+2%の検証に基づく補正:
    - 20日安値タッチ、終値下落等、RSI25以下、MACD下向き: +5点
    - 25MAタッチ、RSI31-40、MACD上向き（差0.1以上）: -10点
    """
    score = 0
    macd_difference = abs(macd - signal)

    if is_25ma_touch:
        if close_today > close_yesterday:
            score += 40
        elif close_today < close_yesterday:
            score += 20
        else:
            score += 30

    if is_box_bottom_touch:
        if close_today > close_yesterday:
            score += 40
        else:
            score += 20

    if rsi <= 25:
        score += 25
    elif rsi <= 30:
        score += 20
    elif rsi <= 40:
        score += 10

    if macd > signal:
        if macd_difference < 0.1:
            score += 30
        else:
            score += 20
    elif macd_difference < 0.1:
        score += 5

    if (
        is_box_bottom_touch
        and close_today <= close_yesterday
        and rsi <= 25
        and macd <= signal
        and macd_difference >= 0.1
    ):
        score += 5

    if (
        is_25ma_touch
        and 30 < rsi <= 40
        and macd > signal
        and macd_difference >= 0.1
    ):
        score -= 10

    return score
