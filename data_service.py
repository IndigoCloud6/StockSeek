"""
Data service module for StockSeek application.
Handles stock data fetching, processing, and related operations.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global variables for lazy-loaded modules
ak = None
pd = None


def lazy_import_data_modules():
    """Lazy import data processing modules"""
    global ak, pd
    
    if ak is None:
        logging.info("正在导入数据处理模块...")
        try:
            import akshare as ak_module
            import pandas as pd_module
            
            ak = ak_module
            pd = pd_module
            
            logging.info("数据处理模块导入完成")
        except Exception as e:
            logging.error(f"导入数据处理模块失败: {e}")
            raise


def fetch_stock_data():
    """
    Fetch stock data from akshare
    
    Returns:
        DataFrame: Stock data with columns for processing
    """
    if ak is None:
        lazy_import_data_modules()
    
    try:
        # Fetch main board stocks
        stock_zh_a_spot_em = ak.stock_zh_a_spot_em()
        logging.info(f"获取到 {len(stock_zh_a_spot_em)} 只股票数据")
        return stock_zh_a_spot_em
    except Exception as e:
        logging.error(f"获取股票数据失败: {e}")
        raise


def process_stock_data(stock_data, min_amount=None, min_market_cap=None):
    """
    Process and filter stock data
    
    Args:
        stock_data: Raw stock data DataFrame
        min_amount: Minimum trading amount filter
        min_market_cap: Minimum market cap filter
        
    Returns:
        DataFrame: Processed and filtered stock data
    """
    if pd is None:
        lazy_import_data_modules()
    
    try:
        # Apply filters if specified
        if min_amount is not None:
            stock_data = stock_data[stock_data['成交额'] >= min_amount]
        
        if min_market_cap is not None:
            stock_data = stock_data[stock_data['总市值'] >= min_market_cap]
        
        # Filter out Beijing and STAR board stocks (if needed)
        def not_bj_kcb(row):
            code = str(row['代码']).zfill(6)
            return not (code.startswith(('8', '4', '920', '688')))
        
        stock_data = stock_data[stock_data.apply(not_bj_kcb, axis=1)]
        
        logging.info(f"过滤后剩余 {len(stock_data)} 只股票")
        return stock_data
        
    except Exception as e:
        logging.error(f"处理股票数据失败: {e}")
        raise


def process_single_stock(stock_code, stock_name):
    """
    Process a single stock and return enriched data
    
    Args:
        stock_code: Stock code
        stock_name: Stock name
        
    Returns:
        dict: Processed stock data with additional information
    """
    if ak is None:
        lazy_import_data_modules()
    
    try:
        from utils import get_stock_info
        
        # Get basic stock info
        exchange, board_type = get_stock_info(stock_code)
        
        # Fetch additional data (could add more enrichment here)
        result = {
            'code': stock_code,
            'name': stock_name,
            'exchange': exchange,
            'board_type': board_type,
            'processed': True
        }
        
        # Add any additional processing logic here
        # For example: technical indicators, fundamentals, etc.
        
        return result
        
    except Exception as e:
        logging.error(f"处理股票 {stock_code} 失败: {e}")
        return {
            'code': stock_code,
            'name': stock_name,
            'error': str(e),
            'processed': False
        }


def fetch_stock_history(stock_code, period="daily", adjust="qfq"):
    """
    Fetch historical stock data for charts
    
    Args:
        stock_code: Stock code
        period: Data period (daily, weekly, monthly)
        adjust: Adjustment type (qfq, hfq, etc.)
        
    Returns:
        DataFrame: Historical stock data
    """
    if ak is None:
        lazy_import_data_modules()
    
    try:
        # Determine the appropriate akshare function based on stock code
        code = str(stock_code).zfill(6)
        
        if code.startswith('000') or code.startswith('002') or code.startswith('300'):
            # Shenzhen stocks
            stock_data = ak.stock_zh_a_hist(symbol=code, period=period, adjust=adjust)
        elif code.startswith('600') or code.startswith('601') or code.startswith('603'):
            # Shanghai stocks  
            stock_data = ak.stock_zh_a_hist(symbol=code, period=period, adjust=adjust)
        else:
            # Default fallback
            stock_data = ak.stock_zh_a_hist(symbol=code, period=period, adjust=adjust)
        
        # Process the data format for charting
        if not stock_data.empty:
            stock_data.index = pd.to_datetime(stock_data['日期'])
            stock_data = stock_data[['开盘', '最高', '最低', '收盘', '成交量']]
            stock_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        
        return stock_data
        
    except Exception as e:
        logging.error(f"获取股票 {stock_code} 历史数据失败: {e}")
        return pd.DataFrame()


def calculate_rsi(data, window=14):
    """
    Calculate RSI (Relative Strength Index) technical indicator
    
    Args:
        data: Price data series
        window: RSI calculation window
        
    Returns:
        Series: RSI values
    """
    if pd is None:
        lazy_import_data_modules()
    
    try:
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except Exception as e:
        logging.error(f"计算RSI失败: {e}")
        return pd.Series()


class DataProcessor:
    """Data processing class with thread management"""
    
    def __init__(self, max_workers=5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="DataProcessor")
        self.processed_count = 0
        self.failed_count = 0
        self.progress_lock = threading.Lock()
    
    def process_stocks_batch(self, stock_list, progress_callback=None):
        """
        Process multiple stocks in parallel
        
        Args:
            stock_list: List of (code, name) tuples
            progress_callback: Callback function for progress updates
            
        Returns:
            list: Processed stock results
        """
        results = []
        
        def process_with_progress(stock_info):
            code, name = stock_info
            result = process_single_stock(code, name)
            
            with self.progress_lock:
                if result.get('processed', False):
                    self.processed_count += 1
                else:
                    self.failed_count += 1
                
                if progress_callback:
                    progress_callback(self.processed_count, self.failed_count)
            
            return result
        
        # Submit all tasks
        future_to_stock = {
            self.executor.submit(process_with_progress, stock): stock 
            for stock in stock_list
        }
        
        # Collect results
        for future in as_completed(future_to_stock):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                stock = future_to_stock[future]
                logging.error(f"处理股票 {stock} 时发生异常: {e}")
        
        return results
    
    def shutdown(self):
        """Shutdown the executor"""
        self.executor.shutdown(wait=True)