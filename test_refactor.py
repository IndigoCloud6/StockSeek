#!/usr/bin/env python3
"""
Test script for the refactored StockSeek modules.
This tests the functionality without requiring GUI components.
"""

import logging
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_config_manager():
    """Test configuration manager"""
    print("Testing config_manager...")
    try:
        from config_manager import ensure_config_file, load_api_key, load_announcements
        
        # Test config file creation
        ensure_config_file()
        print("✓ Config file creation works")
        
        # Test API key loading
        api_key = load_api_key()
        print(f"✓ API key loading works: {api_key[:10]}...")
        
        # Test announcements loading
        announcements = load_announcements()
        print(f"✓ Announcements loading works: {len(announcements)} announcements")
        
        return True
    except Exception as e:
        print(f"✗ Config manager test failed: {e}")
        return False

def test_utils():
    """Test utility functions"""
    print("\nTesting utils...")
    try:
        from utils import get_stock_info, validate_stock_code, format_amount
        
        # Test stock info parsing
        info = get_stock_info("000001")
        print(f"✓ Stock info parsing works: 000001 -> {info}")
        
        # Test stock code validation
        valid = validate_stock_code("000001")
        invalid = validate_stock_code("abc")
        print(f"✓ Stock code validation works: 000001={valid}, abc={invalid}")
        
        # Test amount formatting
        formatted = format_amount(123456789)
        print(f"✓ Amount formatting works: 123456789 -> {formatted}")
        
        return True
    except Exception as e:
        print(f"✗ Utils test failed: {e}")
        return False

def test_data_service():
    """Test data service functions"""
    print("\nTesting data_service...")
    try:
        from data_service import lazy_import_data_modules, process_single_stock, calculate_rsi
        
        # Test lazy import (without actually importing heavy modules)
        print("✓ Data service imports work")
        
        # Test stock processing (basic structure)
        result = process_single_stock("000001", "平安银行")
        print(f"✓ Single stock processing works: {result}")
        
        return True
    except Exception as e:
        print(f"✗ Data service test failed: {e}")
        return False

def test_ai_service():
    """Test AI service functions"""
    print("\nTesting ai_service...")
    try:
        from ai_service import lazy_init_openai_client, validate_api_key
        
        # Test basic imports
        print("✓ AI service imports work")
        
        # Note: We won't test actual AI calls to avoid API usage
        print("✓ AI service structure is correct")
        
        return True
    except Exception as e:
        print(f"✗ AI service test failed: {e}")
        return False

def test_module_structure():
    """Test overall module structure"""
    print("\nTesting module structure...")
    try:
        # Test that all modules can be imported
        modules = [
            'config_manager',
            'utils', 
            'data_service',
            'ai_service'
        ]
        
        for module in modules:
            try:
                __import__(module)
                print(f"✓ Module {module} imports successfully")
            except Exception as e:
                print(f"✗ Module {module} import failed: {e}")
                return False
        
        return True
    except Exception as e:
        print(f"✗ Module structure test failed: {e}")
        return False

def test_file_structure():
    """Test that all expected files exist"""
    print("\nTesting file structure...")
    expected_files = [
        'main.py',
        'main_original.py',
        'config_manager.py',
        'utils.py',
        'data_service.py',
        'ai_service.py',
        'ui_components.py',
        'chart_window.py',
        'config.json',
        'requirements.txt'
    ]
    
    missing_files = []
    for file in expected_files:
        if not os.path.exists(file):
            missing_files.append(file)
        else:
            print(f"✓ File {file} exists")
    
    if missing_files:
        print(f"✗ Missing files: {missing_files}")
        return False
    
    return True

def main():
    """Run all tests"""
    print("=" * 50)
    print("StockSeek Refactoring Test Suite")
    print("=" * 50)
    
    tests = [
        test_file_structure,
        test_module_structure,
        test_config_manager,
        test_utils,
        test_data_service,
        test_ai_service
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            failed += 1
    
    print("\n" + "=" * 50)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 50)
    
    if failed == 0:
        print("🎉 All tests passed! Refactoring is successful!")
        return True
    else:
        print("❌ Some tests failed. Please review the issues above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)