import requests

bot_token = '8901578611:AAFwH648xgPAfnw5Oh_ScBVuzVr94-JYkJI'
channel_id = '-1004295879936'

url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
data = {
    'chat_id': channel_id,
    'text': 'Sabadarmon MSKT - PACS Tizimi sinov xabari:\n\nGE CT apparati (192.168.10.250:4006) va PACS serveri o\'rtasida tarmoq aloqasi muvaffaqiyatli o\'rnatildi!'
}
res = requests.post(url, json=data)
print("Status code:", res.status_code)
print("Response:", res.json())
