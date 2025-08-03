# StockSeek - 草船借箭 (Refactored)

A powerful Chinese stock market analysis tool with AI-powered diagnostics, technical analysis, and real-time data visualization.

## 🎯 Project Overview

StockSeek has been completely refactored from a monolithic 1746-line main.py file into a clean, modular architecture that's easier to maintain, extend, and understand.

## 📁 Project Structure

```
StockSeek/
├── main.py                 # Main application entry point (434 lines)
├── config_manager.py       # Configuration and settings management
├── data_service.py         # Stock data fetching and processing
├── ui_components.py        # User interface components
├── chart_window.py         # K-line chart display module
├── ai_service.py           # AI-powered stock diagnosis
├── utils.py               # Utility functions
├── main_original.py       # Original monolithic file (backup)
├── config.json           # Application configuration
├── requirements.txt      # Python dependencies
├── test_refactor.py      # Test suite for refactored modules
└── README_REFACTOR.md    # This file
```

## 🚀 Key Features

### Core Functionality
- **Real-time Stock Data**: Integration with akshare for live market data
- **Technical Analysis**: K-line charts with indicators (MA, RSI, Bollinger Bands)
- **AI Stock Diagnosis**: Powered by OpenAI/DeepSeek for intelligent analysis
- **Data Filtering**: Advanced filtering by market cap, volume, sector
- **Export Capabilities**: Save data to Excel format

### Refactoring Benefits
- **75% Code Reduction**: Main file reduced from 1746 to 434 lines
- **Modular Design**: 7 focused modules with single responsibilities
- **Lazy Loading**: Heavy modules loaded only when needed
- **Error Handling**: Robust error handling with graceful fallbacks
- **Test Coverage**: Comprehensive test suite included

## 🛠 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/IndigoCloud6/StockSeek.git
   cd StockSeek
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API Key**
   Edit `config.json` and add your OpenAI/DeepSeek API key:
   ```json
   {
     "api_key": "your-api-key-here",
     "announcements": [...]
   }
   ```

## 🏃 Usage

### Running the Application
```bash
python main.py
```

### Running Tests
```bash
python test_refactor.py
```

## 📦 Module Details

### `config_manager.py`
Handles all configuration-related operations:
- Configuration file creation and validation
- API key management
- System announcements management
- Settings persistence

### `data_service.py`
Manages stock data operations:
- akshare integration for real-time data
- Data processing and filtering
- Technical indicator calculations
- Parallel processing for multiple stocks

### `ui_components.py`
Provides reusable UI components:
- Main application interface
- Data tables with sorting and filtering
- Control panels and forms
- Loading animations and status updates

### `chart_window.py`
Handles chart visualization:
- K-line chart generation
- Technical indicators overlay
- Interactive chart tools
- Multiple window management

### `ai_service.py`
AI-powered analysis features:
- OpenAI/DeepSeek integration
- Streaming stock diagnosis
- Market sentiment analysis
- API key validation

### `utils.py`
Common utility functions:
- Stock code validation and parsing
- Data formatting helpers
- Window positioning utilities
- File operations

## 🧪 Testing

The project includes a comprehensive test suite (`test_refactor.py`) that validates:
- ✅ File structure integrity
- ✅ Module import functionality
- ✅ Configuration management
- ✅ Utility functions
- ✅ Data service operations
- ✅ AI service structure

Run tests with: `python test_refactor.py`

## 🔧 Configuration

### System Requirements
- Python 3.8+
- Required packages listed in `requirements.txt`
- GUI support (tkinter)

### Key Configuration Options
- **API Key**: Set in `config.json` for AI features
- **Data Filters**: Configurable market cap and volume thresholds
- **Display Columns**: Customizable data table columns
- **Announcements**: Editable system announcements

## 🚨 Error Handling

The refactored version includes robust error handling:
- Graceful fallbacks for missing dependencies
- Lazy loading to avoid import errors
- Comprehensive logging
- User-friendly error messages

## 🔄 Migration from Original

If upgrading from the original version:
1. The original file is preserved as `main_original.py`
2. All functionality remains the same
3. Configuration is automatically migrated
4. No data loss occurs

## 📈 Performance Improvements

- **Faster Startup**: Lazy loading of heavy modules
- **Better Memory Usage**: Modules loaded on demand
- **Improved Responsiveness**: Better separation of UI and data processing
- **Easier Debugging**: Clear module boundaries

## 🤝 Contributing

The modular structure makes contributing easier:
1. Each module has a clear purpose
2. Tests validate functionality
3. Changes can be made to individual modules
4. Code review is more focused

## 📝 License

This project is licensed under the MIT License - see the original repository for details.

## 🔗 Related

- Original repository: [IndigoCloud6/StockSeek](https://github.com/IndigoCloud6/StockSeek)
- akshare library: [akshare](https://github.com/akfamily/akshare)
- OpenAI API: [OpenAI Platform](https://platform.openai.com/)

---

**Note**: This refactored version maintains 100% compatibility with the original functionality while providing a much cleaner, more maintainable codebase.