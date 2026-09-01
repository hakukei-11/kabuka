# sectors.py

"""対象銘柄の業種分類を固定定義する。"""

from collections.abc import Iterable


def _create_sector_map(groups: dict[str, Iterable[str]]) -> dict[str, str]:
    """業種ごとの銘柄一覧から、銘柄コードをキーとする辞書を作る。"""
    return {
        ticker: sector
        for sector, tickers in groups.items()
        for ticker in tickers
    }


SECTOR_BY_TICKER = _create_sector_map(
    {
        "情報技術・半導体": [
            "8035.T", "6861.T", "6902.T", "6981.T", "6594.T", "7741.T",
            "3861.T", "3863.T", "5214.T", "5802.T", "5803.T", "6503.T",
            "6504.T", "6506.T", "6645.T", "6674.T", "6723.T", "6752.T",
            "6754.T", "6762.T", "6770.T", "6841.T", "6857.T", "6954.T",
            "6971.T", "7731.T", "7733.T", "7751.T", "3697.T", "3993.T",
            "4385.T", "4443.T", "4478.T", "4480.T", "5032.T", "5246.T",
            "5253.T", "5595.T", "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG",
            "AVGO", "CSCO", "ACN", "TXN", "IBM", "INTC", "AMD", "QCOM",
            "AMAT", "ADBE", "NOW", "ORCL", "CRM", "PANW", "FTNT", "LRCX",
            "MU", "CRWD", "DDOG", "MDB", "NET", "PLTR", "SNOW", "SHOP",
        ],
        "金融": [
            "8306.T", "8316.T", "8308.T", "8411.T", "8591.T", "8766.T",
            "8769.T", "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "BLK",
            "SPGI", "GS", "MMC", "C",
        ],
        "ヘルスケア": [
            "4502.T", "4503.T", "4506.T", "4519.T", "4523.T", "4543.T",
            "4578.T", "UNH", "JNJ", "MRK", "ABBV", "PFE", "TMO", "DHR",
            "MDT", "ISRG", "REGN", "GILD", "VRTX", "BDX", "ZTS", "HCA",
        ],
        "生活必需品・小売": [
            "2502.T", "2503.T", "2914.T", "3382.T", "3092.T", "8113.T",
            "8267.T", "9983.T", "7974.T", "4661.T", "4901.T", "4911.T",
            "PG", "PEP", "KO", "COST", "WMT", "MCD", "SBUX", "EL", "MO",
            "CL", "MNST", "KDP", "ROST", "TJX",
        ],
        "資本財・輸送": [
            "6501.T", "8058.T", "8001.T", "8053.T", "9101.T", "9104.T",
            "9107.T", "5411.T", "5401.T", "3407.T", "3401.T", "5020.T",
            "5108.T", "5201.T", "5332.T", "5406.T", "5713.T", "5901.T",
            "6301.T", "6367.T", "6471.T", "6473.T", "6586.T", "7011.T",
            "7012.T", "7201.T", "7203.T", "7267.T", "7270.T", "8031.T",
            "8802.T", "9020.T", "9021.T", "9022.T", "UPS", "RTX", "CAT",
            "GE", "HON", "BA", "LMT", "FDX", "CSX", "NSC", "WM", "ETN",
            "EMR", "HD", "LOW", "DE", "TSLA", "PLD",
        ],
        "通信・サービス": [
            "9432.T", "9433.T", "6098.T", "9984.T", "T", "VZ", "META", "NFLX",
            "DIS", "AMZN", "ABNB", "BKNG", "MELI", "UBER", "MAR",
        ],
        "素材・エネルギー": [
            "4063.T", "4188.T", "4208.T", "4452.T", "5020.T", "5201.T", "XOM",
            "CVX", "LIN",
        ],
        "公益": ["NEE", "SO", "DUK", "AEP"],
    }
)


def get_sector(ticker: str) -> str:
    """銘柄コードに対応する固定業種を返す。"""
    return SECTOR_BY_TICKER.get(ticker, "その他")
