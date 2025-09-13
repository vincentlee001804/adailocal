# PythonAnywhere Setup Guide for News Bot

## Step 1: Upload Code to PythonAnywhere

### Option A: Using Git (Recommended)
1. Open a **Bash console** in PythonAnywhere
2. Run these commands:
```bash
# Clone your repository
git clone https://github.com/vincentlee001804/adailocal.git
cd adailocal

# Verify files are there
ls -la
```

### Option B: Manual Upload
1. Go to **Files** tab in PythonAnywhere
2. Create a new directory: `news_bot`
3. Upload these files:
   - `adailocal.py`
   - `.gitignore`

## Step 2: Install Dependencies

In the Bash console, run:
```bash
cd adailocal  # or news_bot if you used manual upload

# Install required packages
pip3.10 install --user requests feedparser beautifulsoup4 python-dateutil sumy nltk lxml

# Download NLTK data
python3.10 -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab')"
```

## Step 3: Set Environment Variables

Create a `.env` file or set environment variables:
```bash
# Create .env file
nano .env
```

Add your environment variables:
```
FEISHU_WEBHOOK_URL=your_webhook_url_here
ONE_SHOT=1
MAX_PUSH_PER_CYCLE=1
SEND_INTERVAL_SEC=1.0
USE_AI_SUMMARY=1
```

## Step 4: Test the Bot

Test the bot manually first:
```bash
cd adailocal
python3.10 adailocal.py
```

## Step 5: Set Up Scheduled Task

1. Go to **Tasks** tab in PythonAnywhere
2. Click **"Create a new task"**
3. Set up the task:
   - **Command**: `cd /home/vincentlee/adailocal && python3.10 adailocal.py`
   - **Hour**: `*` (every hour)
   - **Minute**: `0,10,20,30,40,50` (every 10 minutes)
   - **Day of month**: `*`
   - **Month**: `*`
   - **Day of week**: `*`

## Step 6: Monitor the Bot

- Check **Tasks** tab for execution logs
- Check **Files** tab to see if `sent_news.txt` is being created
- Monitor your Feishu group for news updates

## Troubleshooting

### If packages fail to install:
```bash
# Try with specific Python version
python3.10 -m pip install --user requests feedparser beautifulsoup4 python-dateutil sumy nltk lxml
```

### If NLTK data fails:
```bash
python3.10 -c "import nltk; nltk.download('punkt', download_dir='/home/vincentlee/nltk_data')"
python3.10 -c "import nltk; nltk.download('punkt_tab', download_dir='/home/vincentlee/nltk_data')"
```

### Check Python version:
```bash
python3.10 --version
```

## File Structure on PythonAnywhere
```
/home/vincentlee/
├── adailocal/
│   ├── adailocal.py
│   ├── .env
│   ├── sent_news.txt (created after first run)
│   └── .gitignore
└── nltk_data/ (if needed)
```
