"""
UI Components module for StockSeek application.
Contains reusable UI components and interface management functionality.
"""

import logging
import threading

# Lazy imports for GUI components
tk = None
ttk = None
messagebox = None
Font = None

def lazy_import_gui():
    """Lazy import GUI modules"""
    global tk, ttk, messagebox, Font
    if tk is None:
        try:
            import tkinter as tk_module
            from tkinter import ttk as ttk_module, messagebox as mb_module
            from tkinter.font import Font as font_module
            tk = tk_module
            ttk = ttk_module
            messagebox = mb_module
            Font = font_module
        except ImportError as e:
            logging.error(f"GUI modules not available: {e}")
            raise

from config_manager import load_announcements, save_announcements, reset_announcements
from utils import center_window


class UIComponents:
    """Main UI components manager"""
    
    def __init__(self, master):
        # Ensure GUI modules are loaded
        lazy_import_gui()
        
        self.master = master
        self.main_frame = None
        self.status_label = None
        
        # Announcement related
        self.announcements = []
        self.current_announcement_idx = 0
        self.announcement_font = Font(family="Microsoft YaHei", size=10, weight="bold")
        
        # Control panel variables
        self.amount_var = tk.StringVar(value="2000")
        self.market_cap_var = tk.StringVar(value="200")
        self.sort_var = tk.StringVar(value="总成交金额")
        
        # Table and display
        self.display_columns = ["代码", "名称", "交易所", "行业", "总市值", "最新", "涨幅", "今开", "最高", "最低", "换手", "量比", "总成交金额"]
        self.tree = None
        self.tree_container = None
        self.loading_frame = None
        self.loading_animation_id = None
        self.animation_angle = 0
        
        # Fonts
        self.bold_font = Font(weight="bold")
        self.normal_font = Font(weight="normal")

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

    def initialize_main_ui(self):
        """初始化主界面"""
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

        # Load announcements
        self.announcements = load_announcements()

        # Create main UI components
        self.create_announcement_bar()
        self.status_label = ttk.Label(self.main_frame, text="界面加载完成，点击刷新数据获取股票信息")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def create_announcement_bar(self):
        """创建公告栏"""
        announcement_frame = ttk.LabelFrame(self.main_frame, text="系统公告", padding=5)
        announcement_frame.pack(fill=tk.X, padx=5, pady=5)

        # 公告内容区域
        content_frame = ttk.Frame(announcement_frame)
        content_frame.pack(fill=tk.X)

        # 左侧公告图标
        icon_label = tk.Label(content_frame, text="📢", font=('Arial', 16))
        icon_label.pack(side=tk.LEFT, padx=(0, 10))

        # 中间公告文本
        self.announcement_label = tk.Label(content_frame, text="加载中...",
                                          font=self.announcement_font,
                                          wraplength=800, justify=tk.LEFT,
                                          anchor="w")
        self.announcement_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 右侧操作按钮
        button_frame = ttk.Frame(content_frame)
        button_frame.pack(side=tk.RIGHT)

        ttk.Button(button_frame, text="◀", width=3,
                   command=lambda: self.change_announcement(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="▶", width=3,
                   command=lambda: self.change_announcement(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="配置",
                   command=self.configure_announcements).pack(side=tk.LEFT, padx=5)

        # 下方时间显示
        self.time_label = tk.Label(announcement_frame, text="",
                                  font=('Microsoft YaHei', 9),
                                  fg='#666666')
        self.time_label.pack(side=tk.BOTTOM, anchor=tk.E, padx=5)

    def update_clock(self):
        """更新时钟显示"""
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, 'time_label'):
            self.time_label.config(text=current_time)
        # 每秒更新一次
        self.master.after(1000, self.update_clock)

    def change_announcement(self, direction):
        """切换公告"""
        if not self.announcements:
            return
        
        self.current_announcement_idx = (self.current_announcement_idx + direction) % len(self.announcements)
        self.update_announcement_display()

    def update_announcement_display(self):
        """更新公告显示"""
        if self.announcements and hasattr(self, 'announcement_label'):
            current_announcement = self.announcements[self.current_announcement_idx]
            self.announcement_label.config(text=current_announcement)

    def update_announcement(self):
        """定期更新公告"""
        if self.announcements:
            self.change_announcement(1)
        # 每15秒自动切换一次公告
        self.master.after(15000, self.update_announcement)

    def configure_announcements(self):
        """配置公告窗口"""
        config_window = tk.Toplevel(self.master)
        config_window.title("公告配置")
        center_window(config_window, 600, 500)
        config_window.transient(self.master)
        config_window.grab_set()

        # 创建主框架
        main_frame = ttk.Frame(config_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 说明标签
        ttk.Label(main_frame, text="编辑系统公告（每行一条公告）：",
                  font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W, pady=(0, 10))

        # 文本编辑区域
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.announcement_text = tk.Text(text_frame, wrap=tk.WORD, font=('Microsoft YaHei', 10))
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.announcement_text.yview)
        self.announcement_text.configure(yscrollcommand=scrollbar.set)

        self.announcement_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 加载当前公告到文本框
        self.load_announcements_to_text()

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="保存",
                   command=lambda: self.save_announcements_from_ui(config_window)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="取消",
                   command=config_window.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="恢复默认",
                   command=self.reset_announcements_ui).pack(side=tk.RIGHT)

    def load_announcements_to_text(self):
        """加载公告到文本框"""
        if hasattr(self, 'announcement_text'):
            self.announcement_text.delete('1.0', tk.END)
            for announcement in self.announcements:
                self.announcement_text.insert(tk.END, announcement + '\n')

    def save_announcements_from_ui(self, window):
        """从UI保存公告"""
        try:
            # 获取文本内容并按行分割
            text_content = self.announcement_text.get('1.0', tk.END).strip()
            new_announcements = [line.strip() for line in text_content.split('\n') if line.strip()]
            
            if not new_announcements:
                messagebox.showwarning("警告", "至少需要一条公告内容")
                return
            
            # 保存到配置文件
            if save_announcements(new_announcements):
                self.announcements = new_announcements
                self.current_announcement_idx = 0
                self.update_announcement_display()
                messagebox.showinfo("成功", "公告保存成功")
                window.destroy()
            else:
                messagebox.showerror("错误", "保存公告失败")
        except Exception as e:
            messagebox.showerror("错误", f"保存公告时出错: {str(e)}")

    def reset_announcements_ui(self):
        """重置公告到默认值"""
        if messagebox.askyesno("确认", "确定要恢复到默认公告吗？"):
            if reset_announcements():
                self.announcements = load_announcements()
                self.current_announcement_idx = 0
                self.load_announcements_to_text()
                self.update_announcement_display()
                messagebox.showinfo("成功", "已恢复默认公告")

    def create_control_panel(self, fetch_data_callback, load_data_callback):
        """创建控制面板"""
        control_frame = ttk.LabelFrame(self.main_frame, text="控制面板", padding=10)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(control_frame, text="刷新数据", 
                   command=lambda: threading.Thread(target=fetch_data_callback, daemon=True).start()).pack(side=tk.LEFT, padx=5)

        # 成交金额控制
        amount_frame = ttk.Frame(control_frame)
        amount_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(amount_frame, text="最小成交金额(万):").pack(side=tk.LEFT, padx=5)
        ttk.Button(amount_frame, text="-", width=3, 
                   command=lambda: self.adjust_amount(-200, load_data_callback)).pack(side=tk.LEFT, padx=2)
        self.amount_label = ttk.Label(amount_frame, textvariable=self.amount_var, width=6, 
                                     anchor="center", background="white", relief="sunken", padding=3)
        self.amount_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(amount_frame, text="+", width=3, 
                   command=lambda: self.adjust_amount(200, load_data_callback)).pack(side=tk.LEFT, padx=2)

        # 市值控制
        market_cap_frame = ttk.Frame(control_frame)
        market_cap_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(market_cap_frame, text="最大总市值(亿):").pack(side=tk.LEFT, padx=5)
        ttk.Button(market_cap_frame, text="-", width=3, 
                   command=lambda: self.adjust_market_cap(-20, load_data_callback)).pack(side=tk.LEFT, padx=2)
        self.market_cap_label = ttk.Label(market_cap_frame, textvariable=self.market_cap_var, width=6, 
                                         anchor="center", background="white", relief="sunken", padding=3)
        self.market_cap_label.pack(side=tk.LEFT, padx=2)
        ttk.Button(market_cap_frame, text="+", width=3, 
                   command=lambda: self.adjust_market_cap(10, load_data_callback)).pack(side=tk.LEFT, padx=2)

        # 排序选择
        ttk.Label(control_frame, text="排序方式:").pack(side=tk.LEFT, padx=5)
        sort_options = ["总成交金额", "涨幅", "总成笔数", "换手", "总市值", "量比"]
        sort_combo = ttk.Combobox(control_frame, textvariable=self.sort_var, values=sort_options, width=10, state="readonly")
        sort_combo.pack(side=tk.LEFT, padx=5)
        sort_combo.bind("<<ComboboxSelected>>", lambda e: load_data_callback())
        
        ttk.Button(control_frame, text="选择显示字段", command=lambda: self.select_columns(load_data_callback)).pack(side=tk.RIGHT, padx=5)

    def adjust_amount(self, delta, load_data_callback):
        """调整成交金额"""
        try:
            current = int(self.amount_var.get())
            new_value = max(0, current + delta)
            self.amount_var.set(str(new_value))
            load_data_callback()
        except ValueError:
            self.amount_var.set("2000")
            load_data_callback()

    def adjust_market_cap(self, delta, load_data_callback):
        """调整市值"""
        try:
            current = int(self.market_cap_var.get())
            new_value = max(0, current + delta)
            self.market_cap_var.set(str(new_value))
            load_data_callback()
        except ValueError:
            self.market_cap_var.set("100")
            load_data_callback()

    def select_columns(self, load_data_callback):
        """选择显示列"""
        select_window = tk.Toplevel(self.master)
        select_window.title("选择显示字段")
        center_window(select_window, 300, 600)
        
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
        
        ttk.Button(select_window, text="确认", 
                   command=lambda: self.apply_column_selection(select_window, load_data_callback)).pack(side=tk.BOTTOM, pady=10)

    def apply_column_selection(self, window, load_data_callback):
        """应用列选择"""
        self.display_columns = [col for col, var in self.column_vars.items() if var.get()]
        window.destroy()
        load_data_callback()

    def create_data_table(self, event_handlers=None):
        """创建数据表格"""
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
        style.configure("Custom.Treeview", font=('Microsoft YaHei', 8))
        style.configure("Custom.Treeview", rowheight=30)
        style.configure("Custom.Treeview.Heading", font=('Microsoft YaHei', 11, 'bold'))

        # 创建Treeview
        self.tree = ttk.Treeview(self.tree_container, show="headings", style="Custom.Treeview")

        # 滚动条
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
        if event_handlers:
            if 'double_click' in event_handlers:
                self.tree.bind("<Double-1>", event_handlers['double_click'])
            if 'right_click' in event_handlers:
                self.tree.bind("<Button-3>", event_handlers['right_click'])

    def create_context_menu(self, menu_items):
        """创建右键菜单"""
        self.context_menu = tk.Menu(self.master, tearoff=0)
        for item in menu_items:
            if item == "separator":
                self.context_menu.add_separator()
            else:
                self.context_menu.add_command(label=item['label'], command=item['command'])

    def show_loading(self):
        """显示加载动画"""
        if self.loading_frame:
            self.loading_frame.place(x=0, y=0, relwidth=1, relheight=1)
            self.loading_frame.lift()
            self.start_loading_animation()

    def hide_loading(self):
        """隐藏加载动画"""
        if self.loading_frame:
            self.loading_frame.place_forget()
            self.stop_loading_animation()

    def start_loading_animation(self):
        """开始loading图标旋转动画"""
        def animate():
            if hasattr(self, 'loading_icon'):
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

    def update_status(self, text):
        """更新状态栏"""
        if self.status_label:
            self.status_label.config(text=text)

    def show_data_load_option(self, load_callback):
        """显示数据加载选项"""
        result = messagebox.askyesno("数据加载", "是否立即加载股票数据？\n\n点击'是'立即加载（可能需要几分钟）\n点击'否'稍后手动加载")
        if result:
            threading.Thread(target=load_callback, daemon=True).start()
        else:
            self.update_status("程序已就绪，点击'刷新数据'按钮开始获取股票信息")