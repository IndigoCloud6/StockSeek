import json
import logging
import os
import sqlite3
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from tkinter import messagebox
from tkinter import ttk
from tkinter.font import Font

import akshare as ak
import pandas as pd

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置文件路径
CONFIG_FILE = "announcement_config.json"

# 默认公告内容
DEFAULT_ANNOUNCEMENTS = [
    "系统公告：欢迎使用股票交易数据可视化系统！",
    "重要提示：系统数据每10分钟自动更新一次，请及时刷新查看最新数据。",
    "操作提示：右键点击股票行可查看基本面分析和K线图。",
    "温馨提示：双击股票行可查看详细交易信息。",
    "系统公告：所有数据来源于公开市场信息，仅供参考，不构成投资建议。"
]

# 创建配置文件（如果不存在）
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({"announcements": DEFAULT_ANNOUNCEMENTS}, f, ensure_ascii=False, indent=4)


# Function to save results to Excel
def save_to_excel(results: list, filename: str = "stock_data.xlsx"):
    # Convert results to DataFrame
    df = pd.DataFrame(results)
    # Save to Excel with raw numeric values
    df.to_excel(filename, index=False, engine='openpyxl')
    print(f"Data saved to {filename}")


def get_stock_info(stock_code):
    """
    根据股票代码判断交易所和详细市场板块
    返回格式: (exchange, market)
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


class StockVisualizationApp:
    def __init__(self, master):
        self.master = master
        master.title("股票交易数据可视化系统")
        master.geometry("1200x650")  # 增加高度以适应公告栏

        # 加载公告
        self.announcements = self.load_announcements()
        self.current_announcement_idx = 0

        # 可配置显示的字段列表
        self.display_columns = ["代码", "名称", "交易所", "行业", "最新", "涨幅", "今开", "最高", "最低", "总成交金额"]

        # 创建自定义字体
        self.bold_font = Font(weight="bold")
        self.normal_font = Font(weight="normal")
        self.announcement_font = Font(family="Microsoft YaHei", size=10, weight="bold")

        # 创建主框架
        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 创建公告栏
        self.create_announcement_bar()

        # 创建状态标签
        self.status_label = ttk.Label(self.main_frame, text="")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        # 顶部控制面板
        self.create_control_panel()

        # 数据表格区域
        self.create_data_table()

        # 启动数据获取线程
        threading.Thread(target=self.fetch_data, daemon=True).start()

        # 当前选中的股票信息
        self.selected_stock = {"code": "", "name": ""}

        # 启动公告更新定时器
        self.update_announcement()

        # 启动实时时钟
        self.update_clock()

    def load_announcements(self):
        """从配置文件加载公告列表"""
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                announcements = config.get("announcements", DEFAULT_ANNOUNCEMENTS)
                # 确保至少有默认公告
                if not announcements:
                    return DEFAULT_ANNOUNCEMENTS
                return announcements
        except Exception as e:
            logging.error(f"加载公告配置文件失败: {e}")
            return DEFAULT_ANNOUNCEMENTS

    def create_announcement_bar(self):
        """创建公告栏"""
        announcement_frame = ttk.Frame(self.main_frame, height=30)
        announcement_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        # 公告图标
        self.announcement_icon = tk.Label(
            announcement_frame,
            text="📢",
            font=self.announcement_font,
            bg="#FFE4B5",
            padx=5
        )
        self.announcement_icon.pack(side=tk.LEFT, fill=tk.Y)

        # 公告内容标签
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

        # 添加实时时钟（在配置按钮左侧）
        self.clock_label = tk.Label(
            announcement_frame,
            text="",
            font=("Microsoft YaHei", 10, "bold"),
            bg="#FFE4B5",
            fg="#FF0000",  # 红色字体
            padx=10
        )
        self.clock_label.pack(side=tk.RIGHT, padx=5)

        # 配置按钮
        ttk.Button(
            announcement_frame,
            text="配置公告",
            width=10,
            command=self.configure_announcements
        ).pack(side=tk.RIGHT, padx=5)

        # 设置背景色
        announcement_frame.configure(style="Announcement.TFrame")
        style = ttk.Style()
        style.configure("Announcement.TFrame", background="#FFE4B5")

    def update_clock(self):
        """更新实时时钟"""
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")  # 格式化为年-月-日 时:分:秒
        self.clock_label.config(text=time_str)
        # 每秒更新一次
        self.master.after(1000, self.update_clock)

    def update_announcement(self):
        """更新公告内容"""
        if self.announcements:
            announcement = self.announcements[self.current_announcement_idx]
            self.announcement_label.config(text=announcement)

            # 更新索引，循环显示
            self.current_announcement_idx = (self.current_announcement_idx + 1) % len(self.announcements)

            # 每8秒更新一次公告
            self.master.after(8000, self.update_announcement)

    def configure_announcements(self):
        """配置公告内容"""
        config_window = tk.Toplevel(self.master)
        config_window.title("公告配置")
        config_window.geometry("600x400")
        config_window.resizable(True, True)

        # 创建文本编辑区域
        text_frame = ttk.Frame(config_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 添加滚动条
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 创建文本编辑框
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

        # 添加说明
        help_text = "提示：每条公告单独一行，系统将按顺序轮播显示"
        ttk.Label(config_window, text=help_text, foreground="gray").pack(anchor=tk.W, padx=10)

        # 添加按钮
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(
            button_frame,
            text="保存",
            command=lambda: self.save_announcements(config_window)
        ).pack(side=tk.RIGHT, padx=5)

        ttk.Button(
            button_frame,
            text="重置",
            command=self.reset_announcements
        ).pack(side=tk.RIGHT, padx=5)

        ttk.Button(
            button_frame,
            text="取消",
            command=config_window.destroy
        ).pack(side=tk.RIGHT, padx=5)

        # 加载现有公告到文本框
        self.load_announcements_to_text()

    def load_announcements_to_text(self):
        """将公告加载到文本编辑框"""
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
        """保存公告配置"""
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
        """重置为默认公告"""
        self.announcement_text.delete(1.0, tk.END)
        self.announcement_text.insert(tk.END, "\n".join(DEFAULT_ANNOUNCEMENTS))

    def fetch_data(self):
        """获取并处理股票数据"""
        try:
            # 显示正在获取数据的提示
            self.status_label.config(text="正在获取数据...")
            self.master.update()

            # 获取大笔买入数据
            stock_changes_em_df = ak.stock_changes_em(symbol="大笔买入")

            # 拆分 '相关信息' 列
            split_info = stock_changes_em_df['相关信息'].str.split(',', expand=True)
            split_info.columns = ['成交量', '成交价', '占成交量比', '成交金额']
            split_info['成交量'] = pd.to_numeric(split_info['成交量'], errors='coerce')
            split_info['成交价'] = pd.to_numeric(split_info['成交价'], errors='coerce')
            split_info['占成交量比'] = pd.to_numeric(split_info['占成交量比'], errors='coerce')
            split_info['成交金额'] = pd.to_numeric(split_info['成交金额'], errors='coerce')
            stock_changes_em_df = pd.concat([stock_changes_em_df.drop(columns=['相关信息']), split_info], axis=1)

            # 处理时间列
            current_date = datetime.now().strftime('%Y%m%d')
            current_date_obj = datetime.now().date()
            stock_changes_em_df['时间'] = pd.to_datetime(
                current_date_obj.strftime('%Y-%m-%d') + ' ' + stock_changes_em_df['时间'].apply(lambda x: x.strftime('%H:%M:%S')),
                format='%Y-%m-%d %H:%M:%S'
            )

            # 连接数据库
            conn = sqlite3.connect('stock_data.db')
            table_name = f'stock_changes_{current_date}'

            try:
                conn.execute(f"DELETE FROM {table_name}")
                print("删除成功")
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):  # SQLite 错误信息
                    print(f"警告：表 {table_name} 不存在")
                else:
                    raise  # 重新抛出其他异常
            except Exception as e:
                print(f"未知错误: {e}")

            stock_changes_em_df.to_sql(table_name, conn, if_exists='append', index=False)
            logging.info(f"数据已成功存入 SQLite 数据库表 {table_name}！")

            # 获取实时数据
            real_data_list = []
            stock_info = stock_changes_em_df[['代码', '名称']].drop_duplicates(subset=['代码'])

            def not_bj_kcb(row):
                exchange, market = get_stock_info(row['代码'])
                return not (exchange == 'bj' or market == '科创板' or market == '创业板')

            filtered_stock_info = stock_info[stock_info.apply(not_bj_kcb, axis=1)]
            max_workers = min(10, len(filtered_stock_info))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_stock = {
                    executor.submit(self.process_stock, row['代码'], row['名称']): row['代码']
                    for _, row in filtered_stock_info.iterrows()
                }
                for future in as_completed(future_to_stock):
                    result = future.result()
                    if result:
                        real_data_list.append(result)

            stock_real_data_df = pd.DataFrame(real_data_list)
            real_table_name = f'stock_real_data_{current_date}'

            try:
                conn.execute(f"DELETE FROM {real_table_name}")
                print("删除成功")
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):  # SQLite 错误信息
                    print(f"警告：表 {real_table_name} 不存在")
                else:
                    raise  # 重新抛出其他异常
            except Exception as e:
                print(f"未知错误: {e}")


            stock_real_data_df.to_sql(real_table_name, conn, if_exists='replace', index=False)
            logging.info(f"实时数据已成功存入 SQLite 数据库表 {real_table_name}！")
            conn.close()

            # 更新UI
            self.status_label.config(text="数据获取完成")
            self.load_data()
        except Exception as e:
            logging.error(f"数据获取失败: {e}")
            self.status_label.config(text="数据获取失败")

    def process_stock(self, stock_code, stock_name):
        """处理单只股票的实时数据"""
        try:
            stock_info_df = ak.stock_individual_info_em(symbol=stock_code)
            industry = stock_info_df[stock_info_df['item'] == '行业']['value'].iloc[0] if '行业' in stock_info_df['item'].values else '未知'
            stock_bid_ask_df = ak.stock_bid_ask_em(symbol=stock_code)
            latest_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '最新']['value'].iloc[0]) if '最新' in stock_bid_ask_df['item'].values else None
            price_change_percent = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '涨幅']['value'].iloc[0]) if '涨幅' in stock_bid_ask_df['item'].values else None
            opening_price = float(stock_bid_ask_df[stock_bid_ask_df['item'] == '今开']['value'].iloc[0]) if '今开' in stock_bid_ask_df['item'].values else None
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
                '最新': latest_price,
                '涨幅': price_change_percent,
                '最高': max_price,
                '最低': min_price,
                '涨停': zhang_ting,
                '今开': opening_price
            }
        except Exception as e:
            logging.error(f"处理股票代码 {stock_code} ({stock_name}) 时出错: {e}")
            return None

    def create_control_panel(self):
        """创建顶部控制面板"""
        control_frame = ttk.LabelFrame(self.main_frame, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # 刷新数据按钮 - 直接调用fetch_data
        ttk.Button(control_frame, text="刷新数据", command=self.fetch_data).pack(side=tk.LEFT, padx=5)

        # 最小成交金额设置 - 改为计数器形式
        amount_frame = ttk.Frame(control_frame)
        amount_frame.pack(side=tk.LEFT, padx=5)

        ttk.Label(amount_frame, text="最小成交金额(万):").pack(side=tk.LEFT, padx=5)

        # 减少按钮
        ttk.Button(
            amount_frame,
            text="-",
            width=3,
            command=lambda: self.adjust_amount(-200)
        ).pack(side=tk.LEFT, padx=2)

        # 金额显示
        self.amount_var = tk.StringVar(value="2000")
        self.amount_label = ttk.Label(
            amount_frame,
            textvariable=self.amount_var,
            width=6,
            anchor="center",
            background="white",
            relief="sunken",
            padding=3
        )
        self.amount_label.pack(side=tk.LEFT, padx=2)

        # 增加按钮
        ttk.Button(
            amount_frame,
            text="+",
            width=3,
            command=lambda: self.adjust_amount(200)
        ).pack(side=tk.LEFT, padx=2)

        # 排序方式设置
        ttk.Label(control_frame, text="排序方式:").pack(side=tk.LEFT, padx=5)
        self.sort_var = tk.StringVar(value="总成交金额")
        sort_options = ["总成交金额", "涨幅", "总成笔数"]
        sort_combo = ttk.Combobox(control_frame, textvariable=self.sort_var, values=sort_options, width=10, state="readonly")
        sort_combo.pack(side=tk.LEFT, padx=5)
        # 绑定选择事件
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self.load_data())

        # 选择显示字段按钮
        ttk.Button(control_frame, text="选择显示字段", command=self.select_columns).pack(side=tk.RIGHT, padx=5)

    def adjust_amount(self, delta):
        """调整最小成交金额"""
        try:
            current = int(self.amount_var.get())
            new_value = max(0, current + delta)  # 确保不会出现负值
            self.amount_var.set(str(new_value))
            self.load_data()
        except ValueError:
            self.amount_var.set("2000")
            self.load_data()

    def select_columns(self):
        """选择要显示的字段"""
        select_window = tk.Toplevel(self.master)
        select_window.title("选择显示字段")
        select_window.geometry("300x400")

        all_columns = [
            "代码", "名称", "交易所", "市场板块",
            "今开", "涨幅", "最低", "最高", "涨停",
            "总成笔数", "总成交金额", "时间金额明细"
        ]

        self.column_vars = {}
        for col in all_columns:
            var = tk.BooleanVar(value=col in self.display_columns)
            self.column_vars[col] = var
            cb = ttk.Checkbutton(select_window, text=col, variable=var)
            cb.pack(anchor=tk.W, padx=10, pady=2)

        ttk.Button(
            select_window,
            text="确认",
            command=lambda: self.apply_column_selection(select_window)
        ).pack(side=tk.BOTTOM, pady=10)

    def apply_column_selection(self, window):
        """应用字段选择"""
        self.display_columns = [col for col, var in self.column_vars.items() if var.get()]
        window.destroy()
        self.load_data()

    def create_data_table(self):
        """创建数据表格"""
        self.table_frame = ttk.Frame(self.main_frame)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Label(self.table_frame, text="股票交易明细", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)
        self.tree_container = ttk.Frame(self.table_frame)
        self.tree_container.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(self.tree_container, show="headings")
        self.vsb = ttk.Scrollbar(self.tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.hsb = ttk.Scrollbar(self.tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=self.hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.tree_container.grid_rowconfigure(0, weight=1)
        self.tree_container.grid_columnconfigure(0, weight=1)

        # 绑定事件
        self.tree.bind("<Double-1>", self.show_detail)
        # 添加右键菜单绑定
        self.tree.bind("<Button-3>", self.on_right_click)

        # 创建右键菜单
        self.context_menu = tk.Menu(self.master, tearoff=0)
        self.context_menu.add_command(label="基本面分析", command=self.show_fundamental)
        self.context_menu.add_command(label="K线图", command=self.show_k_line)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制股票代码", command=self.copy_stock_code)

    def on_right_click(self, event):
        """处理右键点击事件"""
        item = self.tree.identify_row(event.y)
        if item:
            # 选中点击的行
            self.tree.selection_set(item)
            # 获取股票信息
            columns = self.tree["columns"]
            values = self.tree.item(item, "values")
            code_idx = columns.index("代码")
            name_idx = columns.index("名称")

            self.selected_stock = {
                "code": values[code_idx],
                "name": values[name_idx]
            }
            # 显示右键菜单
            self.context_menu.post(event.x_root, event.y_root)

    def show_fundamental(self):
        """显示基本面分析"""
        if self.selected_stock["code"]:
            messagebox.showinfo(
                "基本面分析",
                f"正在获取 {self.selected_stock['name']}({self.selected_stock['code']}) 的基本面数据...\n\n"
                "功能实现中，这里可以展示:\n"
                "- 财务指标(PE, PB, ROE等)\n"
                "- 公司简介\n"
                "- 行业对比\n"
                "- 机构评级\n"
            )
            # 实际应用中这里可以调用akshare获取基本面数据
            # self.get_fundamental_data(self.selected_stock["code"])

    def show_k_line(self):
        """显示K线图"""
        if self.selected_stock["code"]:
            messagebox.showinfo(
                "K线图",
                f"正在显示 {self.selected_stock['name']}({self.selected_stock['code']}) 的K线图...\n\n"
                "功能实现中，这里可以展示:\n"
                "- 日K/周K/月K\n"
                "- 技术指标(MACD, KDJ, RSI等)\n"
                "- 成交量\n"
                "- 画线工具\n"
            )
            # 实际应用中这里可以调用akshare获取K线数据并绘制图表
            # self.plot_k_line(self.selected_stock["code"])

    def copy_stock_code(self):
        """复制股票代码到剪贴板"""
        if self.selected_stock["code"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.selected_stock["code"])
            self.status_label.config(text=f"已复制股票代码: {self.selected_stock['code']}")

    def load_data(self):
        """从数据库加载数据"""
        try:
            min_amount = int(self.amount_var.get())
        except ValueError:
            min_amount = 2000
            self.amount_var.set("2000")
        sort_by = self.sort_var.get()
        current_date = datetime.now().strftime('%Y%m%d')

        conn = sqlite3.connect('stock_data.db')
        query = f"""
        SELECT 
            a.代码,
            a.名称,
            b.交易所,
            b.行业,
            b.市场板块,
            b.今开,
            b.最新,
            b.涨幅,
            b.最低,
            b.最高,
            b.涨停,
            COUNT(1) AS 总成笔数,
            CAST(SUM(a.成交金额) / 10000 AS INTEGER) AS 总成交金额,
            GROUP_CONCAT(CAST(a.成交金额 / 10000 AS INTEGER) || '万(' || a.时间 || ')', '|') AS 时间金额明细
        FROM 
            stock_changes_{current_date} a,
            stock_real_data_{current_date} b
        WHERE 
            a.代码 = b.代码
        GROUP BY 
            a.代码,
            a.名称
        HAVING 
            总成交金额 > {min_amount}
        ORDER BY 
            {sort_by} DESC
        """

        full_df = pd.read_sql_query(query, conn)
        conn.close()
        save_to_excel(full_df)
        available_columns = [col for col in self.display_columns if col in full_df.columns]
        self.df = full_df[available_columns]
        self.update_table()

    def update_table(self):
        """更新表格数据"""
        for i in self.tree.get_children():
            self.tree.delete(i)

        columns = list(self.df.columns)
        self.tree["columns"] = columns

        col_widths = {
            "代码": 120, "名称": 120, "交易所": 60, "市场板块": 80,
            "今开": 70, "涨幅": 70, "最低": 70, "最高": 70, "涨停": 70,
            "总成笔数": 80, "总成交金额": 100, "时间金额明细": 200
        }

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths.get(col, 100), anchor="center")

        if "涨幅" in columns:
            change_idx = columns.index("涨幅")
            for _, row in self.df.iterrows():
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
            for _, row in self.df.iterrows():
                self.tree.insert("", "end", values=list(row))

        self.tree.update_idletasks()
        self.vsb.lift()
        self.hsb.lift()

    def show_detail(self, event):
        """显示选中股票的详细信息"""
        item = self.tree.selection()[0]
        values = self.tree.item(item, "values")
        columns = self.tree["columns"]

        detail_window = tk.Toplevel(self.master)
        detail_window.title(f"{values[columns.index('名称')]} ({values[columns.index('代码')]}) 详细信息")
        detail_window.geometry("600x400")

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


if __name__ == "__main__":
    root = tk.Tk()
    root.iconbitmap(default="logo.ico")  # 使用系统内置图标
    app = StockVisualizationApp(root)
    root.mainloop()