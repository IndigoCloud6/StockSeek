"""
Configuration management module for StockSeek application.
Handles configuration file operations, API key management, and announcements.
"""

import json
import logging
import os

# Configuration file path
CONFIG_FILE = "config.json"

# Default values
DEFAULT_ANNOUNCEMENTS = [
    "系统公告：所有数据来源于公开市场信息，仅供参考，不构成投资建议。"
]

DEFAULT_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def ensure_config_file():
    """Create configuration file if it doesn't exist"""
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "announcements": DEFAULT_ANNOUNCEMENTS, 
                    "api_key": DEFAULT_API_KEY
                }, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"创建配置文件失败: {e}")


def load_api_key():
    """Load API key from configuration file"""
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


def load_announcements():
    """Load announcements from configuration file"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get("announcements", DEFAULT_ANNOUNCEMENTS)
    except Exception as e:
        logging.error(f"读取公告失败: {e}")
        return DEFAULT_ANNOUNCEMENTS


def save_announcements(announcements):
    """Save announcements to configuration file"""
    try:
        # Load existing config
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        # Update announcements
        config["announcements"] = announcements
        
        # Save back to file
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        
        logging.info("公告保存成功")
        return True
    except Exception as e:
        logging.error(f"保存公告失败: {e}")
        return False


def reset_announcements():
    """Reset announcements to default values"""
    return save_announcements(DEFAULT_ANNOUNCEMENTS)