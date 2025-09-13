#!/usr/bin/env python3
"""
PythonAnywhere Setup Script for News Bot
Run this script to set up the environment and test the bot
"""

import os
import sys
import subprocess

def run_command(command, description):
    """Run a command and print the result"""
    print(f"\n🔧 {description}")
    print(f"Running: {command}")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Success: {description}")
            if result.stdout:
                print(f"Output: {result.stdout}")
        else:
            print(f"❌ Error: {description}")
            print(f"Error: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def check_python_version():
    """Check Python version"""
    print(f"🐍 Python version: {sys.version}")
    if sys.version_info < (3, 8):
        print("⚠️  Warning: Python 3.8+ recommended")
    return True

def install_dependencies():
    """Install required packages"""
    packages = [
        "requests",
        "feedparser", 
        "beautifulsoup4",
        "python-dateutil",
        "sumy",
        "nltk",
        "lxml"
    ]
    
    for package in packages:
        success = run_command(f"pip3.10 install --user {package}", f"Installing {package}")
        if not success:
            print(f"⚠️  Failed to install {package}, trying alternative method...")
            run_command(f"python3.10 -m pip install --user {package}", f"Installing {package} (alternative)")

def download_nltk_data():
    """Download NLTK data"""
    nltk_script = """
import nltk
try:
    nltk.download('punkt')
    nltk.download('punkt_tab')
    print("NLTK data downloaded successfully")
except Exception as e:
    print(f"Error downloading NLTk data: {e}")
"""
    
    with open("temp_nltk_download.py", "w") as f:
        f.write(nltk_script)
    
    success = run_command("python3.10 temp_nltk_download.py", "Downloading NLTK data")
    
    # Clean up
    if os.path.exists("temp_nltk_download.py"):
        os.remove("temp_nltk_download.py")
    
    return success

def check_environment():
    """Check if environment variables are set"""
    print("\n🔍 Checking environment variables...")
    
    required_vars = [
        "FEISHU_WEBHOOK_URL",
        "ONE_SHOT", 
        "MAX_PUSH_PER_CYCLE",
        "SEND_INTERVAL_SEC",
        "USE_AI_SUMMARY"
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.environ.get(var)
        if value:
            # Don't print the actual webhook URL for security
            if "WEBHOOK" in var:
                print(f"✅ {var}: [SET]")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: [NOT SET]")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Missing environment variables: {', '.join(missing_vars)}")
        print("Please set these in your .env file or environment")
        return False
    
    return True

def test_imports():
    """Test if all required modules can be imported"""
    print("\n🧪 Testing imports...")
    
    modules = [
        "requests",
        "feedparser", 
        "bs4",
        "dateutil",
        "sumy",
        "nltk",
        "lxml"
    ]
    
    failed_imports = []
    for module in modules:
        try:
            __import__(module)
            print(f"✅ {module}: OK")
        except ImportError as e:
            print(f"❌ {module}: FAILED - {e}")
            failed_imports.append(module)
    
    if failed_imports:
        print(f"\n⚠️  Failed imports: {', '.join(failed_imports)}")
        return False
    
    return True

def main():
    """Main setup function"""
    print("🚀 PythonAnywhere News Bot Setup")
    print("=" * 50)
    
    # Check Python version
    check_python_version()
    
    # Install dependencies
    print("\n📦 Installing dependencies...")
    install_dependencies()
    
    # Download NLTK data
    print("\n📚 Downloading NLTK data...")
    download_nltk_data()
    
    # Test imports
    if not test_imports():
        print("\n❌ Some imports failed. Please check the installation.")
        return False
    
    # Check environment
    if not check_environment():
        print("\n⚠️  Environment variables not set. Please configure them.")
        return False
    
    print("\n🎉 Setup completed successfully!")
    print("\nNext steps:")
    print("1. Set up your environment variables in .env file")
    print("2. Test the bot: python3.10 adailocal.py")
    print("3. Set up scheduled task in PythonAnywhere Tasks tab")
    
    return True

if __name__ == "__main__":
    main()
