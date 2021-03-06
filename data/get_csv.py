import requests
import pandas as pd
import os
from datetime import datetime

from trading_common.utilities.utils import parse_args, load_credentials

args = parse_args()
load_credentials(args.credentials)


def get_av_csv(symbol, csv_dir, key, full=False, interval=None,):
    print(f"Getting symbol: {symbol}")
    if interval != None:
        if interval not in ['1min', '5min', '15min', '30min', '60min']:
            raise Exception(
                "Interval has to be one of the following options (string):\n'1min', '5min', '15min', '30min', '60min'")

        if full:
            url = "https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=" + \
                symbol + "&interval=" + interval + "&outputsize=full" + "&apikey=" + key
        else:
            url = "https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=" + \
                symbol + "&interval=" + interval + "&apikey=" + key

        if not os.path.exists(f"{interval}"):
            os.mkdir(f"{interval}")

        filepath = f"./{interval}/{symbol}.csv"
    else:
        if full:
            url = "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=" + \
                symbol + "&outputsize=full" + "&apikey=" + key
        else:
            url = "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=" + \
                symbol + "&apikey=" + key

        if not os.path.exists(csv_dir):
            os.mkdir(csv_dir)

        filepath = csv_dir + f"/{symbol}.csv"

    parsed_data = requests.get(url).json()
    df = pd.DataFrame.from_dict(
        parsed_data['Time Series (Daily)'], orient='index')
    df = df.iloc[::-1]  # reverse from start to end instead of end to start
    df.columns = ["open", "high", "low", "close", "volume"]
    merge_n_save(filepath, df)


def get_tiingo_eod(ticker, full: bool, key):
    headers = {
        'Content-Type': 'application/json'
    }
    if full:
        start_date = "2000-1-1"
        end_date = datetime.today().strftime('%Y-%m-%d')
    else:
        start_date = "2020-1-1"
        end_date = datetime.today().strftime('%Y-%m-%d')

    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_date}&endDate={end_date}&resampleFreq=daily&token={key}"

    requestResponse = requests.get(url, headers=headers)
    if requestResponse.ok:
        json_df = requestResponse.json()
        try:
            df = pd.DataFrame(json_df)
            df['date'] = df['date'].apply(
                lambda x: x.replace("T00:00:00.000Z", ""))
            df.index = df['date']
            df = df.drop("date", axis=1)
            df = df[["open", "high", "low", "close", "volume"]]
            merge_n_save(ticker, df)
        except Exception as e:
            print(json_df)
            print(e)


def merge_n_save(ticker, df):
    daily_fp = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data', 'daily')
    filepath = os.path.join(daily_fp, ticker)
    if not os.path.exists(daily_fp):
        os.makedirs(daily_fp)
    if os.path.exists(os.path.join(daily_fp, ticker)):
        # merge data
        existing_df = pd.read_csv(filepath, index_col=0)
        df = pd.concat([existing_df, df])
        df = df[~df.index.duplicated(keep='last')]
        df.sort_index(inplace=True)
        assert df.index.nunique() == df.index.size
    df.to_csv(filepath)
    print("Data is stored at {}".format(filepath))


def refresh_data(tiingo_key):
    from trading_common.utilities.utils import remove_bs
    with open(f"{os.path.dirname(__file__)}/dow_stock_list.txt", "r") as fin:
        stock_list = fin.readlines()
    dow_stock_list = list(map(remove_bs, stock_list))

    with open(f"{os.path.dirname(__file__)}/snp500.txt", "r") as fin:
        stock_list = fin.readlines()
    snp500 = list(map(remove_bs, stock_list))

    for ticker in snp500[300:]:
        get_tiingo_eod(ticker, f"{ticker}.csv", full=True,
                       key=tiingo_key)


refresh_data(os.environ["TIINGO_API"])