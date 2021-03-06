from abc import ABCMeta, abstractmethod
from trading_common.data.dataHandler import DataHandler
from trading_common.utilities.enum import OrderPosition
from trading_common.event import SignalEvent

class Rebalance(metaclass=ABCMeta):                
    def __init__(self, events, bars: DataHandler) -> None:
        self.events = events
        self.bars = bars
    @abstractmethod
    def need_rebalance(self, current_holdings):
        """
        The check for rebalancing portfolio
        """
        raise NotImplementedError("Should implement need_rebalance()")

    @abstractmethod
    def rebalance(self, stock_list, current_holdings):
        """
        Updates portfolio based on rebalancing criteria
        """
        raise NotImplementedError("Should implement rebalance(). If not required, just pass")

class NoRebalance():
    ''' No variables initialized as need_balance returns false'''
    def need_rebalance(self, current_holdings):
        return False

    def rebalance(self, stock_list, current_holdings) -> None:
        return


class BaseRebalance(Rebalance):
    ''' EXIT for all positions every year '''
    def __init__(self, events, bars) -> None:
        super().__init__(events, bars)

    def need_rebalance(self, current_holdings):
        return current_holdings['datetime'].dayofyear < 4

    def rebalance(self, stock_list, current_holdings) -> None:
        if self.need_rebalance(current_holdings):
            for symbol in stock_list:
                latest_close_price = self.bars.get_latest_bars(symbol)['close'][-1]
                ## only 1 will go through if there is position
                self.events.put(SignalEvent(symbol, current_holdings['datetime'], OrderPosition.EXIT_LONG, latest_close_price))
                self.events.put(SignalEvent(symbol, current_holdings['datetime'], OrderPosition.EXIT_SHORT, latest_close_price))

class SellLongLosers(Rebalance):
    def __init__(self, events, bars) -> None:
        super().__init__(events, bars)

    def need_rebalance(self, current_holdings):
        ## every quarter
        return current_holdings['datetime'].is_quarter_start

    def rebalance(self, stock_list, current_holdings) -> None:
        if self.need_rebalance(current_holdings):
            for symbol in stock_list:
                ## sell all losers
                latest_close_price = self.bars.get_latest_bars(symbol)['close'][-1]
                if current_holdings[symbol]["quantity"] > 0 and latest_close_price < current_holdings[symbol]["last_trade_price"]:
                    self.events.put(SignalEvent(symbol, current_holdings['datetime'], OrderPosition.EXIT_LONG, latest_close_price))
                elif current_holdings[symbol]["quantity"] < 0 and latest_close_price > current_holdings[symbol]["last_trade_price"]:
                    self.events.put(SignalEvent(symbol, current_holdings['datetime'], OrderPosition.EXIT_SHORT, latest_close_price))