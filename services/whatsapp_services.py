# whatsapp_service.py

import requests
import config

WHATSAPP_API_URL = f"https://graph.facebook.com/v22.0/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
ACCESS_TOKEN = config.WHATSAPP_ACCESS_TOKEN

def send_whatsapp_message(to_number: str, message: str):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message}
    }

    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)

    if response.status_code != 200:
        return {"success": False, "error": response.text}

    return {"success": True, "response": response.json()}
