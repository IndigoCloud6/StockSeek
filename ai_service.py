"""
AI service module for StockSeek application.
Handles OpenAI client initialization and AI-powered stock diagnosis functionality.
"""

import logging
from config_manager import load_api_key

# Global variable for lazy-loaded OpenAI client
client = None


def lazy_init_openai_client():
    """Lazy initialization of OpenAI client"""
    global client
    
    if client is None:
        try:
            api_key = load_api_key()
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            logging.info("OpenAI客户端初始化完成")
        except Exception as e:
            logging.error(f"OpenAI客户端初始化失败: {e}")


def diagnose_stock(stock_code, stock_name, stock_data=None):
    """
    Use AI to diagnose a stock based on available data
    
    Args:
        stock_code: Stock code
        stock_name: Stock name  
        stock_data: Optional stock data for analysis
        
    Returns:
        str: AI diagnosis result
    """
    if client is None:
        lazy_init_openai_client()
    
    if client is None:
        return "AI服务暂不可用，请检查API配置"
    
    try:
        # Prepare the prompt for AI analysis
        prompt = f"""
        请对股票{stock_name}({stock_code})进行技术分析和投资建议。

        请从以下几个方面进行分析：
        1. 技术指标分析
        2. 基本面分析
        3. 市场趋势判断
        4. 风险评估
        5. 投资建议

        注意：所有分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。
        """
        
        # Add stock data to prompt if available
        if stock_data:
            prompt += f"\n当前股价相关信息：{stock_data}"
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的股票分析师，请提供客观、专业的股票分析。"},
                {"role": "user", "content": prompt}
            ],
            stream=True,
            max_tokens=1000,
            temperature=0.7
        )
        
        # Collect streaming response
        full_response = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                full_response += chunk.choices[0].delta.content
        
        return full_response
        
    except Exception as e:
        logging.error(f"AI诊股失败: {e}")
        return f"AI诊股服务暂时不可用：{str(e)}"


def stream_stock_diagnosis(stock_code, stock_name, stock_data=None, callback=None):
    """
    Stream AI stock diagnosis with real-time updates
    
    Args:
        stock_code: Stock code
        stock_name: Stock name
        stock_data: Optional stock data for analysis
        callback: Callback function to handle streaming updates
        
    Returns:
        str: Complete diagnosis result
    """
    if client is None:
        lazy_init_openai_client()
    
    if client is None:
        error_msg = "AI服务暂不可用，请检查API配置"
        if callback:
            callback(error_msg)
        return error_msg
    
    try:
        # Prepare the prompt
        prompt = f"""
        请对股票{stock_name}({stock_code})进行详细的技术分析和投资建议。

        分析要求：
        1. 技术指标分析（均线、RSI、MACD等）
        2. 基本面分析（财务状况、行业地位等）
        3. 市场趋势和情绪分析
        4. 风险评估和注意事项
        5. 具体的投资建议和操作策略

        请提供专业、客观的分析，避免过于乐观或悲观的判断。
        """
        
        if stock_data:
            prompt += f"\n\n当前股票数据：{stock_data}"
        
        # Stream the response
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个资深的股票分析师，拥有丰富的市场经验和专业知识。请提供深入、客观的股票分析。"},
                {"role": "user", "content": prompt}
            ],
            stream=True,
            max_tokens=1500,
            temperature=0.6
        )
        
        full_response = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_response += content
                
                # Call callback with each chunk if provided
                if callback:
                    callback(content)
        
        return full_response
        
    except Exception as e:
        error_msg = f"AI诊股过程中出现错误：{str(e)}"
        logging.error(error_msg)
        if callback:
            callback(error_msg)
        return error_msg


def get_market_sentiment():
    """
    Get general market sentiment analysis from AI
    
    Returns:
        str: Market sentiment analysis
    """
    if client is None:
        lazy_init_openai_client()
    
    if client is None:
        return "AI服务暂不可用"
    
    try:
        prompt = """
        请分析当前A股市场的整体情况和投资环境：
        
        1. 市场整体趋势分析
        2. 主要指数表现
        3. 热点板块和题材
        4. 资金流向分析
        5. 投资策略建议
        
        请提供客观、专业的市场分析。
        """
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的市场分析师，请提供客观的市场分析。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logging.error(f"获取市场情绪分析失败: {e}")
        return f"市场分析服务暂时不可用：{str(e)}"


def validate_api_key():
    """
    Validate if the OpenAI API key is working
    
    Returns:
        bool: True if API key is valid, False otherwise
    """
    if client is None:
        lazy_init_openai_client()
    
    if client is None:
        return False
    
    try:
        # Test with a simple request
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "测试"}],
            max_tokens=10
        )
        return True
    except Exception as e:
        logging.error(f"API密钥验证失败: {e}")
        return False