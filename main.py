"""
Main application module for StockSeek - Refactored version.
Serves as the entry point and main application controller.
"""

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

# Lazy imports for GUI components
tk = None
messagebox = None
Font = None

def lazy_import_gui():
    """Lazy import GUI modules"""
    global tk, messagebox, Font
    if tk is None:
        try:
            import tkinter as tk_module
            from tkinter import messagebox as mb_module
            from tkinter.font import Font as font_module
            tk = tk_module
            messagebox = mb_module
            Font = font_module
        except ImportError as e:
            logging.error(f"GUI modules not available: {e}")
            raise

# Import modular components
from config_manager import ensure_config_file
from ui_components import UIComponents
from data_service import fetch_stock_data, process_stock_data, DataProcessor
from chart_window import KLineWindow
from ai_service import diagnose_stock, stream_stock_diagnosis
from utils import center_window, get_stock_info

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class StockVisualizationApp:
    """Main application class - refactored to use modular components"""

    def __init__(self, master):
        # Ensure GUI modules are loaded
        lazy_import_gui()
        
        self.master = master
        master.title("草船借箭 - 启动中...")
        center_window(master, 1400, 650)

        # Initialize core components
        self.ui = UIComponents(master)
        self.data_processor = DataProcessor()
        
        # Application state
        self.selected_stock = {"code": "", "name": ""}
        self.raw_stock_data = None
        self.stock_data = []
        
        # K线图窗口管理
        self.kline_windows = {}
        self.kline_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="KLine")

        # 创建启动提示
        self.ui.create_startup_ui()

        # 延迟初始化主界面
        master.after(100, self.initialize_main_app)

    def initialize_main_app(self):
        """初始化主应用程序"""
        try:
            # 更新状态
            self.ui.startup_label.config(text="正在加载配置...")
            self.master.update()

            # 初始化配置
            ensure_config_file()

            # 初始化主界面
            self.ui.initialize_main_ui()
            
            # 创建控制面板和数据表格
            self.ui.create_control_panel(self.fetch_data, self.load_data)
            
            # 设置事件处理器
            event_handlers = {
                'double_click': self.show_detail,
                'right_click': self.on_right_click
            }
            self.ui.create_data_table(event_handlers)
            
            # 创建右键菜单
            menu_items = [
                {'label': "大笔买入", 'command': self.show_big_buy_orders},
                {'label': "基本面分析", 'command': self.show_fundamental},
                {'label': "资金流", 'command': self.show_fund_flow},
                {'label': "K线图", 'command': self.show_k_line},
                {'label': "AI诊股", 'command': self.show_ai_diagnose},
                "separator",
                {'label': "复制股票代码", 'command': self.copy_stock_code},
                {'label': "复制股票名称", 'command': self.copy_stock_name}
            ]
            self.ui.create_context_menu(menu_items)

            # 启动后台任务
            self.ui.update_announcement()
            self.ui.update_clock()

            # 界面加载完成，询问是否立即加载数据
            self.ui.show_data_load_option(self.fetch_data)

        except Exception as e:
            logging.error(f"初始化主应用程序失败: {e}")
            messagebox.showerror("启动错误", f"程序启动失败: {str(e)}")

    def fetch_data(self):
        """获取股票数据"""
        try:
            self.ui.show_loading()
            self.ui.update_status("正在获取股票数据...")
            
            # 重置计数器
            self.data_processor.processed_count = 0
            self.data_processor.failed_count = 0

            # 获取原始数据
            self.raw_stock_data = fetch_stock_data()
            
            # 处理数据
            self.process_and_display_data()
            
        except Exception as e:
            logging.error(f"获取数据失败: {e}")
            self.ui.update_status(f"获取数据失败: {str(e)}")
            messagebox.showerror("错误", f"获取数据失败: {str(e)}")
        finally:
            self.ui.hide_loading()

    def process_and_display_data(self):
        """处理并显示数据"""
        if self.raw_stock_data is None or self.raw_stock_data.empty:
            self.ui.update_status("没有可显示的数据")
            return

        try:
            # 获取过滤条件
            min_amount = int(self.ui.amount_var.get()) * 10000  # 转换为万元
            max_market_cap = int(self.ui.market_cap_var.get()) * 100000000  # 转换为亿元
            sort_by = self.ui.sort_var.get()

            # 应用过滤条件
            filtered_data = process_stock_data(
                self.raw_stock_data, 
                min_amount=min_amount,
                min_market_cap=max_market_cap
            )

            # 进一步过滤市值上限
            if max_market_cap > 0:
                filtered_data = filtered_data[filtered_data['总市值'] <= max_market_cap]

            # 排序
            if sort_by in filtered_data.columns:
                filtered_data = filtered_data.sort_values(by=sort_by, ascending=False)

            self.load_data_to_table(filtered_data)
            
        except Exception as e:
            logging.error(f"处理数据失败: {e}")
            self.ui.update_status(f"处理数据失败: {str(e)}")

    def load_data(self):
        """重新加载数据（不重新获取）"""
        if self.raw_stock_data is not None:
            self.process_and_display_data()

    def load_data_to_table(self, data):
        """将数据加载到表格中"""
        try:
            # 清空现有数据
            for item in self.ui.tree.get_children():
                self.ui.tree.delete(item)

            # 设置列
            display_columns = [col for col in self.ui.display_columns if col in data.columns]
            self.ui.tree["columns"] = display_columns
            
            # 配置列标题和宽度
            for col in display_columns:
                self.ui.tree.heading(col, text=col, anchor="center")
                
                # 根据列内容调整宽度
                if col in ["代码", "名称"]:
                    width = 100
                elif col in ["涨幅", "最新", "今开", "最高", "最低"]:
                    width = 80
                elif col in ["换手", "量比"]:
                    width = 70
                else:
                    width = 120
                    
                self.ui.tree.column(col, width=width, anchor="center")

            # 添加数据行
            for _, row in data.iterrows():
                values = []
                for col in display_columns:
                    value = row.get(col, "")
                    # 格式化数值显示
                    if col == "涨幅" and isinstance(value, (int, float)):
                        values.append(f"{value:.2f}%")
                    elif col == "总市值" and isinstance(value, (int, float)):
                        values.append(f"{value/100000000:.2f}亿")
                    elif col == "总成交金额" and isinstance(value, (int, float)):
                        values.append(f"{value/10000:.0f}万")
                    elif isinstance(value, float):
                        values.append(f"{value:.2f}")
                    else:
                        values.append(str(value))
                
                # 插入行，根据涨幅设置颜色标签
                item_id = self.ui.tree.insert("", "end", values=values)
                
                # 设置行颜色
                try:
                    if "涨幅" in display_columns:
                        change_idx = display_columns.index("涨幅")
                        change_value = row.get("涨幅", 0)
                        if isinstance(change_value, (int, float)):
                            if change_value > 0:
                                self.ui.tree.set(item_id, display_columns[change_idx], f"{change_value:.2f}%")
                                # 红色表示上涨
                                self.ui.tree.tag_configure("positive", foreground="red")
                                self.ui.tree.item(item_id, tags=("positive",))
                            elif change_value < 0:
                                self.ui.tree.set(item_id, display_columns[change_idx], f"{change_value:.2f}%")
                                # 绿色表示下跌
                                self.ui.tree.tag_configure("negative", foreground="green")
                                self.ui.tree.item(item_id, tags=("negative",))
                except (ValueError, IndexError):
                    pass

            self.ui.update_status(f"已加载 {len(data)} 只股票数据")
            
        except Exception as e:
            logging.error(f"加载数据到表格失败: {e}")
            self.ui.update_status(f"加载数据失败: {str(e)}")

    def show_detail(self, event):
        """显示股票详细信息"""
        item = self.ui.tree.selection()[0]
        if item:
            columns = list(self.ui.tree["columns"])
            values = [self.ui.tree.set(item, col) for col in columns]
            
            detail_window = tk.Toplevel(self.master)
            detail_window.title(f"{values[columns.index('名称')] if '名称' in columns else ''} ({values[columns.index('代码')] if '代码' in columns else ''}) 详细信息")
            center_window(detail_window, 600, 400)
            
            text = tk.Text(detail_window, wrap=tk.WORD)
            text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            info_lines = [f"{col}: {value}" for col, value in zip(columns, values)]
            info = "\n".join(info_lines)
            text.insert(tk.END, info)
            
            # 设置涨幅颜色
            if "涨幅" in columns:
                try:
                    change_idx = columns.index("涨幅")
                    change_str = values[change_idx].replace('%', '')
                    change = float(change_str)
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
        """右键菜单处理"""
        item = self.ui.tree.identify_row(event.y)
        if item:
            self.ui.tree.selection_set(item)
            self.update_selected_stock()
            self.ui.context_menu.post(event.x_root, event.y_root)

    def update_selected_stock(self):
        """更新选中的股票信息"""
        selection = self.ui.tree.selection()
        if selection:
            item = selection[0]
            columns = list(self.ui.tree["columns"])
            if "代码" in columns and "名称" in columns:
                code = self.ui.tree.set(item, "代码")
                name = self.ui.tree.set(item, "名称")
                self.selected_stock = {"code": code, "name": name}

    def show_k_line(self):
        """显示K线图"""
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return
        
        try:
            # 创建K线图窗口
            kline_window = KLineWindow(
                self.master, 
                self.selected_stock["code"], 
                self.selected_stock["name"]
            )
            
            # 保存窗口引用
            self.kline_windows[kline_window.window_id] = kline_window
            
        except Exception as e:
            logging.error(f"显示K线图失败: {e}")
            messagebox.showerror("错误", f"显示K线图失败: {str(e)}")

    def show_ai_diagnose(self):
        """显示AI诊股"""
        if not self.selected_stock["code"]:
            messagebox.showwarning("提示", "请先选择一只股票")
            return
        
        try:
            # 创建诊股窗口
            diagnose_window = tk.Toplevel(self.master)
            diagnose_window.title(f"AI诊股 - {self.selected_stock['name']}({self.selected_stock['code']})")
            center_window(diagnose_window, 800, 600)
            
            # 创建文本区域
            text_frame = tk.Frame(diagnose_window)
            text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            text_widget = tk.Text(text_frame, wrap=tk.WORD, font=('Microsoft YaHei', 11))
            scrollbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
            text_widget.configure(yscrollcommand=scrollbar.set)
            
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 开始诊股
            text_widget.insert(tk.END, f"正在为 {self.selected_stock['name']}({self.selected_stock['code']}) 进行AI诊股分析...\n\n")
            text_widget.update()
            
            def update_text(content):
                text_widget.insert(tk.END, content)
                text_widget.see(tk.END)
                text_widget.update()
            
            # 异步执行诊股
            def run_diagnosis():
                try:
                    stream_stock_diagnosis(
                        self.selected_stock['code'],
                        self.selected_stock['name'],
                        callback=update_text
                    )
                except Exception as e:
                    update_text(f"\n\n诊股过程中出现错误：{str(e)}")
            
            threading.Thread(target=run_diagnosis, daemon=True).start()
            
        except Exception as e:
            logging.error(f"AI诊股失败: {e}")
            messagebox.showerror("错误", f"AI诊股失败: {str(e)}")

    def show_big_buy_orders(self):
        """显示大笔买入信息"""
        messagebox.showinfo("功能提示", "大笔买入功能正在开发中...")

    def show_fundamental(self):
        """显示基本面分析"""
        messagebox.showinfo("功能提示", "基本面分析功能正在开发中...")

    def show_fund_flow(self):
        """显示资金流"""
        messagebox.showinfo("功能提示", "资金流功能正在开发中...")

    def copy_stock_code(self):
        """复制股票代码"""
        if self.selected_stock["code"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.selected_stock["code"])
            self.ui.update_status(f"已复制股票代码: {self.selected_stock['code']}")

    def copy_stock_name(self):
        """复制股票名称"""
        if self.selected_stock["name"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.selected_stock["name"])
            self.ui.update_status(f"已复制股票名称: {self.selected_stock['name']}")

    def cleanup_closed_windows(self):
        """清理已关闭的K线图窗口"""
        closed_windows = []
        for window_id, kline_window in self.kline_windows.items():
            try:
                if not kline_window.window.winfo_exists():
                    closed_windows.append(window_id)
            except tk.TclError:
                closed_windows.append(window_id)
        
        for window_id in closed_windows:
            del self.kline_windows[window_id]
            logging.info(f"清理已关闭的K线图窗口: {window_id}")

    def __del__(self):
        """清理资源"""
        if hasattr(self, 'kline_executor'):
            self.kline_executor.shutdown(wait=False)
        if hasattr(self, 'data_processor'):
            self.data_processor.shutdown()


def main():
    """主函数"""
    # Ensure GUI modules are loaded
    lazy_import_gui()
    
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


if __name__ == "__main__":
    main()