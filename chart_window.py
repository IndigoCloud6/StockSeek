"""
Chart window module for StockSeek application.
Handles K-line chart display in separate windows with technical indicators.
"""

import logging
import queue
import threading
import uuid
from datetime import datetime, timedelta

# Lazy imports for GUI components
tk = None
ttk = None

def lazy_import_gui():
    """Lazy import GUI modules"""
    global tk, ttk
    if tk is None:
        try:
            import tkinter as tk_module
            from tkinter import ttk as ttk_module
            tk = tk_module
            ttk = ttk_module
        except ImportError as e:
            logging.error(f"GUI modules not available: {e}")
            raise

from utils import center_window

# Global variables for lazy-loaded modules
ak = None
matplotlib = None
plt = None
mpf = None
pd = None
FigureCanvasTkAgg = None
NavigationToolbar2Tk = None


def lazy_import_chart_modules():
    """Lazy import chart-related modules"""
    global ak, matplotlib, plt, mpf, pd, FigureCanvasTkAgg, NavigationToolbar2Tk

    if ak is None:
        logging.info("正在导入图表处理模块...")
        try:
            import akshare as ak_module
            import matplotlib as matplotlib_module
            import matplotlib.pyplot as plt_module
            import mplfinance as mpf_module
            import pandas as pd_module
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as FigureCanvas, NavigationToolbar2Tk as NavToolbar

            ak = ak_module
            matplotlib = matplotlib_module
            plt = plt_module
            mpf = mpf_module
            pd = pd_module
            FigureCanvasTkAgg = FigureCanvas
            NavigationToolbar2Tk = NavToolbar

            # 设置matplotlib字体
            matplotlib.rcParams['font.family'] = 'Microsoft YaHei'
            matplotlib.rcParams['axes.unicode_minus'] = False

            logging.info("图表处理模块导入完成")
        except Exception as e:
            logging.error(f"导入图表处理模块失败: {e}")
            raise


class KLineWindow:
    """独立的K线图窗口类"""

    def __init__(self, parent, stock_code, stock_name):
        # Ensure GUI modules are loaded
        lazy_import_gui()
        
        self.parent = parent
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.window = None
        self.canvas = None
        self.result_queue = queue.Queue()
        self.window_id = str(uuid.uuid4())[:8]

        # 创建窗口
        self.create_window()

        # 在后台获取数据
        threading.Thread(target=self.fetch_data_async, daemon=True).start()

        # 定期检查结果
        self.check_result()

    def create_window(self):
        """创建K线图窗口"""
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"K线图 - {self.stock_name}({self.stock_code}) [ID: {self.window_id}]")
        self.window.geometry("1200x800")

        # 居中显示
        self.center_window()

        # 创建主框架
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 图表容器
        self.chart_frame = ttk.Frame(main_frame)
        self.chart_frame.pack(fill=tk.BOTH, expand=True)

        # 窗口关闭事件
        self.window.protocol("WM_DELETE_WINDOW", self.on_window_close)

    def center_window(self):
        """窗口居中"""
        center_window(self.window, 1200, 800)

    def fetch_data_async(self):
        """异步获取K线数据"""
        try:
            # 确保模块已导入
            if ak is None:
                lazy_import_chart_modules()

            # 获取交易日期逻辑
            now = datetime.now()
            current_time = now.time()
            market_open_time = datetime.strptime("09:30", "%H:%M").time()

            # 如果当前时间早于9:30，使用前一天的日期
            if current_time < market_open_time:
                target_date = now - timedelta(days=1)
            else:
                target_date = now

            # 进一步处理周末情况
            while target_date.weekday() > 4:  # 0-6代表周一到周日
                target_date = target_date - timedelta(days=1)

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

            # RSI 相对强弱指标
            def calculate_rsi(data, window=14):
                delta = data.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                return rsi

            stock_data_processed['RSI'] = calculate_rsi(stock_data_processed['Close'])

            # 将处理好的数据放入队列
            self.result_queue.put({
                'success': True,
                'data': stock_data_processed,
                'display_date': target_date.strftime('%Y-%m-%d')
            })

            logging.info(f"[{self.window_id}] {self.stock_name}({self.stock_code}) 数据获取完成")

        except Exception as e:
            logging.error(f"[{self.window_id}] 获取K线数据失败: {e}")
            self.result_queue.put({
                'success': False,
                'error': f"获取K线数据失败: {str(e)}"
            })

    def check_result(self):
        """检查数据获取结果"""
        try:
            result = self.result_queue.get_nowait()
            if result['success']:
                self.display_chart(result['data'], result['display_date'])
            else:
                self.show_error(result['error'])
        except queue.Empty:
            # 如果窗口还存在，继续检查
            if self.window and self.window.winfo_exists():
                self.window.after(100, self.check_result)

    def display_chart(self, stock_data_processed, display_date):
        """显示K线图"""
        try:
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
            main_ax = axes[0]
            legend_elements = [
                plt.Line2D([0], [0], color='blue', lw=1.5, label='MA5'),
                plt.Line2D([0], [0], color='purple', lw=1.5, label='MA10'),
                plt.Line2D([0], [0], color='orange', lw=1.5, label='MA20'),
                plt.Line2D([0], [0], color='gray', lw=1, alpha=0.7, label='布林带'),
            ]
            main_ax.legend(handles=legend_elements, loc='lower right', frameon=True,
                           fancybox=True, shadow=True, framealpha=0.9, fontsize=10)

            # 为RSI子图添加图例
            if len(axes) > 2:
                rsi_ax = axes[2]
                rsi_legend_elements = [
                    plt.Line2D([0], [0], color='purple', lw=1.5, label='RSI'),
                    plt.Line2D([0], [0], color='red', lw=0.8, linestyle='--', alpha=0.7, label='超买(70)'),
                    plt.Line2D([0], [0], color='green', lw=0.8, linestyle='--', alpha=0.7, label='超卖(30)'),
                ]
                rsi_ax.legend(handles=rsi_legend_elements, loc='lower right', frameon=True,
                              fancybox=True, shadow=True, framealpha=0.9, fontsize=9)

            # 在图表底部添加标题
            fig.suptitle(f'{self.stock_name}({self.stock_code}) - {display_date} K线图',
                         fontsize=14, fontweight='bold', y=0.05)

            # 清空图表容器
            for widget in self.chart_frame.winfo_children():
                widget.destroy()

            # 在Tkinter中嵌入matplotlib图形
            self.canvas = FigureCanvasTkAgg(fig, self.chart_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            # 添加工具栏
            toolbar = NavigationToolbar2Tk(self.canvas, self.chart_frame)
            toolbar.update()

            # 打印技术指标
            if not stock_data_processed.empty:
                latest_data = stock_data_processed.iloc[-1]
                logging.info(f"[{self.window_id}] {self.stock_name}({self.stock_code}) 最新数据:")
                logging.info(f"收盘价: {latest_data['Close']:.2f}, MA5: {latest_data['MA5']:.2f}, RSI: {latest_data['RSI']:.2f}")

        except Exception as e:
            logging.error(f"[{self.window_id}] 显示K线图失败: {e}")
            self.show_error(f"显示K线图失败: {str(e)}")

    def show_error(self, error_message):
        """显示错误信息"""
        error_frame = ttk.Frame(self.chart_frame)
        error_frame.pack(expand=True)

        ttk.Label(error_frame, text="❌", font=('Arial', 48)).pack(pady=20)
        ttk.Label(error_frame, text=error_message, font=('Microsoft YaHei', 12),
                  foreground='red', wraplength=800).pack(pady=10)

        ttk.Button(error_frame, text="重试",
                   command=lambda: self.retry_fetch()).pack(pady=10)

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