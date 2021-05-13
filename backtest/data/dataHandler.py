from backtest.broker import SimulatedBroker
import datetime
import os
import requests
import logging
import pandas as pd
from abc import ABC, abstractmethod
import alpaca_trade_api

from backtest.event import MarketEvent

NY = 'America/New_York'

def get_tiingo_endpoint(endpoint:str, args:str):
    return f"https://api.tiingo.com/tiingo/{endpoint}?{args}&token={os.environ['TIINGO_API']}"

class DataHandler(ABC):
    """
    The goal of a (derived) DataHandler object is to output a generated
    set of bars (OLHCVI) for each symbol requested. 

    This will replicate how a live strategy would function as current
    market data would be sent "down the pipe". Thus a historic and live
    system will be treated identically by the rest of the backtesting suite.
    """

    @abstractmethod
    def get_latest_bars(self, symbol, N=1):
        """
        Returns last N bars from latest_symbol list, or fewer if less
        are available
        """
        raise NotImplementedError("Should implement get_latest_bars()")

    @abstractmethod
    def update_bars(self,):
        """
        Push latest bar to latest symbol structure for all symbols in list
        """
        raise NotImplementedError("Should implement update_bars()")


class HistoricCSVDataHandler(DataHandler):
    """
    read CSV files from local filepath and prove inferface to
    obtain "latest" bar similar to live trading (drip feed)
    """

    def __init__(self, events, csv_dir, symbol_list, start_date, 
        end_date=None, fundamental:bool=False):
        """
        Args:
        - Event Queue on which to push MarketEvent information to
        - absolute path of the CSV files 
        - a list of symbols determining universal stocks
        """
        self.events = events ## a queue
        self.csv_dir = csv_dir
        self.symbol_list = symbol_list
        self.start_date = start_date
        if end_date != None:
            self.end_date = end_date
        else:
            self.end_date = None
        self.symbol_data = {}
        self.raw_data = {}
        self.latest_symbol_data = {}
        self.continue_backtest = True
        self.fundamental_data = None
        self.data_fields = ['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume']
        if fundamental:
            self._obtain_fundamental_data()

        self._download_files()
        self._open_convert_csv_files()
        self._to_generator()
    
    def _obtain_fundamental_data(self):
        self.fundamental_data = {}
        for sym in self.symbol_list:
            url = f"https://api.tiingo.com/tiingo/fundamentals/{sym}/statements?startDate={self.start_date}&token={os.environ['TIINGO_API']}"
            self.fundamental_data[sym] = requests.get(url, headers={ 'Content-Type': 'application/json' }).json()

    def _download_files(self, ):
        dne = []
        if not os.path.exists(self.csv_dir):
            os.makedirs(self.csv_dir)
        for sym in self.symbol_list:
            if not os.path.exists(os.path.join(self.csv_dir, f"{sym}.csv")):
                ## api call
                res_data = requests.get(get_tiingo_endpoint(f'daily/{sym}/prices', 'startDate=2000-1-1'), headers={
                    'Content-Type': 'application/json'
                }).json()
                try:
                    res_data = pd.DataFrame(res_data)
                except Exception:
                    logging.exception(res_data)
                if res_data.empty:
                    dne.append(sym)
                    continue
                res_data.set_index('date', inplace=True)
                res_data.index = res_data.index.map(lambda x: x.replace("T00:00:00.000Z", ""))
                res_data.to_csv(os.path.join(self.csv_dir, f"{sym}.csv"))
        self.symbol_list = [sym for sym in self.symbol_list if sym not in dne]

    def _open_convert_csv_files(self):
        comb_index = None
        for s in self.symbol_list:
            temp = pd.read_csv(
                os.path.join(self.csv_dir, f"{s}.csv"),
                header = 0, index_col= 0,
            ).drop_duplicates()
            temp = temp.loc[:, ["open", "high", "low", "close", "volume"]]
            if self.start_date in temp.index:
                filtered = temp.iloc[temp.index.get_loc(self.start_date):,]
            else:
                filtered = temp
            
            if self.end_date is not None and self.end_date in temp.index:
                filtered = filtered.iloc[:temp.index.get_loc(self.end_date),]
    
            self.raw_data[s] = filtered

            ## combine index to pad forward values
            if comb_index is None:
                comb_index = self.raw_data[s].index
            else: 
                comb_index.union(self.raw_data[s].index.drop_duplicates())
            
            self.latest_symbol_data[s] = []
        ## reindex
        for s in self.symbol_list:
            self.raw_data[s] = self.raw_data[s].reindex(index=comb_index, method='pad',fill_value=0)
            self.raw_data[s].index = self.raw_data[s].index.map(lambda x: datetime.datetime.strptime(x, '%Y-%m-%d'))
    def _to_generator(self):
        for s in self.symbol_list:
            self.symbol_data[s] = self.raw_data[s].iterrows()
        
    def _get_new_bar(self, symbol):
        """
        Returns latest bar from data feed as tuple of
        (symbol, datetime, open, high, low, close, volume)
        """
        for b in self.symbol_data[symbol]:
            ## need to change strptime format depending on format of datatime in csv
            yield {
                'symbol': symbol,
                'datetime': b[0],
                'open' : b[1][0],
                'high' : b[1][1],
                'low' : b[1][2],
                'close': b[1][3],
                'volume' : b[1][4]
            }

    def get_raw_data(self, symbol):
        return self.raw_data[symbol]

    def get_latest_bars(self, symbol, N=1):
        try: 
            bars_list = self.latest_symbol_data[symbol]
        except KeyError:
            logging.error("That symbol is not available in historical data set")
        else:
            bar = dict((k, []) for k in self.data_fields)
            for indi_bar_dict in bars_list[-N:]:
                for k in indi_bar_dict.keys():
                    bar[k] += [indi_bar_dict[k]]
            bar['symbol'] = symbol
            return bar
    
    def update_bars(self):
        for s in self.symbol_list:
            try:
                bar = next(self._get_new_bar(s))
            except StopIteration:
                self.continue_backtest = False
            else: 
                if bar is not None:
                    self.latest_symbol_data[s].append(bar)
        self.events.put(MarketEvent())

class AlpacaData(HistoricCSVDataHandler):
    def __init__(self, events, symbol_list, timeframe='1D', live=True, start_date=None):
        self.events = events
        self.symbol_list = symbol_list
        assert timeframe in ['1Min', '5Min', '15Min', 'day', '1D']
        self.timeframe = timeframe
        self.data_fields = ['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume']

        if not start_date and not live:
            raise Exception("If not live, start_date has to be defined")

        self.live = live
        self.start_date = pd.Timestamp.now(tz=NY)
        self.continue_backtest = True

        ## connect to Alpaca to call their symbols
        self.base_url = "https://paper-api.alpaca.markets"
        self.data_url = "https://data.alpaca.markets/v2" 
        self.api = alpaca_trade_api.REST(
            os.environ["alpaca_key_id"], 
            os.environ["alpaca_secret_key"], 
            self.base_url, api_version="v2"
        )

        if not self.live:
            self.start_date = pd.to_datetime(
                start_date, format="%Y-%m-%d"
            ).tz_localize(NY)
            self.symbol_data = {}
            self.latest_symbol_data = dict((s, []) for s in self.symbol_list)
            self.get_backtest_bars()
            self._to_generator()

    def get_backtest_bars(self):
        start = self.start_date
        ## generate self.raw_data as dict(data)
        for s in self.symbol_list:
            self.symbol_data[s] = self.api.get_barset(s, '1D', 
                limit=1000,
                start=start.isoformat(),
            ).df
    def _to_generator(self):
        for s in self.symbol_list:
            self.symbol_data[s] = self.symbol_data[s].iterrows()

    def get_latest_bars(self, symbol, N=1):
        ## will return none if empty.
        if self.live:
            today = pd.Timestamp.today(tz=NY)
            start = (today - pd.DateOffset(days=N+4)).isoformat()
            end = today.isoformat()
            return self._conform_data_dict(self.api.get_barset(symbol, '1D', 
                start=start, end=end
            ).df.iloc[-N:,:].to_dict(), symbol)
        else:
            return super().get_latest_bars(symbol, N)

    
    def _conform_data_dict(self, data: dict, symbol:str):
        bar = {}
        bar['symbol'] = symbol
        bar['datetime'] = list(data[(f'{symbol}', 'open')].keys())
        if len(list(data[(f'{symbol}', 'open')].values())) == 0:
            return bar
        bar['open'] = list(data[(f'{symbol}', 'open')].values())
        bar['high'] = list(data[(f'{symbol}', 'high')].values())
        bar['low'] = list(data[(f'{symbol}', 'low')].values())
        bar['close'] = list(data[(f'{symbol}', 'close')].values())
        return bar
    
    def get_historical_bars(self, ticker, start, end, limit:int = None) -> pd.DataFrame:
        if limit is not None:
            return self.api.get_barset(ticker, self.timeframe, start=start, end=end, limit=limit).df
        return self.api.get_barset(ticker, self.timeframe, start=start, end=end).df.to_dict()
   
    def get_last_quote(self, ticker):
        return self.api.get_last_quote(ticker)
    
    def get_last_price(self, ticker):
        return self.api.get_last_trade(ticker).price

    def update_bars(self,):
        self.start_date += pd.DateOffset(days=1)
        if not self.live:
            super().update_bars()
            if self.start_date > pd.Timestamp.today(tz=NY):
                self.continue_backtest = False
        self.events.put(MarketEvent())