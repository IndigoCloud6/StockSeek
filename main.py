import json
import logging
import os
import queue
import sqlite3
import threading
import tkinter as tk
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tkinter import messagebox
from tkinter import ttk
from tkinter.font import Font

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置文件路径
CONFIG_FILE = "config.json"

# 默认公告内容
DEFAULT_ANNOUNCEMENTS = [
    "系统公告：所有数据来源于公开市场信息，仅供参考，不构成投资建议。"
]

DEFAULT_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 全局变量，延迟初始化
ak = None
matplotlib = None
plt = None
mpf = None
pd = None
FigureCanvasTkAgg = None
NavigationToolbar2Tk = None
client = None


# 创建配置文件（如果不存在）
def ensure_config_file():
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({"announcements": DEFAULT_ANNOUNCEMENTS, "api_key": DEFAULT_API_KEY}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"创建配置文件失败: {e}")


def lazy_import_heavy_modules():
    """延迟导入重型模块"""
    global ak, matplotlib, plt, mpf, pd, FigureCanvasTkAgg, NavigationToolbar2Tk

    if ak is None:
        logging.info("正在导入数据处理模块...")
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

            logging.info("数据处理模块导入完成")
        except Exception as e:
            logging.error(f"导入数据处理模块失败: {e}")
            raise


def lazy_init_openai_client():
    """延迟初始化OpenAI客户端"""
    global client

    if client is None:
        try:
            api_key = load_api_key()
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            logging.info("OpenAI客户端初始化完成")
        except Exception as e:
            logging.error(f"OpenAI客户端初始化失败: {e}")


# 加载API KEY
def load_api_key():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            api_key = config.get("api_key")
            if not api_key or api_key.startswith("sk-xxxx"):
                logging.error("请在config.json中配置有效的api_key")
            return api_key
    except Exception as e:
        logging.error(f"读取API Key失败: {e}")
        return DEFAULT_API_KEY


# Function to save results to Excel
def save_to_excel(results: list, filename: str = "stock_data.xlsx"):
    if pd is None:
        lazy_import_heavy_modules()
    df = pd.DataFrame(results)
    df.to_excel(filename, index=False, engine='openpyxl')
    print(f"Data saved to {filename}")


def get_stock_info(stock_code):
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


class KLineWindow:
    """独立的K线图窗口类"""

    def __init__(self, parent, stock_code, stock_name):
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
        self.window.update_idletasks()
        width = 1200
        height = 800
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry(f'{width}x{height}+{x}+{y}')

    def fetch_data_async(self):
        """异步获取K线数据"""
        try:
            # 确保模块已导入
            if ak is None:
                lazy_import_heavy_modules()

            from datetime import datetime, timedelta

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


class StockVisualizationApp:
    def __init__(self, master):
        self.master = master
        master.title("草船借箭 - 启动中...")
        self.center_window(master, 1400, 650)

        # 创建启动提示
        self.create_startup_ui()

        # 延迟初始化主界面
        master.after(100, self.initialize_main_app)

    def create_startup_ui(self):
        """创建启动时的简单UI"""
        startup_frame = tk.Frame(self.master, bg='white')
        startup_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = tk.Label(startup_frame, text="草船借箭",
                               font=('Microsoft YaHei', 24, 'bold'),
                               bg='white', fg='#2E86AB')
        title_label.pack(pady=(150, 20))

        # 启动提示
        self.startup_label = tk.Label(startup_frame, text="正在启动程序...",
                                      font=('Microsoft YaHei', 12),
                                      bg='white', fg='#666666')
        self.startup_label.pack(pady=10)

        # 进度条
        self.progress = ttk.Progressbar(startup_frame, mode='indeterminate', length=300)
        self.progress.pack(pady=20)
        self.progress.start()

    def initialize_main_app(self):
        """初始化主应用程序"""
        try:
            # 更新状态
            self.startup_label.config(text="正在加载配置...")
            self.master.update()
            # 添加进度跟踪变量
            self.processed_count = 0
            self.failed_count = 0
            self.progress_lock = threading.Lock()
            # 初始化配置
            ensure_config_file()
            self.announcements = self.load_announcements()
            self.current_announcement_idx = 0
            self.display_columns = ["代码", "名称", "交易所", "行业", "总市值", "最新", "涨幅", "今开", "最高", "最低", "换手", "量比", "总成交金额"]

            self.bold_font = Font(weight="bold")
            self.normal_font = Font(weight="normal")
            self.announcement_font = Font(family="Microsoft YaHei", size=10, weight="bold")

            # K线图窗口管理
            self.kline_windows = {}
            self.kline_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="KLine")

            self.selected_stock = {"code": "", "name": ""}

            # 更新状态
            self.startup_label.config(text="正在构建界面...")
            self.master.update()

            # 清除启动界面
            for widget in self.master.winfo_children():
                widget.destroy()

            # 创建主界面
            self.master.title("草船借箭")
            self.main_frame = ttk.Frame(self.master)
            self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            self.create_announcement_bar()
            self.status_label = ttk.Label(self.main_frame, text="界面加载完成，点击刷新数据获取股票信息")
            self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
            self.create_control_panel()
            self.create_data_table()

            # 启动后台任务
            self.update_announcement()
            self.update_clock()

            # 界面加载完成，询问是否立即加载数据
            self.show_data_load_option()

        except Exception as e:
            logging.error(f"初始化主应用程序失败: {e}")
            messagebox.showerror("启动错误", f"程序启动失败: {str(e)}")

    def show_data_load_option(self):
        """显示数据加载选项"""
        result = messagebox.askyesno("数据加载", "是否立即加载股票数据？\n\n点击'是'立即加载（可能需要几分钟）\n点击'否'稍后手动加载")
        if result:
            # 用户选择立即加载
            threading.Thread(target=self.fetch_data, daemon=True).start()
        else:
            self.status_label.config(text="程序已就绪，点击'刷新数据'按钮开始获取股票信息")

    def center_window(self, window, width, height):
        window.withdraw()
        window.update_idletasks()
        screenwidth = window.winfo_screenwidth()
        screenheight = window.winfo_screenheight()
        x = int((screenwidth - width) / 2)
        y = int((screenheight - height) / 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.deiconify()

    def load_announcements(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                announcements = config.get("announcements", DEFAULT_ANNOUNCEMENTS)
                if not announcements:
                    return DEFAULT_ANNOUNCEMENTS
                return announcements
        except Exception as e:
            logging.error(f"加载公告配置文件失败: {e}")
            return DEFAULT_ANNOUNCEMENTS

    def create_announcement_bar(self):
        announcement_frame = ttk.Frame(self.main_frame, height=30)
        announcement_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.announcement_icon = tk.Label(
            announcement_frame,
            text="📢",
            font=self.announcement_font,
            bg="#FFE4B5",
            padx=5
        )
        self.announcement_icon.pack(side=tk.LEFT, fill=tk.Y)
        self.announcement_label = tk.Label(
            announcement_frame,
            text="",
            font=self.announcement_font,
            bg="#FFE4B5",
            fg="#8B0000",
            anchor="w",
            padx=10
        )
        self.announcement_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.clock_label = tk.Label(
            announcement_frame,
            text="",
            font=("Microsoft YaHei", 10, "bold"),
            bg="#FFE4B5",
            fg="#FF0000",
            padx=10
        )
        self.clock_label.pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            announcement_frame,
            text="配置公告",
            width=10,
            command=self.configure_announcements
        ).pack(side=tk.RIGHT, padx=5)
        announcement_frame.configure(style="Announcement.TFrame")
        style = ttk.Style()
        style.configure("Announcement.TFrame", background="#FFE4B5")

    def update_clock(self):
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        self.clock_label.config(text=time_str)
        self.master.after(1000, self.update_clock)

    def update_announcement(self):
        if self.announcements:
            announcement = self.announcements[self.current_announcement_idx]
            self.announcement_label.config(text=announcement)
            self.current_announcement_idx = (self.current_announcement_idx + 1) % len(self.announcements)
            self.master.after(8000, self.update_announcement)

    def configure_announcements(self):
        config_window = tk.Toplevel(self.master)
        config_window.title("公告配置")
        self.center_window(config_window, 600, 800)
        config_window.resizable(True, True)

        outer_frame = ttk.Frame(config_window)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        text_frame = ttk.Frame(outer_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.announcement_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            font=("Microsoft YaHei", 10),
            padx=10,
            pady=10
        )
        self.announcement_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.announcement_text.yview)

        help_text = "提示：每条公告单独一行，系统将按顺序轮播显示"
        ttk.Label(outer_frame, text=help_text, foreground="gray").pack(anchor=tk.W, padx=10, pady=(6, 0))

        button_frame = ttk.Frame(outer_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)

        ttk.Button(button_frame, text="取消", command=config_window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="重置", command=self.reset_announcements).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="保存", command=lambda: self.save_announcements(config_window)).pack(side=tk.RIGHT, padx=5)

        self.load_announcements_to_text()

    def show_ai_diagnose(self):
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if client is None:
            try:
                lazy_init_openai_client()
            except Exception as e:
                messagebox.showerror("错误", f"AI功能初始化失败: {str(e)}")
                return

        stock_code = self.selected_stock["code"]
        stock_name = self.selected_stock["name"]

        dialog = tk.Toplevel(self.master)
        dialog.title(f"AI诊股: {stock_name}({stock_code})")
        self.center_window(dialog, 600, 400)
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

    def load_announcements_to_text(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                announcements = config.get("announcements", DEFAULT_ANNOUNCEMENTS)
                text = "\n".join(announcements)
                self.announcement_text.delete(1.0, tk.END)
                self.announcement_text.insert(tk.END, text)
        except Exception as e:
            logging.error(f"加载公告到文本框失败: {e}")
            self.announcement_text.insert(tk.END, "\n".join(DEFAULT_ANNOUNCEMENTS))

    def save_announcements(self, window):
        text = self.announcement_text.get(1.0, tk.END).strip()
        announcements = [line.strip() for line in text.split("\n") if line.strip()]
        if not announcements:
            messagebox.showerror("错误", "公告内容不能为空！")
            return
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({"announcements": announcements}, f, ensure_ascii=False, indent=4)
            self.announcements = announcements
            self.current_announcement_idx = 0
            self.update_announcement()
            messagebox.showinfo("成功", "公告配置已保存！")
            window.destroy()
        except Exception as e:
            logging.error(f"保存公告配置失败: {e}")
            messagebox.showerror("错误", f"保存公告配置失败: {str(e)}")

    def reset_announcements(self):
        self.announcement_text.delete(1.0, tk.END)
        self.announcement_text.insert(tk.END, "\n".join(DEFAULT_ANNOUNCEMENTS))

    def fetch_data(self):
        try:
            if ak is None:
                self.status_label.config(text="正在初始化数据模块...")
                self.master.update()
                lazy_import_heavy_modules()

            self.status_label.config(text="正在获取大笔买入数据...")
            self.master.update()

            stock_changes_em_df = ak.stock_changes_em(symbol="大笔买入")
            split_info = stock_changes_em_df['相关信息'].str.split(',', expand=True)
            split_info.columns = ['成交量', '成交价', '占成交量比', '成交金额']
            split_info['成交量'] = pd.to_numeric(split_info['成交量'], errors='coerce')
            split_info['成交价'] = pd.to_numeric(split_info['成交价'], errors='coerce')
            split_info['占成交量比'] = pd.to_numeric(split_info['占成交量比'], errors='coerce')
            split_info['成交金额'] = pd.to_numeric(split_info['成交金额'], errors='coerce')
            stock_changes_em_df = pd.concat([stock_changes_em_df.drop(columns=['相关信息']), split_info], axis=1)
            current_date = datetime.now().strftime('%Y%m%d')
            current_date_obj = datetime.now().date()
            stock_changes_em_df['时间'] = pd.to_datetime(
                current_date_obj.strftime('%Y-%m-%d') + ' ' + stock_changes_em_df['时间'].apply(lambda x: x.strftime('%H:%M:%S')),
                format='%Y-%m-%d %H:%M:%S'
            )

            self.status_label.config(text="正在保存大笔买入数据到数据库...")
            self.master.update()

            conn = sqlite3.connect('stock_data.db')
            table_name = f'stock_changes_{current_date}'
            try:
                conn.execute(f"DELETE FROM {table_name}")
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):
                    pass
                else:
                    raise
            except Exception as e:
                pass
            stock_changes_em_df.to_sql(table_name, conn, if_exists='append', index=False)
            logging.info(f"数据已成功存入 SQLite 数据库表 {table_name}！")

            # 准备处理股票实时数据
            real_data_list = []
            stock_info = stock_changes_em_df[['代码', '名称']].drop_duplicates(subset=['代码'])

            def not_bj_kcb(row):
                exchange, market = get_stock_info(row['代码'])
                return not (exchange == 'bj' or market == '科创板' or market == '创业板')

            filtered_stock_info = stock_info[stock_info.apply(not_bj_kcb, axis=1)]

            # 显示总股票数量
            total_stocks = len(filtered_stock_info)
            self.status_label.config(text=f"开始获取 {total_stocks} 只股票的实时数据...")
            self.master.update()

            # 用于跟踪进度的变量
            self.processed_count = 0
            self.failed_count = 0
            self.progress_lock = threading.Lock()

            def update_progress_status():
                """更新进度显示"""
                with self.progress_lock:
                    progress_percentage = (self.processed_count / total_stocks) * 100
                    self.status_label.config(
                        text=f"正在获取股票数据... {self.processed_count}/{total_stocks} "
                             f"({progress_percentage:.1f}%) - 成功:{self.processed_count - self.failed_count} 失败:{self.failed_count}"
                    )
                    self.master.update()

            def process_stock_with_progress(stock_code, stock_name):
                """带进度更新的process_stock包装函数"""
                try:
                    result = self.process_stock(stock_code, stock_name)

                    # 更新进度
                    with self.progress_lock:
                        self.processed_count += 1
                        if result is None:
                            self.failed_count += 1

                    # 每处理10个股票或者处理完成时更新一次状态显示（避免过于频繁更新）
                    if self.processed_count % 10 == 0 or self.processed_count == total_stocks:
                        # 使用after方法在主线程中更新UI
                        self.master.after(0, update_progress_status)

                    return result
                except Exception as e:
                    logging.error(f"处理股票 {stock_code}({stock_name}) 时出错: {e}")

                    # 更新进度
                    with self.progress_lock:
                        self.processed_count += 1
                        self.failed_count += 1

                    # 更新状态显示
                    if self.processed_count % 10 == 0 or self.processed_count == total_stocks:
                        self.master.after(0, update_progress_status)

                    return None

            max_workers = min(10, total_stocks)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 创建future到股票代码的映射
                future_to_stock = {
                    executor.submit(process_stock_with_progress, row['代码'], row['名称']): (row['代码'], row['名称'])
                    for _, row in filtered_stock_info.iterrows()
                }

                # 处理完成的任务
                for future in as_completed(future_to_stock):
                    stock_code, stock_name = future_to_stock[future]
                    try:
                        result = future.result()
                        if result:
                            real_data_list.append(result)
                    except Exception as e:
                        logging.error(f"获取股票 {stock_code}({stock_name}) 结果时出错: {e}")

            # 最终状态更新
            successful_count = len(real_data_list)
            self.status_label.config(text=f"股票数据获取完成！成功: {successful_count}/{total_stocks} 只股票")
            self.master.update()

            if not real_data_list:
                self.status_label.config(text="未获取到任何股票数据")
                return

            self.status_label.config(text="正在保存股票实时数据到数据库...")
            self.master.update()

            stock_real_data_df = pd.DataFrame(real_data_list)
            real_table_name = f'stock_real_data_{current_date}'
            try:
                conn.execute(f"DELETE FROM {real_table_name}")
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):
                    pass
                else:
                    raise
            except Exception as e:
                pass
            stock_real_data_df.to_sql(real_table_name, conn, if_exists='replace', index=False)
            logging.info(f"实时数据已成功存入 SQLite 数据库表 {real_table_name}！")
            conn.close()

            self.status_label.config(text=f"数据获取完成！共处理 {successful_count} 只股票，正在加载到表格...")
            self.master.update()

            # 加载数据到界面
            self.load_data()

            # 最终完成状态
            final_message = f"数据刷新完成！成功获取 {successful_count} 只股票数据"
            if self.failed_count > 0:
                final_message += f"（失败 {self.failed_count} 只）"
            self.status_label.config(text=final_message)

        except Exception as e:
            logging.error(f"数据获取失败: {e}")
            self.status_label.config(text=f"数据获取失败: {str(e)}")

    def process_stock(self, stock_code, stock_name):
        try:
            stock_info_df = ak.stock_individual_info_em(symbol=stock_code)
            industry = stock_info_df[stock_info_df['item'] == '行业']['value'].iloc[0] if '行业' in stock_info_df['item'].values else '未知'
            market_cap = stock_info_df[stock_info_df['item'] == '总市值']['value'].iloc[0] if '总市值' in stock_info_df['item'].values else '未知'
            stock_bid_ask_df = ak.stock_bid_ask_em(symbol=stock_code)
            latest_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '最新']['value'].iloc[0]) if '最新' in stock_bid_ask_df['item'].values else None
            price_change_percent = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '涨幅']['value'].iloc[0]) if '涨幅' in stock_bid_ask_df[
                'item'].values else None
            opening_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '今开']['value'].iloc[0]) if '今开' in stock_bid_ask_df['item'].values else None

            turnover_rate = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '换手']['value'].iloc[0]) if '换手' in stock_bid_ask_df['item'].values else None
            volume_ratio = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '量比']['value'].iloc[0]) if '量比' in stock_bid_ask_df['item'].values else None

            max_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '最高']['value'].iloc[0]) if '最高' in stock_bid_ask_df['item'].values else None
            min_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '最低']['value'].iloc[0]) if '最低' in stock_bid_ask_df['item'].values else None
            zhang_ting = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '涨停']['value'].iloc[0]) if '涨停' in stock_bid_ask_df['item'].values else None
            exchange, market = get_stock_info(stock_code)
            return {
                '代码': stock_code,
                '名称': stock_name,
                '交易所': exchange,
                '市场板块': market,
                '行业': industry,
                '总市值': int(market_cap / 100000000),
                '最新': latest_price,
                '涨幅': price_change_percent,
                '最高': max_price,
                '最低': min_price,
                '涨停': zhang_ting,
                '换手': turnover_rate,
                '量比': volume_ratio,
                '今开': opening_price
            }
        except Exception as e:
            logging.error(f"处理股票代码 {stock_code} ({stock_name}) 时出错: {e}")
            return None

    def create_control_panel(self):
        control_frame = ttk.LabelFrame(self.main_frame, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(control_frame, text="刷新数据", command=lambda: threading.Thread(target=self.fetch_data, daemon=True).start()).pack(side=tk.LEFT, padx=5)

        amount_frame = ttk.Frame(control_frame)
        amount_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(amount_frame, text="最小成交金额(万):").pack(side=tk.LEFT, padx=5)
        ttk.Button(amount_frame, text="-", width=3, command=lambda: self.adjust_amount(-200)).pack(side=tk.LEFT, padx=2)
        self.amount_var = tk.StringVar(value="2000")
        self.amount_label = ttk.Label(amount_frame, textvariable=self.amount_var, width=6, anchor="center", background="white", relief="sunken", padding=3)
        self.amount_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(amount_frame, text="+", width=3, command=lambda: self.adjust_amount(200)).pack(side=tk.LEFT, padx=2)

        market_cap_frame = ttk.Frame(control_frame)
        market_cap_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(market_cap_frame, text="最大总市值(亿):").pack(side=tk.LEFT, padx=5)
        ttk.Button(market_cap_frame, text="-", width=3, command=lambda: self.adjust_market_cap(-20)).pack(side=tk.LEFT, padx=2)
        self.market_cap_var = tk.StringVar(value="200")
        self.market_cap_label = ttk.Label(market_cap_frame, textvariable=self.market_cap_var, width=6, anchor="center", background="white", relief="sunken",
                                          padding=3)
        self.market_cap_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(market_cap_frame, text="+", width=3, command=lambda: self.adjust_market_cap(10)).pack(side=tk.LEFT, padx=2)

        ttk.Label(control_frame, text="排序方式:").pack(side=tk.LEFT, padx=5)
        self.sort_var = tk.StringVar(value="总成交金额")
        sort_options = ["总成交金额", "涨幅", "总成笔数", "换手", "量比"]
        sort_combo = ttk.Combobox(control_frame, textvariable=self.sort_var, values=sort_options, width=10, state="readonly")
        sort_combo.pack(side=tk.LEFT, padx=5)
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self.load_data())
        ttk.Button(control_frame, text="选择显示字段", command=self.select_columns).pack(side=tk.RIGHT, padx=5)

    def adjust_amount(self, delta):
        try:
            current = int(self.amount_var.get())
            new_value = max(0, current + delta)
            self.amount_var.set(str(new_value))
            self.load_data()
        except ValueError:
            self.amount_var.set("2000")
            self.load_data()

    def adjust_market_cap(self, delta):
        try:
            current = int(self.market_cap_var.get())
            new_value = max(0, current + delta)
            self.market_cap_var.set(str(new_value))
            self.load_data()
        except ValueError:
            self.market_cap_var.set("100")
            self.load_data()

    def select_columns(self):
        select_window = tk.Toplevel(self.master)
        select_window.title("选择显示字段")
        self.center_window(select_window, 300, 600)
        all_columns = [
            "代码", "名称", "行业", "交易所", "市场板块", "总市值",
            "今开", "涨幅", "最新", "最低", "最高", "涨停",
            "换手", "量比", "总成笔数", "总成交金额", "时间金额明细"
        ]
        self.column_vars = {}
        for col in all_columns:
            var = tk.BooleanVar(value=col in self.display_columns)
            self.column_vars[col] = var
            cb = ttk.Checkbutton(select_window, text=col, variable=var)
            cb.pack(anchor=tk.W, padx=10, pady=2)
        ttk.Button(select_window, text="确认", command=lambda: self.apply_column_selection(select_window)).pack(side=tk.BOTTOM, pady=10)

    def apply_column_selection(self, window):
        self.display_columns = [col for col, var in self.column_vars.items() if var.get()]
        window.destroy()
        self.load_data()

    def create_data_table(self):
        self.table_frame = ttk.Frame(self.main_frame)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(self.table_frame, text="交易明细", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)
        self.tree_container = ttk.Frame(self.table_frame)
        self.tree_container.pack(fill=tk.BOTH, expand=True)

        # 创建loading覆盖层
        self.loading_frame = tk.Frame(self.tree_container, bg='white', bd=2, relief='solid')

        loading_content = tk.Frame(self.loading_frame, bg='white')
        loading_content.pack(expand=True)

        self.loading_icon = tk.Label(loading_content, text="⟳", font=('Arial', 24), bg='white', fg='#2E86AB')
        self.loading_icon.pack(pady=5)

        self.loading_text = tk.Label(loading_content, text="正在加载数据...", font=('Microsoft YaHei', 12), bg='white', fg='#333333')
        self.loading_text.pack(pady=5)

        # 配置Treeview样式
        style = ttk.Style()
        # 设置字体大小
        style.configure("Custom.Treeview", font=('Microsoft YaHei', 8))  # 10是字体大小，可以调整
        # 设置行高
        style.configure("Custom.Treeview", rowheight=30)  # 30是行高，可以调整
        # 设置表头字体
        style.configure("Custom.Treeview.Heading", font=('Microsoft YaHei', 11, 'bold'))

        # 创建Treeview时使用自定义样式
        self.tree = ttk.Treeview(self.tree_container, show="headings", style="Custom.Treeview")

        # self.tree = ttk.Treeview(self.tree_container, show="headings")
        self.vsb = ttk.Scrollbar(self.tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.hsb = ttk.Scrollbar(self.tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=self.hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.tree_container.grid_rowconfigure(0, weight=1)
        self.tree_container.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.show_detail)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.context_menu = tk.Menu(self.master, tearoff=0)
        self.context_menu.add_command(label="大笔买入", command=self.show_big_buy_orders)
        self.context_menu.add_command(label="基本面分析", command=self.show_fundamental)
        self.context_menu.add_command(label="资金流", command=self.show_fund_flow)
        self.context_menu.add_command(label="K线图", command=self.show_k_line)
        self.context_menu.add_command(label="AI诊股", command=self.show_ai_diagnose)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制股票代码", command=self.copy_stock_code)
        self.context_menu.add_command(label="复制股票名称", command=self.copy_stock_name)

        self.animation_angle = 0
        self.loading_animation_id = None

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
            self.loading_animation_id = self.master.after(100, animate)

        animate()

    def stop_loading_animation(self):
        """停止loading动画"""
        if self.loading_animation_id:
            self.master.after_cancel(self.loading_animation_id)
            self.loading_animation_id = None

    def on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            columns = self.tree["columns"]
            values = self.tree.item(item, "values")
            code_idx = columns.index("代码")
            name_idx = columns.index("名称")
            self.selected_stock = {"code": values[code_idx], "name": values[name_idx]}
            self.context_menu.post(event.x_root, event.y_root)

    def show_fundamental(self):
        if self.selected_stock["code"]:
            messagebox.showinfo("基本面分析",
                                f"正在获取 {self.selected_stock['name']}({self.selected_stock['code']}) 的基本面数据...\n\n功能实现中，这里可以展示:\n- 财务指标(PE, PB, ROE等)\n- 公司简介\n- 行业对比\n- 机构评级\n")

    def show_big_buy_orders(self):
        """显示选中股票的大笔买入明细"""
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        stock_code = self.selected_stock["code"]
        stock_name = self.selected_stock["name"]
        current_date = datetime.now().strftime('%Y%m%d')

        # 创建新窗口
        detail_window = tk.Toplevel(self.master)
        detail_window.title(f"大笔买入明细 - {stock_name}({stock_code})")
        self.center_window(detail_window, 900, 600)
        detail_window.resizable(True, True)

        # 创建主框架
        main_frame = ttk.Frame(detail_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题标签
        title_label = ttk.Label(main_frame, text=f"{stock_name}({stock_code}) - 大笔买入明细",
                                font=('Microsoft YaHei', 14, 'bold'))
        title_label.pack(pady=(0, 10))

        # 创建表格框架
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        # 创建Treeview表格
        columns = ("时间", "代码", "名称", "板块", "成交量", "成交价", "占成交量比", "成交金额")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=20)

        # 设置列标题和宽度
        column_widths = {
            "时间": 150,
            "代码": 80,
            "名称": 100,
            "板块": 100,
            "成交量": 100,
            "成交价": 80,
            "占成交量比": 100,
            "成交金额": 120
        }

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=column_widths.get(col, 100), anchor="center")

        # 创建滚动条
        v_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 布局
        tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # 状态标签
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        status_label = ttk.Label(status_frame, text="正在加载数据...")
        status_label.pack(side=tk.LEFT)

        # 统计标签
        stats_label = ttk.Label(status_frame, text="", font=('Microsoft YaHei', 9))
        stats_label.pack(side=tk.RIGHT)

        # 异步加载数据
        def load_big_buy_data():
            try:
                conn = sqlite3.connect('stock_data.db')

                # 查询大笔买入数据
                query = f"""
                SELECT 时间,
                       代码,
                       名称,
                       板块,
                       成交量,
                       成交价,
                       占成交量比,
                       成交金额
                FROM stock_changes_{current_date}
                WHERE 代码 = ?
                ORDER BY 时间 ASC
                """

                cursor = conn.execute(query, (stock_code,))
                rows = cursor.fetchall()
                conn.close()

                # 在主线程中更新UI
                def update_ui():
                    if not rows:
                        status_label.config(text="未找到该股票的大笔买入数据")
                        return

                    # 插入数据到表格
                    total_amount = 0
                    total_volume = 0

                    for row in rows:
                        # 格式化数据
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
                            # 成交量
                            if formatted_row[4]:
                                volume = float(formatted_row[4])
                                formatted_row[4] = f"{volume:,.0f}"
                                total_volume += volume

                            # 成交价
                            if formatted_row[5]:
                                price = float(formatted_row[5])
                                formatted_row[5] = f"{price:.2f}"

                            # 占成交量比
                            if formatted_row[6]:
                                ratio = float(formatted_row[6])
                                formatted_row[6] = f"{ratio:.2f}%"

                            # 成交金额
                            if formatted_row[7]:
                                amount = float(formatted_row[7])
                                formatted_row[7] = f"{amount:,.0f}"
                                total_amount += amount
                        except:
                            pass

                        tree.insert("", "end", values=formatted_row)

                    # 更新状态和统计信息
                    status_label.config(text=f"共找到 {len(rows)} 条大笔买入记录")
                    stats_text = f"总成交量: {total_volume:,.0f}手  总成交金额: {total_amount / 10000:.1f}万元"
                    stats_label.config(text=stats_text)

                    logging.info(f"加载 {stock_name}({stock_code}) 大笔买入数据完成，共{len(rows)}条记录")

                # 在主线程中执行UI更新
                detail_window.after(0, update_ui)

            except Exception as e:
                logging.error(f"加载大笔买入数据失败: {e}")

                def show_error():
                    status_label.config(text=f"数据加载失败: {str(e)}")

                detail_window.after(0, show_error)

        # 在后台线程中加载数据
        threading.Thread(target=load_big_buy_data, daemon=True).start()

        # 添加导出功能按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

    def show_fund_flow(self):
        """显示个股资金流（最近10天）"""
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if ak is None:
            try:
                lazy_import_heavy_modules()
            except Exception as e:
                messagebox.showerror("错误", f"加载数据模块失败: {str(e)}")
                return

        stock_code = self.selected_stock["code"]
        stock_name = self.selected_stock["name"]

        # 创建资金流窗口
        fund_flow_window = tk.Toplevel(self.master)
        fund_flow_window.title(f"个股资金流（最近10天） - {stock_name}({stock_code})")
        fund_flow_window.geometry("1200x750")

        # 居中显示
        self.center_window(fund_flow_window, 1200, 750)

        # 创建主框架
        main_frame = ttk.Frame(fund_flow_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 标题
        title_label = ttk.Label(main_frame, text=f"{stock_name}({stock_code}) - 资金流向分析（最近10天）",
                                font=('Microsoft YaHei', 14, 'bold'))
        title_label.pack(pady=(0, 10))

        # 状态标签
        status_label = ttk.Label(main_frame, text="正在获取资金流数据...")
        status_label.pack(pady=5)

        # 创建表格框架
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        # 创建Treeview表格
        columns = ["日期", "收盘价", "涨跌幅(%)", "主力净流入-净额", "主力净流入-净占比(%)",
                   "超大单净流入-净额", "超大单净流入-净占比(%)", "大单净流入-净额"]

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)

        # 设置列标题和宽度
        col_widths = {
            "日期": 100, "收盘价": 80, "涨跌幅(%)": 80,
            "主力净流入-净额": 120, "主力净流入-净占比(%)": 130,
            "超大单净流入-净额": 130, "超大单净流入-净占比(%)": 140,
            "大单净流入-净额": 120, "大单净流入-净占比(%)": 130
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

        # 异步获取数据
        def fetch_fund_flow_data():
            try:
                # 确定交易所代码
                exchange, _ = get_stock_info(stock_code)
                market_mapping = {
                    'sh': 'sh',
                    'sz': 'sz',
                    'bj': 'bj'
                }
                market = market_mapping.get(exchange, 'sh')

                status_label.config(text=f"正在获取{stock_name}({stock_code})的资金流数据...")
                fund_flow_window.update()

                # 调用akshare获取资金流数据
                fund_flow_df = ak.stock_individual_fund_flow(stock=stock_code, market=market)

                if fund_flow_df.empty:
                    status_label.config(text="未获取到资金流数据")
                    return

                # 确保日期列是datetime格式，然后按日期降序排序获取最近的10天数据
                if '日期' in fund_flow_df.columns:
                    # 转换日期格式
                    fund_flow_df['日期'] = pd.to_datetime(fund_flow_df['日期'])
                    # 按日期降序排序，最新的在前面
                    fund_flow_df = fund_flow_df.sort_values('日期', ascending=False)
                    # 取最近的10天数据
                    fund_flow_df = fund_flow_df.head(20)
                else:
                    # 如果没有日期列，则直接取最后10行（通常最新的数据在后面）
                    fund_flow_df = fund_flow_df.tail(20).iloc[::-1]  # tail(10)取后10行，然后reverse顺序

                # 数据处理和显示
                status_label.config(text=f"获取到最近 {len(fund_flow_df)} 天的资金流数据")

                # 清空现有数据
                for item in tree.get_children():
                    tree.delete(item)

                # 插入数据（现在数据已经按最新到最旧排序）
                for index, row in fund_flow_df.iterrows():
                    # 格式化数据
                    values = [
                        str(row['日期'].date()) if pd.notna(row['日期']) and hasattr(row['日期'], 'date') else str(row['日期']) if pd.notna(row['日期']) else "",
                        f"{row['收盘价']:.2f}" if pd.notna(row['收盘价']) else "0.00",
                        f"{row['涨跌幅']:.2f}" if pd.notna(row['涨跌幅']) else "0.00",
                        f"{row['主力净流入-净额'] / 10000:.0f}" if pd.notna(row['主力净流入-净额']) else "0",
                        f"{row['主力净流入-净占比']:.2f}" if pd.notna(row['主力净流入-净占比']) else "0.00",
                        f"{row['超大单净流入-净额'] / 10000:.0f}" if pd.notna(row['超大单净流入-净额']) else "0",
                        f"{row['超大单净流入-净占比']:.2f}" if pd.notna(row['超大单净流入-净占比']) else "0.00",
                        f"{row['大单净流入-净额'] / 10000:.0f}" if pd.notna(row['大单净流入-净额']) else "0",
                        f"{row['大单净流入-净占比']:.2f}" if pd.notna(row['大单净流入-净占比']) else "0.00",
                        f"{row['中单净流入-净额'] / 10000:.0f}" if pd.notna(row['中单净流入-净额']) else "0",
                        f"{row['中单净流入-净占比']:.2f}" if pd.notna(row['中单净流入-净占比']) else "0.00",
                        f"{row['小单净流入-净额'] / 10000:.0f}" if pd.notna(row['小单净流入-净额']) else "0",
                        f"{row['小单净流入-净占比']:.2f}" if pd.notna(row['小单净流入-净占比']) else "0.00"
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

                    # 根据主力净流入设置背景色
                    try:
                        main_flow = float(row['主力净流入-净额'])
                        if main_flow > 0:
                            tree.tag_configure(f"inflow_{item}", background='#FFE4E1')  # 浅红色背景
                            current_tags = tree.item(item, "tags")
                            tree.item(item, tags=current_tags + (f"inflow_{item}",))
                        elif main_flow < 0:
                            tree.tag_configure(f"outflow_{item}", background='#E0FFE0')  # 浅绿色背景
                            current_tags = tree.item(item, "tags")
                            tree.item(item, tags=current_tags + (f"outflow_{item}",))
                    except (ValueError, TypeError):
                        pass

                # 添加统计信息
                stats_frame = ttk.LabelFrame(main_frame, text="统计信息（最近10天）", padding=10)
                stats_frame.pack(fill=tk.X, pady=(10, 0))

                # 计算统计数据
                #total_main_flow = fund_flow_df['主力净流入-净额'].sum()
                #avg_main_flow = fund_flow_df['主力净流入-净额'].mean()

                # 计算最近3天和5天的数据（现在数据已经按最新到最旧排序）
                recent_3_flow = fund_flow_df.head(3)['主力净流入-净额'].sum() if len(fund_flow_df) >= 3 else fund_flow_df['主力净流入-净额'].sum()
                recent_5_flow = fund_flow_df.head(5)['主力净流入-净额'].sum() if len(fund_flow_df) >= 5 else fund_flow_df['主力净流入-净额'].sum()
                recent_10_flow = fund_flow_df.head(10)['主力净流入-净额'].sum() if len(fund_flow_df) >= 10 else fund_flow_df['主力净流入-净额'].sum()
                avg_main_flow = fund_flow_df.head(10)['主力净流入-净额'].mean()
                # 计算流入流出天数
                inflow_days = len(fund_flow_df[fund_flow_df['主力净流入-净额'] > 0])
                outflow_days = len(fund_flow_df[fund_flow_df['主力净流入-净额'] < 0])

                # 获取最新和最旧的日期用于显示
                if '日期' in fund_flow_df.columns and len(fund_flow_df) > 0:
                    latest_date = fund_flow_df['日期'].max().strftime('%Y-%m-%d') if hasattr(fund_flow_df['日期'].max(), 'strftime') else str(fund_flow_df['日期'].max())
                    earliest_date = fund_flow_df['日期'].min().strftime('%Y-%m-%d') if hasattr(fund_flow_df['日期'].min(), 'strftime') else str(fund_flow_df['日期'].min())
                    date_range_text = f"数据范围: {earliest_date} 至 {latest_date}"
                else:
                    date_range_text = f"共 {len(fund_flow_df)} 天数据"

                # 将这几行的显示文本修改：
                stats_text1 = f"10天总主力净流入: {recent_10_flow / 10000:.0f}万元  |  " \
                              f"日均主力净流入: {avg_main_flow / 10000:.0f}万元"

                stats_text2 = f"近3天主力净流入: {recent_3_flow / 10000:.0f}万元  |  " \
                              f"近5天主力净流入: {recent_5_flow / 10000:.0f}万元"

                stats_text3 = f"净流入天数: {inflow_days}天  |  " \
                              f"净流出天数: {outflow_days}天  |  " \
                              f"{date_range_text}"

                ttk.Label(stats_frame, text=stats_text1, font=('Microsoft YaHei', 10)).pack(pady=2)
                ttk.Label(stats_frame, text=stats_text2, font=('Microsoft YaHei', 10)).pack(pady=2)
                ttk.Label(stats_frame, text=stats_text3, font=('Microsoft YaHei', 10)).pack(pady=2)

                # 添加说明
                info_frame = ttk.Frame(main_frame)
                info_frame.pack(fill=tk.X, pady=(5, 0))

                info_text = "说明: 数据按时间倒序排列（最新在前）；红色表示上涨，绿色表示下跌；浅红色背景表示主力净流入，浅绿色背景表示主力净流出"
                ttk.Label(info_frame, text=info_text, font=('Microsoft YaHei', 9), foreground='gray').pack()

                logging.info(f"成功获取{stock_name}({stock_code})的资金流数据: 最近{len(fund_flow_df)}天的记录")

            except Exception as e:
                logging.error(f"获取资金流数据失败: {e}")
                status_label.config(text=f"获取资金流数据失败: {str(e)}")
                messagebox.showerror("错误", f"获取资金流数据失败: {str(e)}")

        # 在后台线程中获取数据
        threading.Thread(target=fetch_fund_flow_data, daemon=True).start()

    def show_k_line(self):
        """显示K线图"""
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return

        if ak is None:
            try:
                lazy_import_heavy_modules()
            except Exception as e:
                messagebox.showerror("错误", f"加载图表模块失败: {str(e)}")
                return

        stock_code = self.selected_stock["code"]
        stock_name = self.selected_stock["name"]

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

    def copy_stock_code(self):
        if self.selected_stock["code"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.selected_stock["code"])
            self.status_label.config(text=f"已复制股票代码: {self.selected_stock['code']}")

    def copy_stock_name(self):
        if self.selected_stock["name"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.selected_stock["name"])
            self.status_label.config(text=f"已复制股票名称: {self.selected_stock['name']}")

    def load_data(self):
        try:
            min_amount = int(self.amount_var.get())
        except ValueError:
            min_amount = 2000
            self.amount_var.set("2000")
        try:
            min_market_cap = int(self.market_cap_var.get())
        except ValueError:
            min_market_cap = 10
            self.market_cap_var.set("10")
        sort_by = self.sort_var.get()
        current_date = datetime.now().strftime('%Y%m%d')

        try:
            conn = sqlite3.connect('stock_data.db')
            query = f"""
            SELECT 
                a.代码, a.名称, b.交易所, b.行业, b.总市值, b.市场板块,
                b.今开, b.最新, b.涨幅, b.最低, b.最高, b.涨停,
                b.换手, b.量比,
                COUNT(1) AS 总成笔数,
                CAST(SUM(a.成交金额) / 10000 AS INTEGER) AS 总成交金额,
                GROUP_CONCAT(CAST(a.成交金额 / 10000 AS INTEGER) || '万(' || a.时间 || ')', '|') AS 时间金额明细
            FROM 
                stock_changes_{current_date} a,
                stock_real_data_{current_date} b
            WHERE 
                a.代码 = b.代码 AND b.总市值 <= {min_market_cap}
            GROUP BY 
                a.代码, a.名称
            HAVING 
                总成交金额 > {min_amount}
            ORDER BY 
                {sort_by} DESC
            """

            if pd is None:
                lazy_import_heavy_modules()

            full_df = pd.read_sql_query(query, conn)
            conn.close()

            if not full_df.empty:
                save_to_excel(full_df)
                available_columns = [col for col in self.display_columns if col in full_df.columns]
                self.df = full_df[available_columns]
                self.update_table()
            else:
                self.status_label.config(text="没有找到符合条件的数据，请先刷新数据或调整筛选条件")

        except Exception as e:
            logging.error(f"加载数据失败: {e}")
            self.status_label.config(text="加载数据失败，请先刷新数据")

    def update_table(self):
        self.show_loading()
        self.master.after(10, self._update_table_content)

    def _update_table_content(self):
        """实际的表格更新内容"""
        try:
            for i in self.tree.get_children():
                self.tree.delete(i)

            columns = list(self.df.columns)
            self.tree["columns"] = columns

            col_widths = {
                "代码": 120, "名称": 120, "交易所": 60, "市场板块": 80, "总市值": 80,
                "今开": 70, "涨幅": 70, "最低": 70, "最高": 70, "涨停": 70, "换手": 80, "量比": 80,
                "总成笔数": 80, "总成交金额": 100, "时间金额明细": 200
            }

            for col in columns:
                self.tree.heading(col, text=col)
                self.tree.column(col, width=col_widths.get(col, 100), anchor="center")

            self._insert_data_batch(0, columns)

        except Exception as e:
            logging.error(f"更新表格内容失败: {e}")
            self.hide_loading()

    def _insert_data_batch(self, start_index, columns, batch_size=100):
        """分批插入数据，每批插入batch_size行"""
        try:
            end_index = min(start_index + batch_size, len(self.df))

            if "涨幅" in columns:
                change_idx = columns.index("涨幅")
                for i in range(start_index, end_index):
                    row = self.df.iloc[i]
                    item = self.tree.insert("", "end", values=list(row))
                    try:
                        change = float(row["涨幅"])
                        if change > 0:
                            self.tree.tag_configure(f"up_{item}", foreground='red', font=self.bold_font)
                            self.tree.item(item, tags=(f"up_{item}",))
                        elif change < 0:
                            self.tree.tag_configure(f"down_{item}", foreground='green', font=self.bold_font)
                            self.tree.item(item, tags=(f"down_{item}",))
                        else:
                            self.tree.tag_configure(f"zero_{item}", foreground='gray', font=self.normal_font)
                            self.tree.item(item, tags=(f"zero_{item}",))
                    except ValueError:
                        pass
            else:
                for i in range(start_index, end_index):
                    row = self.df.iloc[i]
                    self.tree.insert("", "end", values=list(row))

            self.tree.update_idletasks()

            if end_index < len(self.df):
                self.master.after(20, lambda: self._insert_data_batch(end_index, columns, batch_size))
            else:
                self._finish_table_update()

        except Exception as e:
            logging.error(f"批量插入数据失败: {e}")
            self.hide_loading()

    def _finish_table_update(self):
        """完成表格更新的最后步骤"""
        try:
            self.tree.update_idletasks()
            self.vsb.lift()
            self.hsb.lift()
        finally:
            self.hide_loading()

    def show_detail(self, event):
        item = self.tree.selection()[0]
        values = self.tree.item(item, "values")
        columns = self.tree["columns"]
        detail_window = tk.Toplevel(self.master)
        detail_window.title(f"{values[columns.index('名称')]} ({values[columns.index('代码')]}) 详细信息")
        self.center_window(detail_window, 600, 400)
        text = tk.Text(detail_window, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        info_lines = [f"{col}: {value}" for col, value in zip(columns, values)]
        info = "\n".join(info_lines)
        text.insert(tk.END, info)
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

    def __del__(self):
        """清理资源"""
        if hasattr(self, 'kline_executor'):
            self.kline_executor.shutdown(wait=False)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        root.iconbitmap(default="logo.ico")
    except:
        pass  # 如果图标文件不存在，忽略错误

    app = StockVisualizationApp(root)


    # 定期清理已关闭的K线图窗口
    def periodic_cleanup():
        app.cleanup_closed_windows()
        root.after(30000, periodic_cleanup)  # 每30秒清理一次


    root.after(30000, periodic_cleanup)
    root.mainloop()
