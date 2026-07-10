# scoring.py
def calc_score(is_25ma_touch, is_box_bottom_touch, rsi, macd, signal):
    score = 0
    if is_25ma_touch:
        score += 30
    if is_box_bottom_touch:
        score += 30
    if rsi <= 30:
        score += 20
    elif rsi <= 40:
        score += 10
    if macd > signal:
        score += 20
    return score
