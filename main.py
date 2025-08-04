import json
import logging
import os
import queue
import sqlite3
import threading
import tkinter as tk
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from tkinter.font import Font
from typing import Dict, List, Optional, Tuple, Any
from abc import ABC, abstractmethod
import time

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)


# 配置常量
class Config:
    CONFIG_FILE = "config.json"
    DEFAULT_ANNOUNCEMENTS = [
        "系统公告：所有数据来源于公开市场信息，仅供参考，不构成投资建议。"
    ]
    DEFAULT_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    DEFAULT_WINDOW_SIZE = (1400, 650)
    KLINE_WINDOW_SIZE = (1200, 800)
    MAX_KLINE_WORKERS = 5
    MAX_DATA_WORKERS = 10
    BATCH_SIZE = 100
    CLEANUP_INTERVAL = 30000  # 30秒


# 模块管理器
class ModuleManager:
    """管理重型模块的延迟导入"""

    def __init__(self):
        self._modules = {}
        self._initialized = False

    def initialize_data_modules(self):
        """初始化数据处理模块"""
        if self._initialized:
            return

        logging.info("正在导入数据处理模块...")
        try:
            import akshare as ak
            import matplotlib
            import matplotlib.pyplot as plt
            import mplfinance as mpf
            import pandas as pd
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

            self._modules.update({
                'ak': ak,
                'matplotlib': matplotlib,
                'plt': plt,
                'mpf': mpf,
                'pd': pd,
                'FigureCanvasTkAgg': FigureCanvasTkAgg,
                'NavigationToolbar2Tk': NavigationToolbar2Tk
            })

            # 设置matplotlib字体
            matplotlib.rcParams['font.family'] = 'Microsoft YaHei'
            matplotlib.rcParams['axes.unicode_minus'] = False

            self._initialized = True
            logging.info("数据处理模块导入完成")

        except Exception as e:
            logging.error(f"导入数据处理模块失败: {e}")
            raise

    def initialize_openai_client(self, api_key: str):
        """初始化OpenAI客户端"""
        if 'client' in self._modules:
            return self._modules['client']

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            self._modules['client'] = client
            logging.info("OpenAI客户端初始化完成")
            return client
        except Exception as e:
            logging.error(f"OpenAI客户端初始化失败: {e}")
            raise

    def get_module(self, name: str):
        """获取模块"""
        if not self._initialized and name in ['ak', 'matplotlib', 'plt', 'mpf', 'pd', 'FigureCanvasTkAgg', 'NavigationToolbar2Tk']:
            self.initialize_data_modules()
        return self._modules.get(name)

    @property
    def ak(self):
        return self.get_module('ak')

    @property
    def matplotlib(self):
        return self.get_module('matplotlib')

    @property
    def plt(self):
        return self.get_module('plt')

    @property
    def mpf(self):
        return self.get_module('mpf')

    @property
    def pd(self):
        return self.get_module('pd')

    @property
    def FigureCanvasTkAgg(self):
        return self.get_module('FigureCanvasTkAgg')

    @property
    def NavigationToolbar2Tk(self):
        return self.get_module('NavigationToolbar2Tk')

    @property
    def client(self):
        return self.get_module('client')


# 全局模块管理器实例
module_manager = ModuleManager()


# 工具函数
class Utils:
    """工具函数集合"""

    @staticmethod
    def ensure_config_file():
        """确保配置文件存在"""
        if not os.path.exists(Config.CONFIG_FILE):
            try:
                config_data = {
                    "announcements": Config.DEFAULT_ANNOUNCEMENTS,
                    "api_key": Config.DEFAULT_API_KEY
                }
                with open(Config.CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                logging.error(f"创建配置文件失败: {e}")

    @staticmethod
    def get_stock_info(stock_code: str) -> Tuple[str, str]:
        """获取股票交易所和板块信息"""
        if not isinstance(stock_code, str) or not stock_code.isdigit():
            return ('unknown', '非数字代码')

        code = stock_code.zfill(6) if len(stock_code) < 7 else stock_code
        prefix2 = code[:2]
        prefix3 = code[:3]

        # 北交所
        if prefix3 == '920' or prefix3 in ('430', '831', '832', '833', '834', '835', '836', '837', '838', '839'):
            return ('bj', '北交所')
        if prefix3 in ('400', '430', '830') or prefix2 in ('87', '83'):
            return ('bj', '北交所')
        if code[0] == '8' and prefix3 != '920':
            return ('bj', '北交所')

        # 沪市
        if prefix3 in ('600', '601', '603', '605'):
            return ('sh', '沪市主板')
        elif prefix3 == '688':
            return ('sh', '科创板')
        elif prefix3 == '900':
            return ('sh', '沪市B股')

        # 深市
        elif prefix3 in ('000', '001', '002', '003', '004'):
            return ('sz', '深市主板')
        elif prefix3 in ('300', '301'):
            return ('sz', '创业板')
        elif prefix2 == '20':
            return ('sz', '深市B股')

        return ('unknown', '其他板块')

    @staticmethod
    def center_window(window, width: int, height: int):
        """窗口居中显示"""
        window.withdraw()
        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = int((screen_width - width) / 2)
        y = int((screen_height - height) / 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.deiconify()

    @staticmethod
    def format_number(value, decimal_places: int = 2) -> str:
        """格式化数字显示"""
        try:
            if isinstance(value, str):
                value = float(value)
            if decimal_places == 0:
                return f"{value:,.0f}"
            else:
                return f"{value:,.{decimal_places}f}"
        except (ValueError, TypeError):
            return "0" if decimal_places == 0 else "0.00"

    @staticmethod
    def get_trading_date() -> datetime:
        """获取当前交易日"""
        now = datetime.now()
        current_time = now.time()
        market_open_time = datetime.strptime("09:30", "%H:%M").time()

        # 如果当前时间早于9:30，使用前一天的日期
        if current_time < market_open_time:
            target_date = now - timedelta(days=1)
        else:
            target_date = now

        # 处理周末情况
        while target_date.weekday() > 4:  # 0-6代表周一到周日
            target_date = target_date - timedelta(days=1)

        return target_date


# 数据库管理器
class DatabaseManager:
    """数据库操作管理器"""

    def __init__(self, db_path: str = 'stock_data.db'):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def save_stock_changes(self, df, date_str: str):
        """保存股票变动数据"""
        table_name = f'stock_changes_{date_str}'
        with self.get_connection() as conn:
            try:
                conn.execute(f"DELETE FROM {table_name}")
            except sqlite3.OperationalError:
                pass
            df.to_sql(table_name, conn, if_exists='append', index=False)
        logging.info(f"股票变动数据已保存到表 {table_name}")

    def save_stock_real_data(self, df, date_str: str):
        """保存股票实时数据"""
        table_name = f'stock_real_data_{date_str}'
        with self.get_connection() as conn:
            try:
                conn.execute(f"DELETE FROM {table_name}")
            except sqlite3.OperationalError:
                pass
            df.to_sql(table_name, conn, if_exists='replace', index=False)
        logging.info(f"股票实时数据已保存到表 {table_name}")

    def load_filtered_data(self, date_str: str, min_amount: int, max_market_cap: int, sort_by: str):
        """加载过滤后的数据"""
        query = f"""
        SELECT 
            a.代码, a.名称, b.交易所, b.行业, b.总市值, b.市场板块,
            b.今开, b.最新, b.涨幅, b.最低, b.最高, b.涨停,
            b.换手, b.量比,
            COUNT(1) AS 总成笔数,
            CAST(SUM(a.成交金额) / 10000 AS INTEGER) AS 总成交金额,
            GROUP_CONCAT(CAST(a.成交金额 / 10000 AS INTEGER) || '万(' || a.时间 || ')', '|') AS 时间金额明细
        FROM 
            stock_changes_{date_str} a,
            stock_real_data_{date_str} b
        WHERE 
            a.代码 = b.代码 AND b.总市值 <= {max_market_cap}
        GROUP BY 
            a.代码, a.名称
        HAVING 
            总成交金额 > {min_amount}
        ORDER BY 
            {sort_by} DESC
        """

        pd = module_manager.pd
        with self.get_connection() as conn:
            return pd.read_sql_query(query, conn)

    def load_big_buy_orders(self, stock_code: str, date_str: str):
        """加载大笔买入明细"""
        query = f"""
        SELECT 时间, 代码, 名称, 板块, 成交量, 成交价, 占成交量比, 成交金额
        FROM stock_changes_{date_str}
        WHERE 代码 = ?
        ORDER BY 时间 ASC
        """

        with self.get_connection() as conn:
            cursor = conn.execute(query, (stock_code,))
            return cursor.fetchall()


# 配置管理器
class ConfigManager:
    """配置文件管理器"""

    def __init__(self):
        Utils.ensure_config_file()

    def load_config(self) -> Dict[str, Any]:
        """加载配置"""
        try:
            with open(Config.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"加载配置失败: {e}")
            return {
                "announcements": Config.DEFAULT_ANNOUNCEMENTS,
                "api_key": Config.DEFAULT_API_KEY
            }

    def save_config(self, config: Dict[str, Any]):
        """保存配置"""
        try:
            with open(Config.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"保存配置失败: {e}")
            raise

    def get_announcements(self) -> List[str]:
        """获取公告列表"""
        config = self.load_config()
        announcements = config.get("announcements", Config.DEFAULT_ANNOUNCEMENTS)
        return announcements if announcements else Config.DEFAULT_ANNOUNCEMENTS

    def get_api_key(self) -> str:
        """获取API密钥"""
        config = self.load_config()
        api_key = config.get("api_key", Config.DEFAULT_API_KEY)
        if not api_key or api_key.startswith("sk-xxxx"):
            logging.warning("请在config.json中配置有效的api_key")
        return api_key

    def save_announcements(self, announcements: List[str]):
        """保存公告配置"""
        config = self.load_config()
        config["announcements"] = announcements
        self.save_config(config)


# 数据处理器基类
class DataProcessor(ABC):
    """数据处理器抽象基类"""

    @abstractmethod
    def process(self, *args, **kwargs):
        """处理数据的抽象方法"""
        pass


# 股票数据处理器
class StockDataProcessor(DataProcessor):
    """股票数据处理器"""

    def __init__(self):
        self.processed_count = 0
        self.failed_count = 0
        self.lock = threading.Lock()

    def process_stock(self, stock_code: str, stock_name: str) -> Optional[Dict[str, Any]]:
        """处理单个股票数据"""
        try:
            ak = module_manager.ak

            # 获取股票基本信息
            stock_info_df = ak.stock_individual_info_em(symbol=stock_code)
            industry = self._get_info_value(stock_info_df, '行业', '未知')
            market_cap = self._get_info_value(stock_info_df, '总市值', 0)

            # 获取股票买卖盘数据
            stock_bid_ask_df = ak.stock_bid_ask_em(symbol=stock_code)

            # 提取各项数据
            data = {
                '代码': stock_code,
                '名称': stock_name,
                '交易所': Utils.get_stock_info(stock_code)[0],
                '市场板块': Utils.get_stock_info(stock_code)[1],
                '行业': industry,
                '总市值': int(market_cap / 100000000) if isinstance(market_cap, (int, float)) else 0,
                '最新': self._get_bid_ask_value(stock_bid_ask_df, '最新'),
                '涨幅': self._get_bid_ask_value(stock_bid_ask_df, '涨幅'),
                '最高': self._get_bid_ask_value(stock_bid_ask_df, '最高'),
                '最低': self._get_bid_ask_value(stock_bid_ask_df, '最低'),
                '涨停': self._get_bid_ask_value(stock_bid_ask_df, '涨停'),
                '换手': self._get_bid_ask_value(stock_bid_ask_df, '换手'),
                '量比': self._get_bid_ask_value(stock_bid_ask_df, '量比'),
                '今开': self._get_bid_ask_value(stock_bid_ask_df, '今开')
            }

            return data

        except Exception as e:
            logging.error(f"处理股票 {stock_code}({stock_name}) 失败: {e}")
            return None

    def _get_info_value(self, df, item_name: str, default_value=None):
        """从股票信息DataFrame中获取值"""
        try:
            if item_name in df['item'].values:
                value = df[df['item'] == item_name]['value'].iloc[0]
                return value if value is not None else default_value
            return default_value
        except Exception:
            return default_value

    def _get_bid_ask_value(self, df, item_name: str, default_value=None):
        """从买卖盘DataFrame中获取数值"""
        try:
            if item_name in df['item'].values:
                value = df[df['item'] == item_name]['value'].iloc[0]
                return float(value) if value is not None else default_value
            return default_value
        except Exception:
            return default_value

    def process(self, stock_info_list: List[Tuple[str, str]],
                progress_callback=None, max_workers: int = Config.MAX_DATA_WORKERS) -> List[Dict[str, Any]]:
        """批量处理股票数据"""
        total_stocks = len(stock_info_list)
        results = []

        self.processed_count = 0
        self.failed_count = 0

        def process_with_progress(stock_code: str, stock_name: str):
            result = self.process_stock(stock_code, stock_name)

            with self.lock:
                self.processed_count += 1
                if result is None:
                    self.failed_count += 1

                # 调用进度回调
                if progress_callback and (self.processed_count % 10 == 0 or self.processed_count == total_stocks):
                    progress_callback(self.processed_count, total_stocks, self.failed_count)

            return result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_stock = {
                executor.submit(process_with_progress, code, name): (code, name)
                for code, name in stock_info_list
            }

            for future in as_completed(future_to_stock):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    stock_code, stock_name = future_to_stock[future]
                    logging.error(f"获取股票 {stock_code}({stock_name}) 结果失败: {e}")

        return results


# K线图窗口
class KLineWindow:
    """K线图窗口类"""

    def __init__(self, parent, stock_code: str, stock_name: str):
        self.parent = parent
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.window = None
        self.canvas = None
        self.result_queue = queue.Queue()
        self.window_id = str(uuid.uuid4())[:8]

        self.create_window()
        threading.Thread(target=self.fetch_data_async, daemon=True).start()
        self.check_result()

    def create_window(self):
        """创建K线图窗口"""
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"K线图 - {self.stock_name}({self.stock_code}) [ID: {self.window_id}]")
        self.window.geometry(f"{Config.KLINE_WINDOW_SIZE[0]}x{Config.KLINE_WINDOW_SIZE[1]}")

        Utils.center_window(self.window, *Config.KLINE_WINDOW_SIZE)

        # 创建主框架
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 图表容器
        self.chart_frame = ttk.Frame(main_frame)
        self.chart_frame.pack(fill=tk.BOTH, expand=True)

        self.window.protocol("WM_DELETE_WINDOW", self.on_window_close)

    def fetch_data_async(self):
        """异步获取K线数据"""
        try:
            ak = module_manager.ak

            target_date = Utils.get_trading_date()
            today = target_date.strftime('%Y%m%d')

            logging.info(f"[{self.window_id}] 开始获取 {self.stock_name}({self.stock_code}) 的K线数据，日期: {today}")

            # 获取股票1分钟K线数据
            stock_data = ak.stock_zh_a_hist_min_em(
                symbol=self.stock_code,
                period="1",
                start_date=f"{today} 09:00:00",
                end_date=f"{today} 15:00:00",
                adjust="qfq"
            )

            if stock_data.empty:
                self.result_queue.put({
                    'success': False,
                    'error': f"未获取到{self.stock_name}({self.stock_code})的数据，可能是非交易日或数据源问题"
                })
                return

            # 数据预处理
            processed_data = self._process_kline_data(stock_data)

            self.result_queue.put({
                'success': True,
                'data': processed_data,
                'display_date': target_date.strftime('%Y-%m-%d')
            })

            logging.info(f"[{self.window_id}] {self.stock_name}({self.stock_code}) 数据获取完成")

        except Exception as e:
            logging.error(f"[{self.window_id}] 获取K线数据失败: {e}")
            self.result_queue.put({
                'success': False,
                'error': f"获取K线数据失败: {str(e)}"
            })

    def _process_kline_data(self, stock_data):
        """处理K线数据"""
        pd = module_manager.pd

        # 重命名列
        stock_data_processed = stock_data.rename(columns={
            '时间': 'Date',
            '开盘': 'Open',
            '最高': 'High',
            '最低': 'Low',
            '收盘': 'Close',
            '成交量': 'Volume'
        })

        # 转换时间格式并设置为索引
        stock_data_processed['Date'] = pd.to_datetime(stock_data_processed['Date'])
        stock_data_processed.set_index('Date', inplace=True)

        # 确保数据类型正确
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            stock_data_processed[col] = pd.to_numeric(stock_data_processed[col], errors='coerce')

        # 计算技术指标
        stock_data_processed['MA5'] = stock_data_processed['Close'].rolling(window=5).mean()
        stock_data_processed['MA10'] = stock_data_processed['Close'].rolling(window=10).mean()
        stock_data_processed['MA20'] = stock_data_processed['Close'].rolling(window=20).mean()

        # 布林带
        stock_data_processed['BB_middle'] = stock_data_processed['Close'].rolling(window=20).mean()
        stock_data_processed['BB_std'] = stock_data_processed['Close'].rolling(window=20).std()
        stock_data_processed['BB_upper'] = stock_data_processed['BB_middle'] + 2 * stock_data_processed['BB_std']
        stock_data_processed['BB_lower'] = stock_data_processed['BB_middle'] - 2 * stock_data_processed['BB_std']

        # RSI计算
        stock_data_processed['RSI'] = self._calculate_rsi(stock_data_processed['Close'])

        return stock_data_processed

    def _calculate_rsi(self, data, window: int = 14):
        """计算RSI指标"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def check_result(self):
        """检查数据获取结果"""
        try:
            result = self.result_queue.get_nowait()
            if result['success']:
                self.display_chart(result['data'], result['display_date'])
            else:
                self.show_error(result['error'])
        except queue.Empty:
            if self.window and self.window.winfo_exists():
                self.window.after(100, self.check_result)

    def display_chart(self, stock_data_processed, display_date: str):
        """显示K线图"""
        try:
            mpf = module_manager.mpf
            plt = module_manager.plt
            FigureCanvasTkAgg = module_manager.FigureCanvasTkAgg
            NavigationToolbar2Tk = module_manager.NavigationToolbar2Tk

            # 创建自定义颜色样式（中国习惯：红涨绿跌）
            mc = mpf.make_marketcolors(
                up='red',
                down='green',
                edge='inherit',
                wick={'up': 'red', 'down': 'green'},
                volume='in',
            )

            # 创建图表样式
            style = mpf.make_mpf_style(
                marketcolors=mc,
                gridstyle='-',
                gridcolor='lightgray',
                facecolor='white',
                figcolor='white',
                rc={'font.family': 'Microsoft YaHei'}
            )

            # 准备附加图表（技术指标）
            apds = [
                mpf.make_addplot(stock_data_processed['MA5'], color='blue', width=1.5),
                mpf.make_addplot(stock_data_processed['MA10'], color='purple', width=1.5),
                mpf.make_addplot(stock_data_processed['MA20'], color='orange', width=1.5),
                mpf.make_addplot(stock_data_processed['BB_upper'], color='gray', width=1, alpha=0.7),
                mpf.make_addplot(stock_data_processed['BB_lower'], color='gray', width=1, alpha=0.7),
                mpf.make_addplot(stock_data_processed['RSI'], panel=2, color='purple', width=1.5),
                mpf.make_addplot([70] * len(stock_data_processed), panel=2, color='red', width=0.8, linestyle='--', alpha=0.7),
                mpf.make_addplot([30] * len(stock_data_processed), panel=2, color='green', width=0.8, linestyle='--', alpha=0.7),
            ]

            # 创建matplotlib图形
            fig, axes = mpf.plot(
                stock_data_processed,
                type='candle',
                style=style,
                volume=True,
                addplot=apds,
                ylabel='价格 (元)',
                ylabel_lower='成交量',
                figsize=(12, 8),
                panel_ratios=(3, 1, 1),
                tight_layout=True,
                show_nontrading=False,
                returnfig=True
            )

            # 添加图例
            self._add_chart_legends(axes, plt)

            # 在图表底部添加标题
            fig.suptitle(f'{self.stock_name}({self.stock_code}) - {display_date} K线图',
                         fontsize=14, fontweight='bold', y=0.05)

            # 清空图表容器并嵌入新图形
            self._embed_chart(fig)

            # 打印最新数据
            if not stock_data_processed.empty:
                latest_data = stock_data_processed.iloc[-1]
                logging.info(f"[{self.window_id}] {self.stock_name}({self.stock_code}) 最新数据:")
                logging.info(f"收盘价: {latest_data['Close']:.2f}, MA5: {latest_data['MA5']:.2f}, RSI: {latest_data['RSI']:.2f}")

        except Exception as e:
            logging.error(f"[{self.window_id}] 显示K线图失败: {e}")
            self.show_error(f"显示K线图失败: {str(e)}")

    def _add_chart_legends(self, axes, plt):
        """添加图表图例"""
        # 主图图例
        main_ax = axes[0]
        legend_elements = [
            plt.Line2D([0], [0], color='blue', lw=1.5, label='MA5'),
            plt.Line2D([0], [0], color='purple', lw=1.5, label='MA10'),
            plt.Line2D([0], [0], color='orange', lw=1.5, label='MA20'),
            plt.Line2D([0], [0], color='gray', lw=1, alpha=0.7, label='布林带'),
        ]
        main_ax.legend(handles=legend_elements, loc='lower right', frameon=True,
                       fancybox=True, shadow=True, framealpha=0.9, fontsize=10)

        # RSI子图图例
        if len(axes) > 2:
            rsi_ax = axes[2]
            rsi_legend_elements = [
                plt.Line2D([0], [0], color='purple', lw=1.5, label='RSI'),
                plt.Line2D([0], [0], color='red', lw=0.8, linestyle='--', alpha=0.7, label='超买(70)'),
                plt.Line2D([0], [0], color='green', lw=0.8, linestyle='--', alpha=0.7, label='超卖(30)'),
            ]
            rsi_ax.legend(handles=rsi_legend_elements, loc='lower right', frameon=True,
                          fancybox=True, shadow=True, framealpha=0.9, fontsize=9)

    def _embed_chart(self, fig):
        """在Tkinter中嵌入matplotlib图形"""
        FigureCanvasTkAgg = module_manager.FigureCanvasTkAgg
        NavigationToolbar2Tk = module_manager.NavigationToolbar2Tk

        # 清空图表容器
        for widget in self.chart_frame.winfo_children():
            widget.destroy()

        # 嵌入matplotlib图形
        self.canvas = FigureCanvasTkAgg(fig, self.chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 添加工具栏
        toolbar = NavigationToolbar2Tk(self.canvas, self.chart_frame)
        toolbar.update()

    def show_error(self, error_message: str):
        """显示错误信息"""
        error_frame = ttk.Frame(self.chart_frame)
        error_frame.pack(expand=True)

        ttk.Label(error_frame, text="❌", font=('Arial', 48)).pack(pady=20)
        ttk.Label(error_frame, text=error_message, font=('Microsoft YaHei', 12),
                  foreground='red', wraplength=800).pack(pady=10)

        ttk.Button(error_frame, text="重试",
                   command=self.retry_fetch).pack(pady=10)

    def retry_fetch(self):
        """重试获取数据"""
        for widget in self.chart_frame.winfo_children():
            widget.destroy()
        threading.Thread(target=self.fetch_data_async, daemon=True).start()
        self.check_result()

    def on_window_close(self):
        """窗口关闭处理"""
        logging.info(f"[{self.window_id}] 关闭K线图窗口: {self.stock_name}({self.stock_code})")
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
        self.window.destroy()


# UI组件基类
class UIComponent(ABC):
    """UI组件抽象基类"""

    def __init__(self, parent):
        self.parent = parent

    @abstractmethod
    def create_ui(self):
        """创建UI界面"""
        pass


# 公告栏组件
class AnnouncementBar(UIComponent):
    """公告栏组件"""

    def __init__(self, parent, config_manager: ConfigManager):
        super().__init__(parent)
        self.config_manager = config_manager
        self.announcements = config_manager.get_announcements()
        self.current_announcement_idx = 0

        self.announcement_frame = None
        self.announcement_label = None
        self.clock_label = None

        self.create_ui()
        self.start_announcement_loop()
        self.start_clock_update()

    def create_ui(self):
        """创建公告栏UI"""
        self.announcement_frame = ttk.Frame(self.parent, height=30)
        self.announcement_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        # 公告图标
        announcement_icon = tk.Label(
            self.announcement_frame,
            text="📢",
            font=("Microsoft YaHei", 10, "bold"),
            bg="#FFE4B5",
            padx=5
        )
        announcement_icon.pack(side=tk.LEFT, fill=tk.Y)

        # 公告内容
        self.announcement_label = tk.Label(
            self.announcement_frame,
            text="",
            font=("Microsoft YaHei", 10, "bold"),
            bg="#FFE4B5",
            fg="#8B0000",
            anchor="w",
            padx=10
        )
        self.announcement_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 时钟
        self.clock_label = tk.Label(
            self.announcement_frame,
            text="",
            font=("Microsoft YaHei", 10, "bold"),
            bg="#FFE4B5",
            fg="#FF0000",
            padx=10
        )
        self.clock_label.pack(side=tk.RIGHT, padx=0)

        # 配置按钮
        # ttk.Button(
        #     self.announcement_frame,
        #     text="配置公告",
        #     width=10,
        #     command=self.configure_announcements
        # ).pack(side=tk.RIGHT, padx=5)

        # 设置样式
        style = ttk.Style()
        style.configure("Announcement.TFrame", background="#FFE4B5")

    def start_announcement_loop(self):
        """开始公告轮播"""

        def update_announcement():
            if self.announcements:
                announcement = self.announcements[self.current_announcement_idx]
                self.announcement_label.config(text=announcement)
                self.current_announcement_idx = (self.current_announcement_idx + 1) % len(self.announcements)
            self.parent.after(8000, update_announcement)

        update_announcement()

    def start_clock_update(self):
        """开始时钟更新"""

        def update_clock():
            now = datetime.now()
            time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            self.clock_label.config(text=time_str)
            self.parent.after(1000, update_clock)

        update_clock()

    def configure_announcements(self):
        """配置公告"""
        config_window = tk.Toplevel(self.parent)
        config_window.title("公告配置")
        Utils.center_window(config_window, 600, 800)
        config_window.resizable(True, True)

        # 创建界面
        outer_frame = ttk.Frame(config_window)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        # 文本编辑区域
        text_frame = ttk.Frame(outer_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        announcement_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            font=("Microsoft YaHei", 10),
            padx=10,
            pady=10
        )
        announcement_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=announcement_text.yview)

        # 帮助提示
        help_text = "提示：每条公告单独一行，系统将按顺序轮播显示"
        ttk.Label(outer_frame, text=help_text, foreground="gray").pack(anchor=tk.W, padx=10, pady=(6, 0))

        # 按钮区域
        button_frame = ttk.Frame(outer_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)

        def save_announcements():
            text = announcement_text.get(1.0, tk.END).strip()
            announcements = [line.strip() for line in text.split("\n") if line.strip()]
            if not announcements:
                messagebox.showerror("错误", "公告内容不能为空！")
                return

            try:
                self.config_manager.save_announcements(announcements)
                self.announcements = announcements
                self.current_announcement_idx = 0
                messagebox.showinfo("成功", "公告配置已保存！")
                config_window.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"保存公告配置失败: {str(e)}")

        def reset_announcements():
            announcement_text.delete(1.0, tk.END)
            announcement_text.insert(tk.END, "\n".join(Config.DEFAULT_ANNOUNCEMENTS))

        # 按钮
        ttk.Button(button_frame, text="取消", command=config_window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="重置", command=reset_announcements).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="保存", command=save_announcements).pack(side=tk.RIGHT, padx=5)

        # 加载当前公告
        announcement_text.insert(tk.END, "\n".join(self.announcements))


# 控制面板组件
class ControlPanel(UIComponent):
    """控制面板组件"""

    def __init__(self, parent, on_refresh_callback, on_column_select_callback):
        super().__init__(parent)
        self.on_refresh_callback = on_refresh_callback
        self.on_column_select_callback = on_column_select_callback

        # 控制变量
        self.amount_var = tk.StringVar(value="2000")
        self.market_cap_var = tk.StringVar(value="2000")
        self.sort_var = tk.StringVar(value="总成交金额")

        self.create_ui()

    def create_ui(self):
        """创建控制面板UI"""
        control_frame = ttk.LabelFrame(self.parent, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 刷新按钮
        ttk.Button(
            control_frame,
            text="刷新数据",
            command=lambda: threading.Thread(target=self.on_refresh_callback, daemon=True).start()
        ).pack(side=tk.LEFT, padx=5)

        # 最小成交金额控制
        self._create_amount_control(control_frame)

        # 最大总市值控制
        self._create_market_cap_control(control_frame)

        # 排序方式选择
        self._create_sort_control(control_frame)

        # 显示字段选择按钮
        ttk.Button(
            control_frame,
            text="选择显示字段",
            command=self.on_column_select_callback
        ).pack(side=tk.RIGHT, padx=5)

    def _create_amount_control(self, parent):
        """创建最小成交金额控制"""
        amount_frame = ttk.Frame(parent)
        amount_frame.pack(side=tk.LEFT, padx=5)

        ttk.Label(amount_frame, text="最小成交金额(万):").pack(side=tk.LEFT, padx=5)
        ttk.Button(amount_frame, text="-", width=3, command=lambda: self._adjust_amount(-200)).pack(side=tk.LEFT, padx=2)

        amount_label = ttk.Label(
            amount_frame,
            textvariable=self.amount_var,
            width=6,
            anchor="center",
            background="white",
            relief="sunken",
            padding=3
        )
        amount_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(amount_frame, text="+", width=3, command=lambda: self._adjust_amount(200)).pack(side=tk.LEFT, padx=2)

    def _create_market_cap_control(self, parent):
        """创建最大总市值控制"""
        market_cap_frame = ttk.Frame(parent)
        market_cap_frame.pack(side=tk.LEFT, padx=5)

        ttk.Label(market_cap_frame, text="最大总市值(亿):").pack(side=tk.LEFT, padx=5)
        ttk.Button(market_cap_frame, text="-", width=3, command=lambda: self._adjust_market_cap(-50)).pack(side=tk.LEFT, padx=2)

        market_cap_label = ttk.Label(
            market_cap_frame,
            textvariable=self.market_cap_var,
            width=6,
            anchor="center",
            background="white",
            relief="sunken",
            padding=3
        )
        market_cap_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(market_cap_frame, text="+", width=3, command=lambda: self._adjust_market_cap(50)).pack(side=tk.LEFT, padx=2)

    def _create_sort_control(self, parent):
        """创建排序控制"""
        ttk.Label(parent, text="排序方式:").pack(side=tk.LEFT, padx=5)

        sort_options = ["总成交金额", "涨幅", "总成笔数", "换手", "总市值", "量比"]
        sort_combo = ttk.Combobox(
            parent,
            textvariable=self.sort_var,
            values=sort_options,
            width=10,
            state="readonly"
        )
        sort_combo.pack(side=tk.LEFT, padx=5)
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self._on_sort_change())

    def _adjust_amount(self, delta: int):
        """调整最小成交金额"""
        try:
            current = int(self.amount_var.get())
            new_value = max(0, current + delta)
            self.amount_var.set(str(new_value))
            self._trigger_data_reload()
        except ValueError:
            self.amount_var.set("2000")
            self._trigger_data_reload()

    def _adjust_market_cap(self, delta: int):
        """调整最大总市值"""
        try:
            current = int(self.market_cap_var.get())
            new_value = max(0, current + delta)
            self.market_cap_var.set(str(new_value))
            self._trigger_data_reload()
        except ValueError:
            self.market_cap_var.set("200")
            self._trigger_data_reload()

    def _on_sort_change(self):
        """排序方式改变"""
        self._trigger_data_reload()

    def _trigger_data_reload(self):
        """触发数据重新加载"""
        # 这个方法将由主应用程序重写
        pass

    def get_filter_params(self) -> Dict[str, Any]:
        """获取过滤参数"""
        try:
            min_amount = int(self.amount_var.get())
        except ValueError:
            min_amount = 2000
            self.amount_var.set("2000")

        try:
            max_market_cap = int(self.market_cap_var.get())
        except ValueError:
            max_market_cap = 200
            self.market_cap_var.set("200")

        return {
            'min_amount': min_amount,
            'max_market_cap': max_market_cap,
            'sort_by': self.sort_var.get()
        }


# 数据表格组件
class DataTable(UIComponent):
    """数据表格组件"""

    def __init__(self, parent, on_item_select_callback, on_right_click_callback):
        super().__init__(parent)
        self.on_item_select_callback = on_item_select_callback
        self.on_right_click_callback = on_right_click_callback

        self.tree = None
        self.loading_frame = None
        self.loading_animation_id = None
        self.animation_angle = 0

        self.display_columns = [
            "代码", "名称", "交易所", "行业", "总市值", "最新",
            "涨幅", "今开", "最高", "最低", "换手", "量比", "总成交金额"
        ]

        self.create_ui()

    def create_ui(self):
        """创建数据表格UI"""
        table_frame = ttk.Frame(self.parent)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 表格标题
        ttk.Label(table_frame, text="交易明细", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)

        # 表格容器
        tree_container = ttk.Frame(table_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        # 创建loading覆盖层
        self._create_loading_overlay(tree_container)

        # 配置表格样式
        self._configure_table_style()

        # 创建表格
        self.tree = ttk.Treeview(tree_container, show="headings", style="Custom.Treeview")

        # 创建滚动条
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # 布局
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # 绑定事件
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

    def _create_loading_overlay(self, parent):
        """创建加载覆盖层"""
        self.loading_frame = tk.Frame(parent, bg='white', bd=2, relief='solid')

        loading_content = tk.Frame(self.loading_frame, bg='white')
        loading_content.pack(expand=True)

        self.loading_icon = tk.Label(
            loading_content,
            text="⟳",
            font=('Arial', 24),
            bg='white',
            fg='#2E86AB'
        )
        self.loading_icon.pack(pady=5)

        self.loading_text = tk.Label(
            loading_content,
            text="正在加载数据...",
            font=('Microsoft YaHei', 12),
            bg='white',
            fg='#333333'
        )
        self.loading_text.pack(pady=5)

    def _configure_table_style(self):
        """配置表格样式"""
        style = ttk.Style()
        style.configure("Custom.Treeview", font=('Microsoft YaHei', 8))
        style.configure("Custom.Treeview", rowheight=30)
        style.configure("Custom.Treeview.Heading", font=('Microsoft YaHei', 11, 'bold'))

    def _on_double_click(self, event):
        """处理双击事件"""
        if self.on_item_select_callback:
            self.on_item_select_callback(event)

    def _on_right_click(self, event):
        """处理右键点击事件"""
        if self.on_right_click_callback:
            self.on_right_click_callback(event)

    def show_loading(self):
        """显示加载动画"""
        self.loading_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.loading_frame.lift()
        self.start_loading_animation()

    def hide_loading(self):
        """隐藏加载动画"""
        self.loading_frame.place_forget()
        self.stop_loading_animation()

    def start_loading_animation(self):
        """开始loading图标旋转动画"""

        def animate():
            rotation_chars = ["⟳", "⟲", "◐", "◑", "◒", "◓"]
            char_index = (self.animation_angle // 60) % len(rotation_chars)
            self.loading_icon.config(text=rotation_chars[char_index])
            self.animation_angle = (self.animation_angle + 30) % 360
            self.loading_animation_id = self.parent.after(100, animate)

        animate()

    def stop_loading_animation(self):
        """停止loading动画"""
        if self.loading_animation_id:
            self.parent.after_cancel(self.loading_animation_id)
            self.loading_animation_id = None

    def update_data(self, df, display_columns: List[str]):
        """更新表格数据"""
        self.display_columns = display_columns
        self.show_loading()
        self.parent.after(10, lambda: self._update_table_content(df))

    def _update_table_content(self, df):
        """实际的表格更新内容"""
        try:
            # 清空现有数据
            for item in self.tree.get_children():
                self.tree.delete(item)

            # 设置列
            available_columns = [col for col in self.display_columns if col in df.columns]
            filtered_df = df[available_columns]

            self.tree["columns"] = available_columns

            # 设置列宽度
            col_widths = {
                "代码": 120, "名称": 120, "交易所": 60, "市场板块": 80, "总市值": 80,
                "今开": 70, "涨幅": 70, "最低": 70, "最高": 70, "涨停": 70, "换手": 80, "量比": 80,
                "总成笔数": 80, "总成交金额": 100, "时间金额明细": 200, "行业": 100, "最新": 70
            }

            for col in available_columns:
                self.tree.heading(col, text=col)
                self.tree.column(col, width=col_widths.get(col, 100), anchor="center")

            # 分批插入数据
            self._insert_data_batch(filtered_df, 0, available_columns)

        except Exception as e:
            logging.error(f"更新表格内容失败: {e}")
            self.hide_loading()

    def _insert_data_batch(self, df, start_index: int, columns: List[str], batch_size: int = Config.BATCH_SIZE):
        """分批插入数据"""
        try:
            end_index = min(start_index + batch_size, len(df))

            # 创建字体样式
            bold_font = Font(weight="bold")
            normal_font = Font(weight="normal")

            if "涨幅" in columns:
                change_idx = columns.index("涨幅")
                for i in range(start_index, end_index):
                    row = df.iloc[i]
                    item = self.tree.insert("", "end", values=list(row))

                    try:
                        change = float(row["涨幅"])
                        if change > 0:
                            self.tree.tag_configure(f"up_{item}", foreground='red', font=bold_font)
                            self.tree.item(item, tags=(f"up_{item}",))
                        elif change < 0:
                            self.tree.tag_configure(f"down_{item}", foreground='green', font=bold_font)
                            self.tree.item(item, tags=(f"down_{item}",))
                        else:
                            self.tree.tag_configure(f"zero_{item}", foreground='gray', font=normal_font)
                            self.tree.item(item, tags=(f"zero_{item}",))
                    except (ValueError, TypeError):
                        pass
            else:
                for i in range(start_index, end_index):
                    row = df.iloc[i]
                    self.tree.insert("", "end", values=list(row))

            # 更新界面
            self.tree.update_idletasks()

            # 继续处理下一批或完成
            if end_index < len(df):
                self.parent.after(20, lambda: self._insert_data_batch(df, end_index, columns, batch_size))
            else:
                self._finish_table_update()

        except Exception as e:
            logging.error(f"批量插入数据失败: {e}")
            self.hide_loading()

    def _finish_table_update(self):
        """完成表格更新"""
        try:
            self.tree.update_idletasks()
        finally:
            self.hide_loading()

    def get_selected_stock_info(self) -> Dict[str, str]:
        """获取选中的股票信息"""
        selection = self.tree.selection()
        if not selection:
            return {"code": "", "name": ""}

        item = selection[0]
        values = self.tree.item(item, "values")
        columns = self.tree["columns"]

        try:
            code_idx = columns.index("代码")
            name_idx = columns.index("名称")
            return {
                "code": values[code_idx],
                "name": values[name_idx]
            }
        except (ValueError, IndexError):
            return {"code": "", "name": ""}


# 主应用程序类
class StockVisualizationApp:
    """主应用程序类"""

    def __init__(self, master):
        self.master = master
        master.title("草船借箭 - 启动中...")
        Utils.center_window(master, *Config.DEFAULT_WINDOW_SIZE)
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 初始化管理器
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager()
        self.data_processor = StockDataProcessor()

        # 初始化组件
        self.announcement_bar = None
        self.control_panel = None
        self.data_table = None
        self.status_label = None

        # K线图窗口管理
        self.kline_windows = {}

        # 状态变量
        self.current_df = None

        # 创建启动UI并延迟初始化主应用
        self.create_startup_ui()
        master.after(100, self.initialize_main_app)

    def on_closing(self):
        """窗口关闭时强制退出"""
        try:
            logging.info("程序正在强制退出...")
        except:
            pass
        finally:
            import os
            os._exit(0)  # 强制退出，不执行清理

    def create_startup_ui(self):
        """创建启动时的简单UI"""
        startup_frame = tk.Frame(self.master, bg='white')
        startup_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = tk.Label(
            startup_frame,
            text="草船借箭",
            font=('Microsoft YaHei', 24, 'bold'),
            bg='white',
            fg='#2E86AB'
        )
        title_label.pack(pady=(150, 20))

        # 启动提示
        self.startup_label = tk.Label(
            startup_frame,
            text="正在启动程序...",
            font=('Microsoft YaHei', 12),
            bg='white',
            fg='#666666'
        )
        self.startup_label.pack(pady=10)

        # 进度条
        self.progress = ttk.Progressbar(startup_frame, mode='indeterminate', length=300)
        self.progress.pack(pady=20)
        self.progress.start()

    def initialize_main_app(self):
        """初始化主应用程序"""
        try:
            # 更新启动状态
            self.startup_label.config(text="正在加载配置...")
            self.master.update()

            # 清除启动界面
            for widget in self.master.winfo_children():
                widget.destroy()

            # 创建主界面
            self.master.title("草船借箭")
            self.main_frame = ttk.Frame(self.master)
            self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            # 创建各个组件
            self.announcement_bar = AnnouncementBar(self.main_frame, self.config_manager)

            self.control_panel = ControlPanel(
                self.main_frame,
                self.fetch_data,
                self.select_columns
            )
            # 重写控制面板的数据重新加载触发器
            self.control_panel._trigger_data_reload = self.load_data

            self.data_table = DataTable(
                self.main_frame,
                self.show_detail,
                self.on_right_click
            )

            # 状态标签
            self.status_label = ttk.Label(
                self.main_frame,
                text="界面加载完成，点击刷新数据获取股票信息"
            )
            self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

            # 创建右键菜单
            self.create_context_menu()

            # 启动定期清理任务
            self.start_cleanup_task()

            # 询问是否立即加载数据
            self.show_data_load_option()

        except Exception as e:
            logging.error(f"初始化主应用程序失败: {e}")
            messagebox.showerror("启动错误", f"程序启动失败: {str(e)}")

    def create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = tk.Menu(self.master, tearoff=0)
        self.context_menu.add_command(label="大笔买入", command=self.show_big_buy_orders)
        self.context_menu.add_command(label="基本面分析", command=self.show_fundamental)
        self.context_menu.add_command(label="资金流", command=self.show_fund_flow)
        self.context_menu.add_command(label="K线图", command=self.show_k_line)
        self.context_menu.add_command(label="历史行情数据", command=self.show_historical_data)
        self.context_menu.add_command(label="AI诊股", command=self.show_ai_diagnose)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制股票代码", command=self.copy_stock_code)
        self.context_menu.add_command(label="复制股票名称", command=self.copy_stock_name)
        self.context_menu.add_command(label="复制股票名称和代码", command=self.copy_stock_name_code)

    def start_cleanup_task(self):
        """启动定期清理任务"""

        def periodic_cleanup():
            self.cleanup_closed_windows()
            self.master.after(Config.CLEANUP_INTERVAL, periodic_cleanup)

        self.master.after(Config.CLEANUP_INTERVAL, periodic_cleanup)

    def show_data_load_option(self):
        """显示数据加载选项"""
        result = messagebox.askyesno(
            "数据加载",
            "是否立即加载股票数据？\n\n点击'是'立即加载（可能需要几分钟）\n点击'否'稍后手动加载"
        )
        if result:
            threading.Thread(target=self.fetch_data, daemon=True).start()
        else:
            self.status_label.config(text="程序已就绪，点击'刷新数据'按钮开始获取股票信息")

    def fetch_data(self):
        """获取股票数据"""
        try:
            # 初始化数据模块
            if not module_manager._initialized:
                self.status_label.config(text="正在初始化数据模块...")
                self.master.update()
                module_manager.initialize_data_modules()

            ak = module_manager.ak
            pd = module_manager.pd

            # 获取大笔买入数据
            self.status_label.config(text="正在获取大笔买入数据...")
            self.master.update()

            stock_changes_em_df = ak.stock_changes_em(symbol="大笔买入")

            # 处理相关信息字段
            split_info = stock_changes_em_df['相关信息'].str.split(',', expand=True)
            split_info.columns = ['成交量', '成交价', '占成交量比', '成交金额']
            for col in split_info.columns:
                split_info[col] = pd.to_numeric(split_info[col], errors='coerce')

            stock_changes_em_df = pd.concat([
                stock_changes_em_df.drop(columns=['相关信息']),
                split_info
            ], axis=1)

            # 处理时间字段
            current_date = datetime.now().strftime('%Y%m%d')
            current_date_obj = datetime.now().date()
            stock_changes_em_df['时间'] = pd.to_datetime(
                current_date_obj.strftime('%Y-%m-%d') + ' ' +
                stock_changes_em_df['时间'].apply(lambda x: x.strftime('%H:%M:%S')),
                format='%Y-%m-%d %H:%M:%S'
            )

            # 保存大笔买入数据
            self.status_label.config(text="正在保存大笔买入数据到数据库...")
            self.master.update()
            self.db_manager.save_stock_changes(stock_changes_em_df, current_date)

            # 获取股票列表并过滤
            stock_info = stock_changes_em_df[['代码', '名称']].drop_duplicates(subset=['代码'])

            def filter_stocks(row):
                exchange, market = Utils.get_stock_info(row['代码'])
                return not (exchange == 'bj' or market == '科创板' or market == '创业板')

            filtered_stock_info = stock_info[stock_info.apply(filter_stocks, axis=1)]
            total_stocks = len(filtered_stock_info)

            self.status_label.config(text=f"开始获取 {total_stocks} 只股票的实时数据...")
            self.master.update()

            # 进度回调函数
            def progress_callback(processed_count, total_count, failed_count):
                progress_percentage = (processed_count / total_count) * 100
                self.status_label.config(
                    text=f"正在获取股票数据... {processed_count}/{total_count} "
                         f"({progress_percentage:.1f}%) - 成功:{processed_count - failed_count} 失败:{failed_count}"
                )
                self.master.update()

            # 处理股票数据
            stock_list = [(row['代码'], row['名称']) for _, row in filtered_stock_info.iterrows()]
            real_data_list = self.data_processor.process(stock_list, progress_callback)

            # 保存实时数据
            if real_data_list:
                self.status_label.config(text="正在保存股票实时数据到数据库...")
                self.master.update()

                stock_real_data_df = pd.DataFrame(real_data_list)
                self.db_manager.save_stock_real_data(stock_real_data_df, current_date)

                # 保存到Excel
                self._save_to_excel(stock_real_data_df)

                # 加载数据到界面
                self.status_label.config(text="正在加载数据到表格...")
                self.master.update()
                self.load_data()

                # 最终状态
                successful_count = len(real_data_list)
                final_message = f"数据刷新完成！成功获取 {successful_count} 只股票数据"
                if self.data_processor.failed_count > 0:
                    final_message += f"（失败 {self.data_processor.failed_count} 只）"
                self.status_label.config(text=final_message)
            else:
                self.status_label.config(text="未获取到任何股票数据")

        except Exception as e:
            logging.error(f"数据获取失败: {e}")
            self.status_label.config(text=f"数据获取失败: {str(e)}")

    def _save_to_excel(self, df, filename: str = "stock_data.xlsx"):
        """保存数据到Excel"""
        try:
            df.to_excel(filename, index=False, engine='openpyxl')
            logging.info(f"数据已保存到 {filename}")
        except Exception as e:
            logging.error(f"保存Excel文件失败: {e}")

    def load_data(self):
        """加载数据到表格"""
        try:
            # 获取过滤参数
            filter_params = self.control_panel.get_filter_params()
            current_date = datetime.now().strftime('%Y%m%d')

            # 从数据库加载数据
            full_df = self.db_manager.load_filtered_data(
                current_date,
                filter_params['min_amount'],
                filter_params['max_market_cap'],
                filter_params['sort_by']
            )

            if not full_df.empty:
                self.current_df = full_df
                self.data_table.update_data(full_df, self.data_table.display_columns)

                # 更新状态
                self.status_label.config(text=f"已加载 {len(full_df)} 条数据")
            else:
                self.status_label.config(text="没有找到符合条件的数据，请先刷新数据或调整筛选条件")

        except Exception as e:
            logging.error(f"加载数据失败: {e}")
            self.status_label.config(text="加载数据失败，请先刷新数据")

    def select_columns(self):
        """选择显示列"""
        select_window = tk.Toplevel(self.master)
        select_window.title("选择显示字段")
        Utils.center_window(select_window, 300, 600)

        all_columns = [
            "代码", "名称", "行业", "交易所", "市场板块", "总市值",
            "今开", "涨幅", "最新", "最低", "最高", "涨停",
            "换手", "量比", "总成笔数", "总成交金额", "时间金额明细"
        ]

        column_vars = {}
        for col in all_columns:
            var = tk.BooleanVar(value=col in self.data_table.display_columns)
            column_vars[col] = var
            cb = ttk.Checkbutton(select_window, text=col, variable=var)
            cb.pack(anchor=tk.W, padx=10, pady=2)

        def apply_selection():
            self.data_table.display_columns = [
                col for col, var in column_vars.items() if var.get()
            ]
            select_window.destroy()
            if self.current_df is not None:
                self.data_table.update_data(self.current_df, self.data_table.display_columns)

        ttk.Button(select_window, text="确认", command=apply_selection).pack(side=tk.BOTTOM, pady=10)

    def show_detail(self, event):
        """显示详细信息"""
        selection = self.data_table.tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.data_table.tree.item(item, "values")
        columns = self.data_table.tree["columns"]

        detail_window = tk.Toplevel(self.master)
        detail_window.title(f"{values[columns.index('名称')]} ({values[columns.index('代码')]}) 详细信息")
        Utils.center_window(detail_window, 600, 400)

        text = tk.Text(detail_window, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        info_lines = [f"{col}: {value}" for col, value in zip(columns, values)]
        info = "\n".join(info_lines)
        text.insert(tk.END, info)

        # 设置涨幅颜色
        if "涨幅" in columns:
            try:
                change_idx = columns.index("涨幅")
                change = float(values[change_idx])
                color = 'red' if change > 0 else 'green' if change < 0 else 'gray'
                font = ('Microsoft YaHei', 10, 'bold') if change != 0 else ('Microsoft YaHei', 10, 'normal')

                for i, line in enumerate(info_lines, 1):
                    if line.startswith("涨幅:"):
                        text.tag_add("change", f"{i}.0", f"{i}.0 lineend")
                        text.tag_config("change", foreground=color, font=font)
                        break
            except (ValueError, IndexError):
                pass

        text.config(state=tk.DISABLED)

    def on_right_click(self, event):
        """处理右键点击"""
        item = self.data_table.tree.identify_row(event.y)
        if item:
            self.data_table.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def show_big_buy_orders(self):
        """显示大笔买入明细"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        stock_code = selected_stock["code"]
        stock_name = selected_stock["name"]
        current_date = datetime.now().strftime('%Y%m%d')

        # 创建窗口
        detail_window = tk.Toplevel(self.master)
        detail_window.title(f"大笔买入明细 - {stock_name}({stock_code})")
        Utils.center_window(detail_window, 900, 600)
        detail_window.resizable(True, True)

        # 创建主框架
        main_frame = ttk.Frame(detail_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题
        title_label = ttk.Label(
            main_frame,
            text=f"{stock_name}({stock_code}) - 大笔买入明细",
            font=('Microsoft YaHei', 14, 'bold')
        )
        title_label.pack(pady=(0, 10))

        # 创建表格
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("时间", "代码", "名称", "板块", "成交量", "成交价", "占成交量比", "成交金额")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=20)

        # 设置列
        column_widths = {
            "时间": 150, "代码": 80, "名称": 100, "板块": 100,
            "成交量": 100, "成交价": 80, "占成交量比": 100, "成交金额": 120
        }

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=column_widths.get(col, 100), anchor="center")

        # 滚动条
        v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 布局
        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # 状态和统计
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        status_label = ttk.Label(status_frame, text="正在加载数据...")
        status_label.pack(side=tk.LEFT)

        stats_label = ttk.Label(status_frame, text="", font=('Microsoft YaHei', 9))
        stats_label.pack(side=tk.RIGHT)

        # 异步加载数据
        def load_big_buy_data():
            try:
                rows = self.db_manager.load_big_buy_orders(stock_code, current_date)

                def update_ui():
                    if not rows:
                        status_label.config(text="未找到该股票的大笔买入数据")
                        return

                    total_amount = 0
                    total_volume = 0

                    for row in rows:
                        formatted_row = list(row)

                        # 格式化时间
                        if formatted_row[0]:
                            try:
                                time_obj = datetime.strptime(str(formatted_row[0]), '%Y-%m-%d %H:%M:%S')
                                formatted_row[0] = time_obj.strftime('%H:%M:%S')
                            except:
                                pass

                        # 格式化数字
                        try:
                            if formatted_row[4]:  # 成交量
                                volume = float(formatted_row[4])
                                formatted_row[4] = Utils.format_number(volume, 0)
                                total_volume += volume

                            if formatted_row[5]:  # 成交价
                                price = float(formatted_row[5])
                                formatted_row[5] = Utils.format_number(price, 2)

                            if formatted_row[6]:  # 占成交量比
                                ratio = float(formatted_row[6])
                                formatted_row[6] = f"{ratio:.2f}%"

                            if formatted_row[7]:  # 成交金额
                                amount = float(formatted_row[7])
                                formatted_row[7] = Utils.format_number(amount, 0)
                                total_amount += amount
                        except:
                            pass

                        tree.insert("", "end", values=formatted_row)

                    # 更新统计信息
                    status_label.config(text=f"共找到 {len(rows)} 条大笔买入记录")
                    stats_text = f"总成交量: {Utils.format_number(total_volume, 0)}手  总成交金额: {total_amount / 10000:.1f}万元"
                    stats_label.config(text=stats_text)

                    logging.info(f"加载 {stock_name}({stock_code}) 大笔买入数据完成，共{len(rows)}条记录")

                detail_window.after(0, update_ui)

            except Exception as e:
                logging.error(f"加载大笔买入数据失败: {e}")
                detail_window.after(0, lambda: status_label.config(text=f"数据加载失败: {str(e)}"))

        threading.Thread(target=load_big_buy_data, daemon=True).start()

    def show_fundamental(self):
        """显示基本面分析"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        messagebox.showinfo(
            "基本面分析",
            f"正在获取 {selected_stock['name']}({selected_stock['code']}) 的基本面数据...\n\n"
            "功能实现中，这里可以展示:\n- 财务指标(PE, PB, ROE等)\n- 业绩预告\n- 股东信息\n- 行业对比"
        )

    def show_fund_flow(self):
        """显示资金流向"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if not module_manager._initialized:
            try:
                module_manager.initialize_data_modules()
            except Exception as e:
                messagebox.showerror("错误", f"加载数据模块失败: {str(e)}")
                return

        stock_code = selected_stock["code"]
        stock_name = selected_stock["name"]

        # 创建资金流窗口
        fund_flow_window = tk.Toplevel(self.master)
        fund_flow_window.title(f"个股资金流（最近10天） - {stock_name}({stock_code})")
        Utils.center_window(fund_flow_window, 1200, 750)

        # 创建主框架
        main_frame = ttk.Frame(fund_flow_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题
        title_label = ttk.Label(
            main_frame,
            text=f"{stock_name}({stock_code}) - 资金流向分析（最近10天）",
            font=('Microsoft YaHei', 14, 'bold')
        )
        title_label.pack(pady=(0, 10))

        # 状态标签
        status_label = ttk.Label(main_frame, text="正在获取资金流数据...")
        status_label.pack(pady=5)

        # 创建表格
        self._create_fund_flow_table(main_frame, stock_code, stock_name, status_label)

    def _create_fund_flow_table(self, parent, stock_code: str, stock_name: str, status_label):
        """创建资金流表格"""
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = [
            "日期", "收盘价", "涨跌幅(%)", "主力净流入-净额", "主力净流入-净占比(%)",
            "超大单净流入-净额", "超大单净流入-净占比(%)", "大单净流入-净额"
        ]

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        # 设置列
        col_widths = {
            "日期": 100, "收盘价": 80, "涨跌幅(%)": 80,
            "主力净流入-净额": 120, "主力净流入-净占比(%)": 130,
            "超大单净流入-净额": 130, "超大单净流入-净占比(%)": 140,
            "大单净流入-净额": 120
        }

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_widths.get(col, 100), anchor="center")

        # 滚动条
        v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 布局
        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # 异步获取资金流数据
        def fetch_fund_flow_data():
            try:
                ak = module_manager.ak
                pd = module_manager.pd

                # 确定交易所
                exchange, _ = Utils.get_stock_info(stock_code)
                market_mapping = {'sh': 'sh', 'sz': 'sz', 'bj': 'bj'}
                market = market_mapping.get(exchange, 'sh')

                status_label.config(text=f"正在获取{stock_name}({stock_code})的资金流数据...")
                parent.update()

                # 获取资金流数据
                fund_flow_df = ak.stock_individual_fund_flow(stock=stock_code, market=market)

                if fund_flow_df.empty:
                    status_label.config(text="未获取到资金流数据")
                    return

                # 处理数据
                if '日期' in fund_flow_df.columns:
                    fund_flow_df['日期'] = pd.to_datetime(fund_flow_df['日期'])
                    fund_flow_df = fund_flow_df.sort_values('日期', ascending=False).head(20)
                else:
                    fund_flow_df = fund_flow_df.tail(20).iloc[::-1]

                status_label.config(text=f"获取到最近 {len(fund_flow_df)} 天的资金流数据")

                # 插入数据
                for item in tree.get_children():
                    tree.delete(item)

                for index, row in fund_flow_df.iterrows():
                    values = [
                        str(row['日期'].date()) if pd.notna(row['日期']) and hasattr(row['日期'], 'date') else str(row['日期']) if pd.notna(row['日期']) else "",
                        Utils.format_number(row['收盘价'], 2) if pd.notna(row['收盘价']) else "0.00",
                        Utils.format_number(row['涨跌幅'], 2) if pd.notna(row['涨跌幅']) else "0.00",
                        Utils.format_number(row['主力净流入-净额'] / 10000, 0) if pd.notna(row['主力净流入-净额']) else "0",
                        Utils.format_number(row['主力净流入-净占比'], 2) if pd.notna(row['主力净流入-净占比']) else "0.00",
                        Utils.format_number(row['超大单净流入-净额'] / 10000, 0) if pd.notna(row['超大单净流入-净额']) else "0",
                        Utils.format_number(row['超大单净流入-净占比'], 2) if pd.notna(row['超大单净流入-净占比']) else "0.00",
                        Utils.format_number(row['大单净流入-净额'] / 10000, 0) if pd.notna(row['大单净流入-净额']) else "0"
                    ]

                    item = tree.insert("", "end", values=values)

                    # 设置颜色
                    try:
                        change_pct = float(row['涨跌幅'])
                        if change_pct > 0:
                            tree.tag_configure(f"up_{item}", foreground='red')
                            tree.item(item, tags=(f"up_{item}",))
                        elif change_pct < 0:
                            tree.tag_configure(f"down_{item}", foreground='green')
                            tree.item(item, tags=(f"down_{item}",))
                    except (ValueError, TypeError):
                        pass

                    # 设置背景色
                    try:
                        main_flow = float(row['主力净流入-净额'])
                        if main_flow > 0:
                            tree.tag_configure(f"inflow_{item}", background='#FFE4E1')
                            current_tags = tree.item(item, "tags")
                            tree.item(item, tags=current_tags + (f"inflow_{item}",))
                        elif main_flow < 0:
                            tree.tag_configure(f"outflow_{item}", background='#E0FFE0')
                            current_tags = tree.item(item, "tags")
                            tree.item(item, tags=current_tags + (f"outflow_{item}",))
                    except (ValueError, TypeError):
                        pass

                # 添加统计信息
                self._add_fund_flow_statistics(parent, fund_flow_df)

                logging.info(f"成功获取{stock_name}({stock_code})的资金流数据: 最近{len(fund_flow_df)}天的记录")

            except Exception as e:
                logging.error(f"获取资金流数据失败: {e}")
                status_label.config(text=f"获取资金流数据失败: {str(e)}")
                messagebox.showerror("错误", f"获取资金流数据失败: {str(e)}")

        threading.Thread(target=fetch_fund_flow_data, daemon=True).start()

    def _add_fund_flow_statistics(self, parent, fund_flow_df):
        """添加资金流统计信息"""
        stats_frame = ttk.LabelFrame(parent, text="统计信息（最近10天）", padding=10)
        stats_frame.pack(fill=tk.X, pady=(10, 0))

        # 计算统计数据
        recent_3_flow = fund_flow_df.head(3)['主力净流入-净额'].sum() if len(fund_flow_df) >= 3 else fund_flow_df['主力净流入-净额'].sum()
        recent_5_flow = fund_flow_df.head(5)['主力净流入-净额'].sum() if len(fund_flow_df) >= 5 else fund_flow_df['主力净流入-净额'].sum()
        recent_10_flow = fund_flow_df.head(10)['主力净流入-净额'].sum() if len(fund_flow_df) >= 10 else fund_flow_df['主力净流入-净额'].sum()
        avg_main_flow = fund_flow_df.head(10)['主力净流入-净额'].mean()

        # 计算流入流出天数
        inflow_days = len(fund_flow_df[fund_flow_df['主力净流入-净额'] > 0])
        outflow_days = len(fund_flow_df[fund_flow_df['主力净流入-净额'] < 0])

        # 日期范围
        if '日期' in fund_flow_df.columns and len(fund_flow_df) > 0:
            latest_date = fund_flow_df['日期'].max().strftime('%Y-%m-%d') if hasattr(fund_flow_df['日期'].max(), 'strftime') else str(fund_flow_df['日期'].max())
            earliest_date = fund_flow_df['日期'].min().strftime('%Y-%m-%d') if hasattr(fund_flow_df['日期'].min(), 'strftime') else str(fund_flow_df['日期'].min())
            date_range_text = f"数据范围: {earliest_date} 至 {latest_date}"
        else:
            date_range_text = f"共 {len(fund_flow_df)} 天数据"

        # 统计文本
        stats_text1 = f"10天总主力净流入: {recent_10_flow / 10000:.0f}万元  |  日均主力净流入: {avg_main_flow / 10000:.0f}万元"
        stats_text2 = f"近3天主力净流入: {recent_3_flow / 10000:.0f}万元  |  近5天主力净流入: {recent_5_flow / 10000:.0f}万元"
        stats_text3 = f"净流入天数: {inflow_days}天  |  净流出天数: {outflow_days}天  |  {date_range_text}"

        ttk.Label(stats_frame, text=stats_text1, font=('Microsoft YaHei', 10)).pack(pady=2)
        ttk.Label(stats_frame, text=stats_text2, font=('Microsoft YaHei', 10)).pack(pady=2)
        ttk.Label(stats_frame, text=stats_text3, font=('Microsoft YaHei', 10)).pack(pady=2)

        # 说明
        info_frame = ttk.Frame(parent)
        info_frame.pack(fill=tk.X, pady=(5, 0))

        info_text = "说明: 数据按时间倒序排列（最新在前）；红色表示上涨，绿色表示下跌；浅红色背景表示主力净流入，浅绿色背景表示主力净流出；单位：万元"
        ttk.Label(info_frame, text=info_text, font=('Microsoft YaHei', 9), foreground='gray').pack()

    def show_historical_data(self):
        """显示历史行情数据"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if not module_manager._initialized:
            try:
                module_manager.initialize_data_modules()
            except Exception as e:
                messagebox.showerror("错误", f"加载数据模块失败: {str(e)}")
                return

        stock_code = selected_stock["code"]
        stock_name = selected_stock["name"]

        # 创建历史行情窗口
        history_window = tk.Toplevel(self.master)
        history_window.title(f"历史行情数据（最近一个月） - {stock_name}({stock_code})")
        Utils.center_window(history_window, 1400, 800)

        # 创建主框架
        main_frame = ttk.Frame(history_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题
        title_label = ttk.Label(
            main_frame,
            text=f"{stock_name}({stock_code}) - 历史行情数据（最近一个月）",
            font=('Microsoft YaHei', 14, 'bold')
        )
        title_label.pack(pady=(0, 10))

        # 状态标签
        status_label = ttk.Label(main_frame, text="正在获取历史行情数据...")
        status_label.pack(pady=5)

        # 创建历史行情表格
        self._create_historical_data_table(main_frame, stock_code, stock_name, status_label)

    def _create_historical_data_table(self, parent, stock_code: str, stock_name: str, status_label):
        """创建历史行情数据表格"""
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill=tk.BOTH, expand=True)

        # 定义表格列
        columns = [
            "日期", "股票代码", "开盘", "收盘", "最高", "最低",
            "成交量(手)", "成交额(万元)", "振幅(%)", "涨跌幅(%)", "涨跌额", "换手率(%)"
        ]

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=20)

        # 设置列宽度
        col_widths = {
            "日期": 100, "股票代码": 80, "开盘": 80, "收盘": 80, "最高": 80, "最低": 80,
            "成交量(手)": 120, "成交额(万元)": 120, "振幅(%)": 80, "涨跌幅(%)": 80,
            "涨跌额": 80, "换手率(%)": 90
        }

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_widths.get(col, 100), anchor="center")

        # 添加滚动条
        v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 布局
        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # 异步获取历史行情数据
        def fetch_historical_data():
            try:
                ak = module_manager.ak
                pd = module_manager.pd

                # 计算最近一个月的日期范围
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)

                start_date_str = start_date.strftime('%Y%m%d')
                end_date_str = end_date.strftime('%Y%m%d')

                status_label.config(text=f"正在获取{stock_name}({stock_code})的历史行情数据...")
                parent.update()

                # 调用akshare获取历史行情数据
                stock_zh_a_hist_df = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date_str,
                    end_date=end_date_str,
                    adjust=""
                )

                if stock_zh_a_hist_df.empty:
                    status_label.config(text="未获取到历史行情数据")
                    return

                # 按日期降序排序（最新的在前面）
                stock_zh_a_hist_df = stock_zh_a_hist_df.sort_values('日期', ascending=False)

                status_label.config(text=f"获取到最近 {len(stock_zh_a_hist_df)} 天的历史行情数据")

                # 清空现有数据
                for item in tree.get_children():
                    tree.delete(item)

                # 插入数据到表格
                for index, row in stock_zh_a_hist_df.iterrows():
                    values = [
                        str(row['日期']) if pd.notna(row['日期']) else "",
                        str(row['股票代码']) if pd.notna(row['股票代码']) else "",
                        Utils.format_number(row['开盘'], 2) if pd.notna(row['开盘']) else "0.00",
                        Utils.format_number(row['收盘'], 2) if pd.notna(row['收盘']) else "0.00",
                        Utils.format_number(row['最高'], 2) if pd.notna(row['最高']) else "0.00",
                        Utils.format_number(row['最低'], 2) if pd.notna(row['最低']) else "0.00",
                        Utils.format_number(row['成交量'], 0) if pd.notna(row['成交量']) else "0",
                        Utils.format_number(row['成交额'] / 10000, 0) if pd.notna(row['成交额']) else "0",  # 转换为万元
                        Utils.format_number(row['振幅'], 2) if pd.notna(row['振幅']) else "0.00",
                        Utils.format_number(row['涨跌幅'], 2) if pd.notna(row['涨跌幅']) else "0.00",
                        Utils.format_number(row['涨跌额'], 2) if pd.notna(row['涨跌额']) else "0.00",
                        Utils.format_number(row['换手率'], 2) if pd.notna(row['换手率']) else "0.00"
                    ]

                    item = tree.insert("", "end", values=values)

                    # 根据涨跌幅设置颜色
                    try:
                        change_pct = float(row['涨跌幅'])
                        if change_pct > 0:
                            tree.tag_configure(f"up_{item}", foreground='red')
                            tree.item(item, tags=(f"up_{item}",))
                        elif change_pct < 0:
                            tree.tag_configure(f"down_{item}", foreground='green')
                            tree.item(item, tags=(f"down_{item}",))
                    except (ValueError, TypeError):
                        pass

                # 添加统计信息
                self._add_historical_data_statistics(parent, stock_zh_a_hist_df, stock_name, stock_code)

                logging.info(f"成功获取{stock_name}({stock_code})的历史行情数据: 最近{len(stock_zh_a_hist_df)}天的记录")

            except Exception as e:
                logging.error(f"获取历史行情数据失败: {e}")
                status_label.config(text=f"获取历史行情数据失败: {str(e)}")
                messagebox.showerror("错误", f"获取历史行情数据失败: {str(e)}")

        threading.Thread(target=fetch_historical_data, daemon=True).start()

    def _add_historical_data_statistics(self, parent, hist_df, stock_name: str, stock_code: str):
        """添加历史行情数据统计信息"""
        stats_frame = ttk.LabelFrame(parent, text="统计信息（最近一个月）", padding=10)
        stats_frame.pack(fill=tk.X, pady=(10, 0))

        try:
            # 计算统计数据
            pd = module_manager.pd

            if len(hist_df) == 0:
                return

            # 按日期排序计算统计信息
            hist_df_sorted = hist_df.sort_values('日期', ascending=True)

            # 基本统计
            latest_price = hist_df_sorted['收盘'].iloc[-1] if len(hist_df_sorted) > 0 else 0
            earliest_price = hist_df_sorted['收盘'].iloc[0] if len(hist_df_sorted) > 0 else 0

            # 期间涨跌幅
            period_change = ((latest_price - earliest_price) / earliest_price * 100) if earliest_price != 0 else 0

            # 最高最低价
            max_price = hist_df['最高'].max()
            min_price = hist_df['最低'].min()

            # 平均成交量和成交额
            avg_volume = hist_df['成交量'].mean()
            total_amount = hist_df['成交额'].sum()
            avg_amount = hist_df['成交额'].mean()

            # 涨跌天数统计
            up_days = len(hist_df[hist_df['涨跌幅'] > 0])
            down_days = len(hist_df[hist_df['涨跌幅'] < 0])
            flat_days = len(hist_df[hist_df['涨跌幅'] == 0])

            # 最大涨跌幅
            max_gain = hist_df['涨跌幅'].max()
            max_loss = hist_df['涨跌幅'].min()

            # 日期范围
            if '日期' in hist_df.columns and len(hist_df) > 0:
                latest_date = hist_df['日期'].max()
                earliest_date = hist_df['日期'].min()
                date_range_text = f"数据范围: {earliest_date} 至 {latest_date}"
            else:
                date_range_text = f"共 {len(hist_df)} 天数据"

            # 创建统计信息显示
            stats_text1 = f"期间涨跌幅: {period_change:+.2f}%  |  最新收盘价: {Utils.format_number(latest_price, 2)}元  |  期间最高: {Utils.format_number(max_price, 2)}元  |  期间最低: {Utils.format_number(min_price, 2)}元"

            stats_text2 = f"上涨天数: {up_days}天  |  下跌天数: {down_days}天  |  平盘天数: {flat_days}天  |  最大单日涨幅: {max_gain:.2f}%  |  最大单日跌幅: {max_loss:.2f}%"

            stats_text3 = f"日均成交量: {Utils.format_number(avg_volume, 0)}手  |  日均成交额: {Utils.format_number(avg_amount / 10000, 0)}万元  |  总成交额: {Utils.format_number(total_amount / 100000000, 2)}亿元"

            stats_text4 = date_range_text

            # 显示统计信息
            ttk.Label(stats_frame, text=stats_text1, font=('Microsoft YaHei', 10)).pack(pady=2)
            ttk.Label(stats_frame, text=stats_text2, font=('Microsoft YaHei', 10)).pack(pady=2)
            ttk.Label(stats_frame, text=stats_text3, font=('Microsoft YaHei', 10)).pack(pady=2)
            ttk.Label(stats_frame, text=stats_text4, font=('Microsoft YaHei', 10)).pack(pady=2)

            # 添加说明
            info_frame = ttk.Frame(parent)
            info_frame.pack(fill=tk.X, pady=(5, 0))

            info_text = "说明: 数据按时间倒序排列（最新在前）；红色表示上涨，绿色表示下跌；成交量单位：手，成交额单位：万元"
            ttk.Label(info_frame, text=info_text, font=('Microsoft YaHei', 9), foreground='gray').pack()

            # 添加导出按钮
            button_frame = ttk.Frame(parent)
            button_frame.pack(fill=tk.X, pady=(10, 0))

            def export_to_excel():
                try:
                    filename = f"{stock_name}({stock_code})_历史行情_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    hist_df.to_excel(filename, index=False, engine='openpyxl')
                    messagebox.showinfo("导出成功", f"数据已导出到文件：{filename}")
                    logging.info(f"历史行情数据已导出到: {filename}")
                except Exception as e:
                    logging.error(f"导出Excel失败: {e}")
                    messagebox.showerror("导出失败", f"导出Excel失败: {str(e)}")

            #ttk.Button(button_frame, text="导出Excel", command=export_to_excel).pack(side=tk.RIGHT, padx=5)

        except Exception as e:
            logging.error(f"生成历史行情统计信息失败: {e}")
            # 如果统计计算失败，至少显示基本信息
            simple_stats = f"共获取到 {len(hist_df)} 天的历史行情数据"
            ttk.Label(stats_frame, text=simple_stats, font=('Microsoft YaHei', 10)).pack(pady=2)

    def show_k_line(self):
        """显示K线图"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if not module_manager._initialized:
            try:
                module_manager.initialize_data_modules()
            except Exception as e:
                messagebox.showerror("错误", f"加载图表模块失败: {str(e)}")
                return

        stock_code = selected_stock["code"]
        stock_name = selected_stock["name"]

        window_key = f"{stock_code}_{stock_name}"
        if window_key in self.kline_windows:
            existing_window = self.kline_windows[window_key]
            if existing_window.window and existing_window.window.winfo_exists():
                existing_window.window.lift()
                existing_window.window.focus()
                return
            else:
                del self.kline_windows[window_key]

        try:
            kline_window = KLineWindow(self.master, stock_code, stock_name)
            self.kline_windows[window_key] = kline_window
            logging.info(f"创建K线图窗口: {stock_name}({stock_code}), 当前活跃窗口数: {len(self.kline_windows)}")
            self.status_label.config(text=f"已打开 {stock_name}({stock_code}) 的K线图")
        except Exception as e:
            logging.error(f"创建K线图窗口失败: {e}")
            messagebox.showerror("错误", f"创建K线图窗口失败: {str(e)}")

    def show_ai_diagnose(self):
        """显示AI诊股"""
        selected_stock = self.data_table.get_selected_stock_info()
        if not selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        # 初始化OpenAI客户端
        try:
            api_key = self.config_manager.get_api_key()
            client = module_manager.initialize_openai_client(api_key)
        except Exception as e:
            messagebox.showerror("错误", f"AI功能初始化失败: {str(e)}")
            return

        stock_code = selected_stock["code"]
        stock_name = selected_stock["name"]

        # 创建AI诊股窗口
        dialog = tk.Toplevel(self.master)
        dialog.title(f"AI诊股: {stock_name}({stock_code})")
        Utils.center_window(dialog, 600, 400)

        text_widget = tk.Text(dialog, wrap=tk.WORD, state=tk.NORMAL)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        font_bold_large = ("Microsoft YaHei", 14, "bold")
        text_widget.configure(font=font_bold_large)
        text_widget.insert(tk.END, "正在咨询AI诊股，请稍候...\n")
        text_widget.config(state=tk.DISABLED)

        def stream_gpt_response():
            prompt = f"请用中文分析股票 {stock_name}({stock_code}) 的投资价值、风险、行业地位和未来走势。"
            try:
                stream = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    extra_body={"web_search": True}
                )

                text_widget.config(state=tk.NORMAL)
                text_widget.delete(1.0, tk.END)

                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        text_widget.insert(tk.END, content)
                        text_widget.see(tk.END)
                        text_widget.update()

                text_widget.config(state=tk.DISABLED)

            except Exception as e:
                text_widget.config(state=tk.NORMAL)
                text_widget.insert(tk.END, f"\n[AI诊股失败]: {e}")
                text_widget.config(state=tk.DISABLED)

        threading.Thread(target=stream_gpt_response, daemon=True).start()

    def copy_stock_code(self):
        """复制股票代码"""
        selected_stock = self.data_table.get_selected_stock_info()
        if selected_stock["code"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(selected_stock["code"])
            self.status_label.config(text=f"已复制股票代码: {selected_stock['code']}")

    def copy_stock_name(self):
        """复制股票名称"""
        selected_stock = self.data_table.get_selected_stock_info()
        if selected_stock["name"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(selected_stock["name"])
            self.status_label.config(text=f"已复制股票名称: {selected_stock['name']}")

    def copy_stock_name_code(self):
        """复制股票名称"""
        selected_stock = self.data_table.get_selected_stock_info()
        if selected_stock["name"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(selected_stock["name"]+ f" ({selected_stock['code']})")
            self.status_label.config(text=f"已复制: {selected_stock['name']}")

    def cleanup_closed_windows(self):
        """清理已关闭的K线图窗口"""
        closed_windows = []
        for key, window in self.kline_windows.items():
            if not window.window or not window.window.winfo_exists():
                closed_windows.append(key)

        for key in closed_windows:
            del self.kline_windows[key]

        if closed_windows:
            logging.info(f"清理了 {len(closed_windows)} 个已关闭的K线图窗口")

    def __del__(self):
        """清理资源"""
        if hasattr(self, 'kline_windows'):
            for window in self.kline_windows.values():
                if window.window and window.window.winfo_exists():
                    window.window.destroy()


# 主程序入口
def main():
    """主程序入口"""
    root = tk.Tk()

    # 设置图标
    try:
        root.iconbitmap(default="logo.ico")
    except:
        pass  # 忽略图标文件不存在的错误

    # 创建应用程序
    app = StockVisualizationApp(root)

    # 启动主循环
    try:
        root.mainloop()
    except:
        pass
    finally:
        # 确保程序完全退出
        import os
        os._exit(0)


if __name__ == "__main__":
    main()