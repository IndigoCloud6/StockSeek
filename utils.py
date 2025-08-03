"""
Utility functions for StockSeek application.
Contains helper functions for stock information parsing, data export, and common operations.
"""

import logging

# Global variables for lazy-loaded modules
pd = None
tk = None


def lazy_import_pandas():
    """Lazy import pandas module"""
    global pd
    if pd is None:
        try:
            import pandas as pd_module
            pd = pd_module
        except Exception as e:
            logging.error(f"导入pandas失败: {e}")
            raise


def save_to_excel(results: list, filename: str = "stock_data.xlsx"):
    """Save results to Excel file"""
    if pd is None:
        lazy_import_pandas()
    df = pd.DataFrame(results)
    df.to_excel(filename, index=False, engine='openpyxl')
    print(f"Data saved to {filename}")


def get_stock_info(stock_code):
    """
    Determine stock exchange and board type from stock code
    
    Args:
        stock_code: Stock code string
        
    Returns:
        tuple: (exchange, board_type)
    """
    if not isinstance(stock_code, str) or not stock_code.isdigit():
        return ('unknown', '非数字代码')
    
    code = stock_code.zfill(6) if len(stock_code) < 7 else stock_code
    prefix2 = code[:2]
    prefix3 = code[:3]
    
    if prefix3 == '920':
        return ('bj', '北交所')
    if prefix3 in ('600', '601', '603', '605'):
        return ('sh', '沪市主板')
    elif prefix3 == '688':
        return ('sh', '科创板')
    elif prefix3 in ('000', '001', '002', '003', '004'):
        return ('sz', '深市主板')
    elif prefix3 in ('300', '301'):
        return ('sz', '创业板')
    elif prefix2 == '20':
        return ('sz', '深市B股')
    elif prefix3 == '900':
        return ('sh', '沪市B股')
    elif prefix3 in ('430', '831', '832', '833', '834', '835', '836', '837', '838', '839'):
        return ('bj', '北交所')
    elif prefix3 in ('400', '430', '830'):
        return ('bj', '北交所')
    elif prefix2 == '87':
        return ('bj', '北交所')
    elif prefix2 == '83':
        return ('bj', '北交所')
    elif code[0] == '8' and prefix3 != '920':
        return ('bj', '北交所')
    else:
        return ('unknown', '其他板块')


def center_window(window, width, height):
    """Center a window on the screen"""
    global tk
    if tk is None:
        import tkinter as tk_module
        tk = tk_module
    
    window.update_idletasks()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry(f'{width}x{height}+{x}+{y}')


def format_amount(amount):
    """Format amount to human readable string with units"""
    if amount >= 1e8:
        return f"{amount/1e8:.1f}亿"
    elif amount >= 1e4:
        return f"{amount/1e4:.1f}万"
    else:
        return f"{amount:.0f}"


def validate_stock_code(code):
    """Validate if a stock code is valid format"""
    if not code or not isinstance(code, str):
        return False
    
    # Remove spaces and convert to string
    code = str(code).strip()
    
    # Check if it's all digits
    if not code.isdigit():
        return False
    
    # Check length (typically 6 digits)
    if len(code) < 3 or len(code) > 6:
        return False
    
    return True