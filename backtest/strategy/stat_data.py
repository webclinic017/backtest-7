import talib
from abc import abstractmethod, ABC
import pandas as pd

class StatisticalData(ABC):
    @abstractmethod
    def preprocess_X(self):
        raise NotImplementedError("Should implement preprocess_X()")

    @abstractmethod 
    def _transform_X(self, df: pd.DataFrame):
        raise NotImplementedError("_transform_X() not implemented. \
            return df if no transformation.")

    @abstractmethod
    def preprocess_Y(self):
        raise NotImplementedError("Should implement preprocess_Y()")

    @abstractmethod
    def process_data(self) -> dict:
        raise NotImplementedError("process_data() must be implemented.\n \
            Should return dict(pd.DataFrame) where keys are symbol name.")


class BaseStatisticalData(StatisticalData):
    def __init__(self, bars, shift: int, lag: int=0, add_ta=None):
        '''
        Arguments
        * lag - generates t-1, ..., t-n for close prices
        * shift - how much forward should y-var be
        * add_ta - add TA indicators to the dataset. A list of functions to apply on close price
            - CCI applies on more than 1 variables so string argument is needed for CCI
        '''
        print("Basic Data Model for supervised models")
        ##  one whole dataframe concatnated in a dict
        self.lag = lag
        self.add_ta = dict() if add_ta == None else add_ta 
        if lag < 0:
            raise Exception("self.lag variable should not be negative")
        elif lag != 0:
            self.lag = lag + 1

        if shift > 0:
            self.shift = -shift
        else:
            self.shift = shift

    def get_shift(self):
        return abs(self.shift)

    # returns dict(pd.DataFrame)
    def preprocess_X(self, df:pd.DataFrame):
        return self._transform_X(df)

    def _transform_X(self, df: pd.DataFrame): 
        ## obtains lagged data for lag days
        if self.lag > 0:
            for i in range(1,self.lag):
                df.loc[:, "lag_"+str(i)] = df["close"].shift(-i)
        df = self._add_col_TA(df)
        df.drop(['open', 'high', 'low'],axis=1, inplace=True)
        return df.dropna()
    
    def preprocess_Y(self, X:pd.DataFrame):
        ## derive Y from transformed X
        ## In this basic example, our reference is the EMA self.shift days from now.
        X.loc[:, "EMA"] = talib.EMA(X["close"], timeperiod=-self.shift).shift(self.shift)  ## for target
        X.loc[:, "target"] = (X["EMA"]- X["close"]) / X["close"]
        X.drop("EMA", axis=1, inplace=True)
        return X.loc[:,"target"]
        
    def _add_col_TA(self, df:pd.DataFrame):
        for ta, ta_func in self.add_ta.items():
            if ta == 'CCI':
                df[ta] = ta_func(df['high'], df['low'], df['close'], timeperiod=-self.shift).shift(self.shift)
            else:
                df[ta] = ta_func[0](df['close'], timeperiod=ta_func[1]).shift(-ta_func[1])
        return df

    # must be implemented
    ## appends all data into 1 large dataframe with extra col - ticker
    def process_data(self, data) -> pd.DataFrame:
        X = self.preprocess_X(data)
        y = self.preprocess_Y(data)
        final_data = pd.concat([X,y],axis=1).dropna()
        return final_data.drop('target', axis=1), final_data['target']

class ClassificationData(BaseStatisticalData):
    def __init__(self, bars, shift, lag:int=0, perc_change:float=0.05):
        super().__init__(bars, shift)
        self.lag = lag
        self.perc_chg = perc_change
        if self.lag != 0:
            self.lag = lag + 1
    
    def to_buy_or_sell(self, perc):
        if perc > self.perc_chg:
            return 1
        elif perc < 1-self.perc_chg:
            return -1
        else:
            return 0

    def preprocess_Y(self, X):
        X.loc[:, "target_num"] = X["close"].shift(self.shift)
        X.loc[:, "target"] = (X["target_num"] / X["close"])
        del X["target_num"]
        return X["target"].apply(self.to_buy_or_sell)
