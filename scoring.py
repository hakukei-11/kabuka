# scoring.py

LOW20_MACD_GOLDEN_CROSS_BONUS = 10

def calc_rebound_score(
    is_25ma_touch: bool,
    is_box_bottom_touch: bool,
    rsi: float,
    macd: float,
    signal: float,
    close_today: float,
    close_yesterday: float,
) -> int:
    """
    反発候補の総合スコアを計算する。

    スコアの仕様:
    - 25MA付近かつ終値上昇: 40点
    - 25MA付近かつ終値下落: 20点
    - 25MA付近かつ横ばい: 30点
    - 20日安値付近かつ終値上昇: 40点
    - 20日安値付近かつ終値下落・横ばい: 20点
    - RSI 25以下: 25点
    - RSI 30以下: 20点
    - RSI 40以下: 10点
    - MACDがシグナルを上回る: 20〜30点
    - MACDがシグナルを下回る直後: 5点
    """
    score = 0

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
        if abs(macd - signal) < 0.1:
            score += 30
        else:
            score += 20
    elif abs(signal - macd) < 0.1:
        score += 5

    # 過去5年の前半・後半の両方で、組み合わせ条件の有効性を確認済み。
    if is_box_bottom_touch and macd > signal:
        score += LOW20_MACD_GOLDEN_CROSS_BONUS

    return score
