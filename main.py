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
from openai import OpenAI

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置文件路径
CONFIG_FILE = "config.json"

# 默认公告内容
DEFAULT_ANNOUNCEMENTS = [
    "系统公告：所有数据来源于公开市场信息，仅供参考，不构成投资建议。"
]

DEFAULT_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 可选：不建议在代码中留密钥

# 创建配置文件（如果不存在）
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({"announcements": DEFAULT_ANNOUNCEMENTS, "api_key": DEFAULT_API_KEY}, f, ensure_ascii=False, indent=4)


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
        raise


api_key = load_api_key()
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


# Function to save results to Excel
def save_to_excel(results: list, filename: str = "stock_data.xlsx"):
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


class StockVisualizationApp:
    def __init__(self, master):
        self.master = master
        master.title("草船借箭")
        self.center_window(master, 1200, 650)

        self.announcements = self.load_announcements()
        self.current_announcement_idx = 0
        self.display_columns = ["代码", "名称", "交易所", "行业", "总市值", "最新", "涨幅", "今开", "最高", "最低", "总成交金额"]

        self.bold_font = Font(weight="bold")
        self.normal_font = Font(weight="normal")
        self.announcement_font = Font(family="Microsoft YaHei", size=10, weight="bold")

        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.create_announcement_bar()
        self.status_label = ttk.Label(self.main_frame, text="")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        self.create_control_panel()
        self.create_data_table()
        threading.Thread(target=self.fetch_data, daemon=True).start()
        self.selected_stock = {"code": "", "name": ""}
        self.update_announcement()
        self.update_clock()

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

        # 外层frame，确保按钮不会被内容挤出窗口
        outer_frame = ttk.Frame(config_window)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        # 编辑区
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

        # 帮助说明
        help_text = "提示：每条公告单独一行，系统将按顺序轮播显示"
        ttk.Label(outer_frame, text=help_text, foreground="gray").pack(anchor=tk.W, padx=10, pady=(6, 0))

        # 按钮区
        button_frame = ttk.Frame(outer_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)

        ttk.Button(
            button_frame,
            text="取消",
            command=config_window.destroy
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            button_frame,
            text="重置",
            command=self.reset_announcements
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            button_frame,
            text="保存",
            command=lambda: self.save_announcements(config_window)
        ).pack(side=tk.RIGHT, padx=5)

        self.load_announcements_to_text()

    def show_ai_diagnose(self):
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
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
                    extra_body={
                        "web_search": True  # 启用联网功能
                    }
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
            self.status_label.config(text="正在获取数据...")
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
            self.status_label.config(text="数据获取完成")
            self.load_data()
        except Exception as e:
            logging.error(f"数据获取失败: {e}")
            self.status_label.config(text="数据获取失败")

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
                '今开': opening_price
            }
        except Exception as e:
            logging.error(f"处理股票代码 {stock_code} ({stock_name}) 时出错: {e}")
            return None

    def create_control_panel(self):
        control_frame = ttk.LabelFrame(self.main_frame, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(control_frame, text="刷新数据", command=self.fetch_data).pack(side=tk.LEFT, padx=5)
        amount_frame = ttk.Frame(control_frame)
        amount_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(amount_frame, text="最小成交金额(万):").pack(side=tk.LEFT, padx=5)
        ttk.Button(
            amount_frame,
            text="-",
            width=3,
            command=lambda: self.adjust_amount(-200)
        ).pack(side=tk.LEFT, padx=2)
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
        ttk.Button(
            amount_frame,
            text="+",
            width=3,
            command=lambda: self.adjust_amount(200)
        ).pack(side=tk.LEFT, padx=2)

        # 总市值过滤
        market_cap_frame = ttk.Frame(control_frame)
        market_cap_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(market_cap_frame, text="最小总市值(亿):").pack(side=tk.LEFT, padx=5)
        ttk.Button(
            market_cap_frame,
            text="-",
            width=3,
            command=lambda: self.adjust_market_cap(-10)
        ).pack(side=tk.LEFT, padx=2)
        self.market_cap_var = tk.StringVar(value="10")
        self.market_cap_label = ttk.Label(
            market_cap_frame,
            textvariable=self.market_cap_var,
            width=6,
            anchor="center",
            background="white",
            relief="sunken",
            padding=3
        )
        self.market_cap_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(
            market_cap_frame,
            text="+",
            width=3,
            command=lambda: self.adjust_market_cap(10)
        ).pack(side=tk.LEFT, padx=2)

        ttk.Label(control_frame, text="排序方式:").pack(side=tk.LEFT, padx=5)
        self.sort_var = tk.StringVar(value="总成交金额")
        sort_options = ["总成交金额", "涨幅", "总成笔数"]
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
            "代码", "名称", "交易所", "市场板块", "总市值",
            "今开", "涨幅", "最新", "最低", "最高", "涨停",
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
        self.display_columns = [col for col, var in self.column_vars.items() if var.get()]
        window.destroy()
        self.load_data()

    def create_data_table(self):
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
        self.tree.bind("<Double-1>", self.show_detail)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.context_menu = tk.Menu(self.master, tearoff=0)
        self.context_menu.add_command(label="基本面分析", command=self.show_fundamental)
        self.context_menu.add_command(label="K线图", command=self.show_k_line)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制股票代码", command=self.copy_stock_code)
        self.context_menu.add_command(label="复制股票名称", command=self.copy_stock_name)
        self.context_menu.add_command(label="AI诊股", command=self.show_ai_diagnose)

    def on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            columns = self.tree["columns"]
            values = self.tree.item(item, "values")
            code_idx = columns.index("代码")
            name_idx = columns.index("名称")
            self.selected_stock = {
                "code": values[code_idx],
                "name": values[name_idx]
            }
            self.context_menu.post(event.x_root, event.y_root)

    def show_fundamental(self):
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

    def show_k_line(self):
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
        conn = sqlite3.connect('stock_data.db')
        query = f"""
        SELECT 
            a.代码,
            a.名称,
            b.交易所,
            b.行业,
            b.总市值,
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
            AND b.总市值 >= {min_market_cap}
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
        for i in self.tree.get_children():
            self.tree.delete(i)
        columns = list(self.df.columns)
        self.tree["columns"] = columns
        col_widths = {
            "代码": 120, "名称": 120, "交易所": 60, "市场板块": 80, "总市值": 80,
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


if __name__ == "__main__":
    root = tk.Tk()
    root.iconbitmap(default="logo.ico")
    app = StockVisualizationApp(root)
    root.mainloop()
