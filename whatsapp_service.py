import requests
import config

def send_whatsapp_message(phone: str, message: str):
    url = f"https://graph.facebook.com/v22.0/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace(" ", "").replace("+", ""),
        "type": "text",
        "text": {
            "body": message
        }
    }

    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    res = requests.post(url, json=payload, headers=headers)
    return res.json()
