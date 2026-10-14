@st.cache_data(ttl=3)
def obtener_mercado_publico(trade_type, trans_amount):
    url = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
    
    # Payload base
    filtros = { 
        "fiat": "VES", 
        "page": 1, 
        "rows": 5, 
        "tradeType": trade_type, 
        "asset": "USDT", 
        "countries": [], 
        "proMerchantAds": False, 
        "shieldMerchantAds": False, 
        "publisherType": "merchant", 
        "payTypes": ["BancodeVenezuela", "BankTransferVenezuela"] 
    }
    
    # Lógica para manejar el filtro de "Bloque" o monto normal
    if trans_amount == "bloque":
        filtros["tradeZone"] = "block" # Parámetro que suele usar Binance para P2P en Bloque
        filtros["transAmount"] = ""
    else:
        filtros["transAmount"] = str(trans_amount)
        
    try:
        res = requests.post(url, json=filtros, headers={'Content-Type': 'application/json'}, timeout=4)
        return res.json().get('data', [])
    except: 
        return []
