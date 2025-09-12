import re
from datetime import datetime
from Shenmi import Update
from Shenmi.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import requests
import json
import random

def get_tenant_access_token(app_id, app_secret):
    url = "https://open.f.mioffice.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    payload = {'app_id': app_id, 'app_secret': app_secret}
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    response_data = response.json()

    if response_data.get('code') == 0:
        return response_data.get('tenant_access_token'), response_data.get('expire')
    else:
        error_message = response_data.get('msg')
        return None, error_message

def send_card_message(chat_id, title, content):
    app_id = '输入您的 app id'
    app_secret = '输入您的 app_secret'
    tenant_access_token, expires_or_error = get_tenant_access_token(app_id, app_secret)
    
    if tenant_access_token is None:
        print(f"获取 token 失败，错误信息: {expires_or_error}")
        return

 # colors = ['blue', 'wathet', 'turquoise', 'green', 'yellow', 'orange', 'red', 'carmine', 'violet', 'purple', 'indigo'] 会导致偶发性重推，注释掉了。
    colors = ['wathet']
    color = random.choice(colors)
    
    url = "https://open.f.mioffice.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        'Authorization': f'Bearer {tenant_access_token}',
        'Content-Type': 'application/json'
    }
    card_content = {
        "header": {
            "title": {
                "content": title,
                "tag": "plain_text"
            },
            "template": color
        },
        "config": {
            "wide_screen_mode": True
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "content": content,
                    "tag": "lark_md"
                }
            },
            {
                "tag": "hr"
            },
            {
                "tag": "div",
                "text": {
                    "content": "\n\n注：摘要、正文均不代表个人观点 [📚阿呆](https://xiaomi.f.mioffice.cn/docx/doxk4ziddiL3yoOEDOKqyRMfuvb)",
                    "tag": "lark_md"
                }
            }
        ]
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content)
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

def format_with_entities(text, entities):
    entities_list = list(entities) if entities else []
    if entities_list:
        entities_list.sort(key=lambda x: x.offset, reverse=True)
        for entity in entities_list:
            if entity.type == 'text_link':
                start = entity.offset
                end = start + entity.length
                link_text = text[start:end]
                markdown_link = f"[{link_text}]({entity.url})"
                text = text[:start] + markdown_link + text[end:]
    return text

def check_keywords(text):
    keyword_patterns = {
        '涉政词': re.compile(r'输入您的关键词|输入您的关键词1', re.IGNORECASE),
        '广告词': re.compile(r'输入您\的关键词', re.IGNORECASE),
        '其它词': re.compile(r'输入您的关键词', re.IGNORECASE)
    }
    for key, pattern in keyword_patterns.items():
        if pattern.search(text):
            return key
    return None

def echo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if user_id != xxxxxxxxxx:
        print("消息非指定userid，忽略")
        return

    text = update.message.text or update.message.caption or ""
    if not text:
        # 如果没有文本则返回，防止图/视空白推送
        return

    entities = update.message.entities or update.message.caption_entities
    text = format_with_entities(text, entities) if text else ''
    
    if 'pass' in text:
        keyword_type = None
    else:
        keyword_type = check_keywords(text)

    if keyword_type:
        summary = text[:6] + '...'  
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = "资讯已被过滤"
        content = f"{now} 摘要「{summary}」因 {keyword_type} 已被过滤"
    else:
        lines = text.strip().split('\n')
        if len(lines) == 1:
            title = '简短资讯'
            content = text
        else:
            title = lines[0] if lines else 'No Title'
            content = '\n'.join(lines[1:]) if len(lines) > 1 else 'No additional text'
    
    chat_id = '输入您的飞书群组ID'  
    send_card_message(chat_id, title, content)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hello! I am your bot.')

def main():
    application = Application.builder().token('输入资讯平台Bot Api').build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT | filters.CAPTION & ~filters.COMMAND, echo))
    application.run_polling()

if __name__ == '__main__':
    main()