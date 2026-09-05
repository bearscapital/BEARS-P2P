import streamlit as st
import requests
import pandas as pd
import time
import hmac
import hashlib
from urllib.parse import urlencode
from datetime import datetime, timedelta
import plotly.graph_objects as go

st.set_page_config(page_title="BEARS Terminal P2P", page_icon="⚡", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #ffffff; }
    [data-stale="true"] { opacity: 1 !important; filter: none !important; pointer-events: auto !important; transition: none !important; }
    div[data-testid="stFragment"] { opacity: 1 !important; }
    .card-box { background-color: #12161f; border: 1px solid #21262d; border-radius: 6px; padding: 12px; margin-bottom: 10px; }
    .header-compra { color: #0ecb81; font-weight: bold; font-size: 15px; border-bottom: 2px solid #0ecb81; padding-bottom: 4px; margin-bottom: 8px; }
    .header-venta { color: #f6465d; font-weight: bold; font-size: 15px; border-bottom: 2px solid #f6465d; padding-bottom: 4px; margin-bottom: 8px; }
    .header-center { color: #f0b90b; font-weight: bold; font-size: 15px; border-bottom: 2px solid #f0b90b; padding-bottom: 4px; margin-bottom: 8px; }
    .p2p-table { width: 100%; border-collapse: collapse; font-size: 12px; background-color: #12161f; border-radius: 6px; overflow: hidden; }
    .p2p-table th { background-color: #161a23; color: #848e9c; padding: 6px 8px; text-align: left; border-bottom: 1px solid #21262d; }
    .p2p-table td { padding: 6px 8px; border-bottom: 1px solid #1a1f2c; color: #eaecef; }
    .p2p-table tr:last-child td { border-bottom: none; }
    </style>
""", unsafe_allow_html=True)

if 'ganancia_sesion' not in st.session_state:
    st.session_state.ganancia_sesion = 0.0
    st.session_state.ciclos = 0

def sincronizar_tiempo_binance():
    try:
        res = requests.get('https://api.binance.com/api/v3/time', timeout=3)
        st.session_state.time_offset = res.json()['serverTime'] - int(time.time() * 1000)
    except:
        st.session_state.time_offset = 0

if 'time_offset' not in st.session_state:
    sincronizar_tiempo_binance()

st.sidebar.title("⚙️ Configuración")
with st.sidebar.expander("🔑 Credenciales API (Merchant)", expanded=False):
    api_key_input = st.text_input("API Key", type="password", value="")
    secret_key_input = st.text_input("Secret Key", type="password", value="")

capital_trabajo = st.sidebar.number_input("Capital de Trabajo (USDT)", value=400.0, step=50.0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎚️ Filtros de Mercado")
opcion_filtro = st.sidebar.radio("Selecciona los montos a escanear:", ("Perfil A (C: 70k | V: 20k)", "Perfil B (C: 20k | V: 10k)", "Perfil C (C: 70k | V: 70k)"))

if opcion_filtro == "Perfil A (C: 70k | V: 20k)": filtro_c, filtro_v = 70000, 20000
elif opcion_filtro == "Perfil B (C: 20k | V: 10k)": filtro_c, filtro_v = 20000, 10000
else: filtro_c, filtro_v = 70000, 70000

str_filtro_c, str_filtro_v = f"{filtro_c:,}".replace(',', '.'), f"{filtro_v:,}".replace(',', '.')

def realizar_peticion_firmada(endpoint, params, api_key, secret_key):
    url = 'https://api.binance.com' + endpoint
    for intento in range(2):
        if 'signature' in params: del params['signature']
        params['timestamp'] = int(time.time() * 1000) + st.session_state.get('time_offset', 0)
        params['recvWindow'] = 60000
        query_string = urlencode(params)
        signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        params['signature'] = signature
        headers = {'X-MBX-APIKEY': api_key}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=4)
            data = res.json()
            if str(data.get('code')) == '-1021':
                sincronizar_tiempo_binance()
                continue
            return data, None
        except Exception as e:
            return None, str(e)
    return None, "Error de sincronización"

def obtener_mis_anuncios(api_key, secret_key):
    if not api_key or not secret_key: return []
    data, err = realizar_peticion_firmada('/sapi/v1/c2c/ads/list', {}, api_key, secret_key)
    if data and data.get('code') == '000000': return data.get('data', [])
    return []

def obtener_ordenes_activas(api_key, secret_key):
    if not api_key or not secret_key: return [], "Faltan credenciales"
    ordenes_activas = []
    estados_activos = ['PENDING', 'TRADING', 'BUYER_PAYED', 'DISTRIBUTING', 'IN_APPEAL', 'PAYING']
    data, error = realizar_peticion_firmada('/sapi/v1/c2c/orderMatch/listUserOrderHistory', {'rows': 30}, api_key, secret_key)
    if error: return [], error
    if data and data.get('code') == '000000' and data.get('data'):
        for order in data['data']:
            if order.get('orderStatus') in estados_activos:
                ordenes_activas.append(order)
    elif data and str(data.get('code')) not in ['000000', '-1021']:
        return [], f"Error Binance [{data.get('code')}]: {data.get('msg')}"
    return ordenes_activas, None

@st.cache_data(ttl=3)
def obtener_mercado_publico(trade_type, trans_amount):
    url = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
    filtros = { "fiat": "VES", "page": 1, "rows": 5, "tradeType": trade_type, "asset": "USDT", "countries": [], "proMerchantAds": False, "shieldMerchantAds": False, "publisherType": "merchant", "payTypes": ["BancodeVenezuela", "BankTransferVenezuela"], "transAmount": str(trans_amount) }
    try:
        res = requests.post(url, json=filtros, headers={'Content-Type': 'application/json'}, timeout=4)
        return res.json().get('data', [])
    except: return []

st.title("⚡ BEARS Terminal P2P")
st.markdown("---")

col_compra, col_centro, col_venta = st.columns([1.2, 1, 1.2])

with col_compra:
    st.markdown('<div class="header-compra">COMPRA</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="display: flex; justify-content: space-between; background: #161a23; padding: 6px 10px; border-radius: 4px; font-size: 13px; color: #848e9c; margin-bottom: 8px;"><span><b>PM | BDV | TRANSF</b></span><span style="color: #0ecb81; font-weight: bold;">{str_filtro_c} VES</span></div>', unsafe_allow_html=True)
    
    @st.fragment(run_every=timedelta(seconds=4))
    def render_seccion_compra():
        mis_anuncios = obtener_mis_anuncios(api_key_input, secret_key_input)
        anuncios_compra = [ad for ad in mis_anuncios if ad.get('tradeType') == 'BUY']
        if anuncios_compra:
            html_c = '<table class="p2p-table"><tr><th>NRO</th><th>PRECIO</th><th>DISP</th><th>ESTADO</th></tr>'
            for ad in anuncios_compra: html_c += f"<tr><td>{str(ad.get('adNo'))[-6:]}</td><td>{float(ad.get('price', 0)):,.3f}</td><td>{float(ad.get('surplusAmount', 0)):,.1f}</td><td>{ad.get('advStatus')}</td></tr>"
            html_c += '</table>'
            st.markdown(html_c, unsafe_allow_html=True)
        else:
            mercado_c = obtener_mercado_publico("BUY", filtro_c)
            if mercado_c:
                html_c = '<table class="p2p-table"><tr><th>#</th><th>PRECIO</th><th>DISP</th><th>USUARIO</th></tr>'
                for idx, item in enumerate(mercado_c, 1): html_c += f"<tr><td>#{idx}</td><td>{float(item['adv']['price']):,.3f}</td><td>{float(item['adv']['surplusAmount']):.1f}</td><td>{item['advertiser']['nickName'][:12]}</td></tr>"
                html_c += '</table>'
                st.markdown(html_c, unsafe_allow_html=True)
            else: st.info("Cargando mercado de compra...")
                
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="header-center">📊 PERFIL DE VOLUMEN (VES/USDT)</div>', unsafe_allow_html=True)
        mercado_c_vol = obtener_mercado_publico("BUY", filtro_c)
        mercado_v_vol = obtener_mercado_publico("SELL", filtro_v)
        fig = go.Figure()
        if mercado_c_vol:
            precios_c = [float(x['adv']['price']) for x in mercado_c_vol]
            vol_c = [float(x['adv']['surplusAmount']) for x in mercado_c_vol]
            fig.add_trace(go.Bar(x=precios_c, y=vol_c, name='Órdenes de Compra', marker_color='#0ecb81', opacity=0.85, width=0.25))
        if mercado_v_vol:
            precios_v = [float(x['adv']['price']) for x in mercado_v_vol]
            vol_v = [float(x['adv']['surplusAmount']) for x in mercado_v_vol]
            fig.add_trace(go.Bar(x=precios_v, y=vol_v, name='Órdenes de Venta', marker_color='#f6465d', opacity=0.85, width=0.25))
        fig.update_layout(paper_bgcolor='#12161f', plot_bgcolor='#12161f', font_color='#848e9c', margin=dict(l=10, r=10, t=10, b=10), height=280, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)), xaxis=dict(title="Precio de la Tasa (VES)", dtick=2, tickformat=".1f"), yaxis_title="Volumen Disponible", barmode='group')
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    render_seccion_compra()

with col_centro:
    st.markdown('<div class="header-center">PANEL DE CONTROL & CÁLCULO</div>', unsafe_allow_html=True)
    
    @st.fragment(run_every=timedelta(seconds=4))
    def render_spread_live():
        m_c = obtener_mercado_publico("BUY", filtro_c)
        m_v = obtener_mercado_publico("SELL", filtro_v)
        p_c = float(m_c[0]['adv']['price']) if m_c else 0.0
        p_v = float(m_v[0]['adv']['price']) if m_v else 0.0
        spread_val = p_c - p_v if (p_c and p_v) else 0.0
        prof_pct = (spread_val / p_v * 100) if p_v > 0 else 0.0
        st.markdown(f'<div class="card-box" style="text-align: center;"><div style="color: #848e9c; font-size: 12px; font-weight: bold;">SPREAD ACTUAL (VES)</div><div style="font-size: 30px; font-weight: bold; color: #f0b90b; margin: 3px 0;">{spread_val:.2f}</div><div style="color: #0ecb81; font-weight: bold; font-size: 13px;">Profit +{prof_pct:.2f}%</div><div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 13px; font-weight: bold;"><span style="color: #0ecb81;">Compra: {p_c:.3f}</span><span style="color: #f6465d;">Venta: {p_v:.3f}</span></div></div>', unsafe_allow_html=True)
        st.session_state['p_compra_live'], st.session_state['p_venta_live'] = p_c, p_v
    render_spread_live()
    
    st.markdown('<div class="header-center">🧮 SIMULADOR DE OPERACIÓN</div>', unsafe_allow_html=True)
    with st.container():
        if st.button("🔄 Cargar Tasas en Vivo", use_container_width=True):
            st.session_state['calc_sr'] = float(st.session_state.get('p_compra_live', 40.0))
            st.session_state['calc_br'] = float(st.session_state.get('p_venta_live', 39.0))
        vip_nivel = st.selectbox("Nivel VIP (Comisión)", ["Sin verificar (0.25%)", "Bronce (-20%)", "Plata (-30%)", "Oro (-50%)"])
        desc = 0.0 if "Sin" in vip_nivel else (0.20 if "Bronce" in vip_nivel else (0.30 if "Plata" in vip_nivel else 0.50))
        active_fee_rate = 0.0025 * (1 - desc)
        
        c_in1, c_in2 = st.columns(2)
        with c_in1: calc_usdt = st.number_input("USDT a operar", value=capital_trabajo, step=50.0)
        with c_in2: calc_sell_rate = st.number_input("Tasa Venta", step=0.1, format="%.3f", key="calc_sr")
        calc_buy_rate = st.number_input("Tasa Compra", step=0.1, format="%.3f", key="calc_br")
        
        fiat_recibido = calc_usdt * calc_sell_rate
        usdt_recuperados = fiat_recibido / calc_buy_rate if calc_buy_rate > 0 else 0
        gross_profit = usdt_recuperados - calc_usdt
        total_fee = (calc_usdt * active_fee_rate) + (usdt_recuperados * active_fee_rate)
        net_profit_calc = gross_profit - total_fee
        
        st.markdown(f'<div style="font-size: 11px; color: #848e9c; margin-top: 6px; display: flex; justify-content: space-between;"><span>Bruta: <b style="color: #eaecef;">{gross_profit:.2f} USDT</b></span><span style="color: #f6465d;">Comisión: -{total_fee:.2f} USDT</span></div><div style="font-size: 14px; color: #2ebd85; margin-top: 4px; text-align: center; font-weight: bold;">Ganancia Neta: +{net_profit_calc:.2f} USDT</div>', unsafe_allow_html=True)
        
    st.metric(label="GANANCIA ACUMULADA DE LA SESIÓN", value=f"{st.session_state.ganancia_sesion:.2f} USDT", delta=f"Ciclos: {st.session_state.ciclos}")
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("➕ REGISTRAR", use_container_width=True):
            st.session_state.ganancia_sesion += net_profit_calc
            st.session_state.ciclos += 1
            st.rerun()
    with btn_col2:
        if st.button("🗑️ REINICIAR", use_container_width=True):
            st.session_state.ganancia_sesion = 0.0
            st.session_state.ciclos = 0
            st.rerun()

with col_venta:
    st.markdown('<div class="header-venta">VENTA</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="display: flex; justify-content: space-between; background: #161a23; padding: 6px 10px; border-radius: 4px; font-size: 13px; color: #848e9c; margin-bottom: 8px;"><span><b>BDV | TRANSF</b></span><span style="color: #f6465d; font-weight: bold;">{str_filtro_v} VES</span></div>', unsafe_allow_html=True)
    
    @st.fragment(run_every=timedelta(seconds=4))
    def render_seccion_venta():
        mis_anuncios = obtener_mis_anuncios(api_key_input, secret_key_input)
        anuncios_venta = [ad for ad in mis_anuncios if ad.get('tradeType') == 'SELL']
        if anuncios_venta:
            html_v = '<table class="p2p-table"><tr><th>NRO</th><th>PRECIO</th><th>DISP</th><th>ESTADO</th></tr>'
            for ad in anuncios_venta: html_v += f"<tr><td>{str(ad.get('adNo'))[-6:]}</td><td>{float(ad.get('price', 0)):,.3f}</td><td>{float(ad.get('surplusAmount', 0)):,.1f}</td><td>{ad.get('advStatus')}</td></tr>"
            html_v += '</table>'
            st.markdown(html_v, unsafe_allow_html=True)
        else:
            mercado_v = obtener_mercado_publico("SELL", filtro_v)
            if mercado_v:
                html_v = '<table class="p2p-table"><tr><th>#</th><th>PRECIO</th><th>DISP</th><th>USUARIO</th></tr>'
                for idx, item in enumerate(mercado_v, 1): html_v += f"<tr><td>#{idx}</td><td>{float(item['adv']['price']):,.3f}</td><td>{float(item['adv']['surplusAmount']):.1f}</td><td>{item['advertiser']['nickName'][:12]}</td></tr>"
                html_v += '</table>'
                st.markdown(html_v, unsafe_allow_html=True)
            else: st.info("Cargando mercado de venta...")
            
        st.markdown("<br>", unsafe_allow_html=True)
        ordenes_activas, error_ordenes = obtener_ordenes_activas(api_key_input, secret_key_input)
        total_usdt_activas = sum([float(o.get('amount', 0)) for o in ordenes_activas]) if ordenes_activas else 0.0
        st.markdown(f'<div style="color: #f0b90b; font-weight: bold; font-size: 15px; border-bottom: 2px solid #f0b90b; padding-bottom: 4px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;"><span>📋 MIS ÓRDENES ACTIVAS</span><span style="color: #eaecef; font-size: 12px; background: #161a23; padding: 2px 6px; border-radius: 4px;">Total: {total_usdt_activas:,.2f} USDT</span></div>', unsafe_allow_html=True)
        
        if error_ordenes:
            if error_ordenes == "Faltan credenciales": st.markdown('<div style="text-align: center; color: #848e9c; font-size: 13px; padding: 10px; background: #12161f; border-radius: 4px;">Ingresa tus API Keys.</div>', unsafe_allow_html=True)
            else: st.error(error_ordenes)
        elif ordenes_activas:
            html_o = '<table class="p2p-table"><tr><th>TIPO</th><th>FIAT</th><th>USDT</th><th>ESTADO</th></tr>'
            for o in ordenes_activas:
                is_buy = (o.get('tradeType') == 'BUY')
                tipo_color, tipo_str = ("#0ecb81", "COMPRA") if is_buy else ("#f6465d", "VENTA")
                html_o += f"<tr><td style='color: {tipo_color}; font-weight: bold;'>{tipo_str}</td><td>{float(o.get('totalPrice', 0)):,.2f} VES</td><td>{float(o.get('amount', 0)):,.2f}</td><td>{o.get('orderStatus', '')}</td></tr>"
            html_o += '</table>'
            st.markdown(html_o, unsafe_allow_html=True)
        else: st.markdown('<div style="text-align: center; color: #848e9c; font-size: 13px; padding: 10px; background: #12161f; border-radius: 4px;">No tienes órdenes activas en este momento.</div>', unsafe_allow_html=True)
    render_seccion_venta()
