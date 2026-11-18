import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ==============================================================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILO OSCURO PROFESIONAL (BEARS TERMINAL P2P)
# ==============================================================================
st.set_page_config(
    page_title="BEARS Terminal P2P",
    page_icon="🐻",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Fondo principal y contenedores oscuros */
    .stApp {
        background-color: #0b0e14;
        color: #e6edf3;
    }
    section[data-testid="stSidebar"] {
        background-color: #11151f;
        border-right: 1px solid #1e2433;
    }
    /* Tarjetas de métricas KPI */
    div[data-testid="stMetric"] {
        background-color: #131824;
        border: 1px solid #22293a;
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    div[data-testid="stMetricLabel"] {
        color: #8b949e !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetricValue"] {
        color: #f0f6fc !important;
        font-size: 1.55rem !important;
        font-weight: 700 !important;
    }
    /* Botones de perfiles rápidos */
    div.stButton > button {
        background-color: #161c2a;
        color: #e6edf3;
        border: 1px solid #2a3347;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        border-color: #f0b90b;
        color: #f0b90b;
        background-color: #1c2436;
    }
    /* Pestañas principales */
    button[data-baseweb="tab"] {
        font-size: 1rem !important;
        font-weight: 700 !important;
        padding: 10px 20px !important;
    }
    /* Expanders */
    div[data-testid="stExpander"] {
        background-color: #131824;
        border: 1px solid #22293a;
        border-radius: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==============================================================================
# 2. INICIALIZACIÓN DE ESTADOS (SEPARADOS POR MERCADO PARA EVITAR COLISIONES)
# ==============================================================================
DEFAULT_STATES = {
    # Estados USDT-B (VES)
    "ves_monto_compra": 1000000,
    "ves_monto_venta": 1000000,
    # Estados EURO-USDT (EUR)
    "eur_monto_compra": 500,
    "eur_monto_venta": 500,
    # Credenciales opcionales
    "binance_api_key": "",
    "binance_api_secret": "",
}

for k, v in DEFAULT_STATES.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ==============================================================================
# 3. CONECTORES API BINANCE (P2P BOOK, SPOT REFERENCE & SINCRONIZACIÓN DE RELOJ)
# ==============================================================================
@st.cache_data(ttl=30)
def check_binance_server_sync() -> tuple[bool, int]:
    """Verifica sincronización de tiempo con servidores de Binance."""
    try:
        t0 = int(time.time() * 1000)
        r = requests.get("https://api.binance.com/api/v3/time", timeout=5)
        t1 = int(time.time() * 1000)
        server_time = int(r.json()["serverTime"])
        local_mid = (t0 + t1) // 2
        offset_ms = server_time - local_mid
        return True, offset_ms
    except Exception:
        return False, 0


@st.cache_data(ttl=10)
def get_spot_eur_usdt() -> float | None:
    """Obtiene el valor de 1 USDT en EUR usando el par Spot EURUSDT de Binance."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "EURUSDT"},
            timeout=5,
        )
        eur_in_usdt = float(r.json()["price"])
        return round(1.0 / eur_in_usdt, 4) if eur_in_usdt > 0 else None
    except Exception:
        return None


def fetch_p2p_orderbook(
    fiat: str,
    trade_type: str,
    trans_amount: float = 0,
    pay_types: list[str] | None = None,
    verified_only: bool = True,
    min_finish_rate: float = 85.0,
    min_orders: int = 10,
    rows: int = 15,
) -> pd.DataFrame:
    """
    Consulta el libro P2P de Binance en tiempo real.
    trade_type:
      - 'BUY'  -> Anuncios donde tú COMPRAS USDT (precio Ask)
      - 'SELL' -> Anuncios donde tú VENDES USDT (precio Bid)
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "fiat": fiat,
        "page": 1,
        "rows": rows,
        "tradeType": trade_type,
        "asset": "USDT",
        "countries": [],
        "proMerchantAds": False,
        "shieldMerchantAds": False,
        "filterType": "all",
        "periods": [],
        "additionalKycVerifyFilter": 0,
        "publisherType": "merchant" if verified_only else None,
        "payTypes": pay_types or [],
        "classifies": ["mass", "profession", "fiat_trade"],
    }
    if trans_amount and trans_amount > 0:
        payload["transAmount"] = trans_amount

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=8)
        resp.raise_for_status()
        raw_data = resp.json().get("data", [])
    except Exception:
        return pd.DataFrame()

    rows_parsed = []
    for entry in raw_data:
        adv = entry.get("adv", {})
        adv_user = entry.get("advertiser", {})

        finish_rate = round(float(adv_user.get("monthFinishRate", 0)) * 100, 1)
        order_count = int(adv_user.get("monthOrderCount", 0))

        if finish_rate < min_finish_rate or order_count < min_orders:
            continue

        methods = [
            m.get("identifier", m.get("tradeMethodName", ""))
            for m in adv.get("tradeMethods", [])
        ]

        rows_parsed.append(
            {
                "Comerciante": adv_user.get("nickName", "N/D"),
                "Precio": float(adv.get("price", 0)),
                "Disponible (USDT)": float(adv.get("surplusAmount", 0)),
                "Mínimo": float(adv.get("minSingleTransAmount", 0)),
                "Máximo": float(adv.get("dynamicMaxSingleTransAmount", 0)),
                "Órdenes (30d)": order_count,
                "Tasa (%)": finish_rate,
                "Métodos": ", ".join(methods),
            }
        )

    return pd.DataFrame(rows_parsed)


def fetch_merchant_active_ads(api_key: str, api_secret: str) -> pd.DataFrame:
    """Consulta opcional de anuncios propios si se configuran las API Keys en el sidebar."""
    if not api_key or not api_secret:
        return pd.DataFrame()
    try:
        ok, offset = check_binance_server_sync()
        ts = int(time.time() * 1000) + (offset if ok else 0)
        params = {"timestamp": ts, "recvWindow": 5000}
        query_str = urlencode(params)
        signature = hmac.new(
            api_secret.encode("utf-8"),
            query_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = f"https://api.binance.com/sapi/v1/c2c/ads/listWithPagination?{query_str}&signature={signature}"
        headers = {"X-MBX-APIKEY": api_key}
        r = requests.post(url, json={"page": 1, "rows": 10}, headers=headers, timeout=6)
        data = r.json().get("data", [])
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "Adv No": d.get("advNo"),
                    "Par": f"{d.get('asset')}/{d.get('fiatUnit')}",
                    "Tipo": d.get("tradeType"),
                    "Precio": float(d.get("price", 0)),
                    "Disponible": float(d.get("surplusAmount", 0)),
                    "Estado": "Activo" if d.get("advStatus") == 1 else "Pausado",
                }
                for d in data
            ]
        )
    except Exception:
        return pd.DataFrame()


# ==============================================================================
# 4. GRÁFICO DE PROFUNDIDAD / CURVA DE PRECIOS P2P (PLOTLY)
# ==============================================================================
def build_depth_chart(df_buy: pd.DataFrame, df_sell: pd.DataFrame, currency_symbol: str, decimals: int):
    fig = go.Figure()

    if not df_buy.empty:
        top_buy = df_buy.head(10).reset_index(drop=True)
        fig.add_trace(
            go.Scatter(
                x=list(range(1, len(top_buy) + 1)),
                y=top_buy["Precio"],
                mode="lines+markers",
                name="Compra USDT (Ask)",
                line=dict(color="#00e676", width=2.5),
                marker=dict(size=7),
                hovertemplate=f"Posición #%{x}<br>Precio: %{y:.{decimals}f} {currency_symbol}<extra></extra>",
            )
        )

    if not df_sell.empty:
        top_sell = df_sell.head(10).reset_index(drop=True)
        fig.add_trace(
            go.Scatter(
                x=list(range(1, len(top_sell) + 1)),
                y=top_sell["Precio"],
                mode="lines+markers",
                name="Venta USDT (Bid)",
                line=dict(color="#ff5252", width=2.5),
                marker=dict(size=7),
                hovertemplate=f"Posición #%{x}<br>Precio: %{y:.{decimals}f} {currency_symbol}<extra></extra>",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#131824",
        plot_bgcolor="#131824",
        height=270,
        margin=dict(l=20, r=20, t=35, b=20),
        title=dict(text="Curva de Precios Top 10 Anunciantes", font=dict(size=14, color="#e6edf3")),
        xaxis=dict(title="Posición en el Libro", gridcolor="#1f2636", dtick=1),
        yaxis=dict(title=f"Tasa ({currency_symbol})", gridcolor="#1f2636"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ==============================================================================
# 5. BARRA LATERAL (CONFIGURACIÓN GLOBAL, AUTO-REFRESCO Y API KEYS)
# ==============================================================================
with st.sidebar:
    st.markdown("## 🐻 BEARS Terminal P2P")
    st.caption("Panel Profesional de Liquidez y Arbitraje")

    # Estado de reloj con Binance
    sync_ok, offset_ms = check_binance_server_sync()
    if sync_ok:
        st.success(f"🟢 Reloj Binance OK ({offset_ms:+d} ms)")
    else:
        st.warning("🟡 Sin respuesta de /api/v3/time")

    st.divider()

    # Control Anti-Pestañeo / Auto-Refresco
    st.markdown("### ⚡ Monitoreo en Tiempo Real")
    auto_refresh = st.toggle("Auto-Refresco Activo", value=True, key="global_auto_refresh")
    refresh_seconds = st.selectbox(
        "Intervalo de actualización (seg)",
        options=[5, 10, 15, 30],
        index=1,
        disabled=not auto_refresh,
        key="global_refresh_sec",
    )
    if st.button("🔄 Actualizar Libros Ahora", use_container_width=True):
        st.cache_data.clear()

    st.divider()

    # Filtros globales de calidad
    st.markdown("### 🛡️ Filtros de Contraparte")
    solo_verificados = st.toggle("Solo Comerciantes Verificados", value=True, key="global_verified")
    min_tasa = st.slider("Tasa mínima completado (%)", 50, 100, 90, step=5, key="global_min_rate")
    min_ordenes = st.number_input("Órdenes mínimas (30d)", min_value=0, value=20, step=10, key="global_min_orders")
    filas_libro = st.slider("Anuncios por tabla", 5, 25, 15, step=5, key="global_rows")

    st.divider()

    # Credenciales API Binance (Opcional)
    with st.expander("🔑 API Keys Binance (Opcional)"):
        st.caption("Ingresa tus llaves para visualizar tus anuncios activos.")
        st.session_state.binance_api_key = st.text_input(
            "API Key", value=st.session_state.binance_api_key, type="password"
        )
        st.session_state.binance_api_secret = st.text_input(
            "API Secret", value=st.session_state.binance_api_secret, type="password"
        )


# ==============================================================================
# 6. RENDERIZADO DE PESTAÑA 1: 🇻🇪 USDT-B (SECCIÓN ORIGINAL COMPLETA)
# ==============================================================================
def render_usdt_b_section():
    st.markdown("### 🇻🇪 Mercado P2P — USDT-B (Bolívares)")

    # Perfiles rápidos de bloque VES
    st.caption("⚡ Perfiles rápidos de liquidez (Compra / Venta en Bs.):")
    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        if st.button("Bloque 1M / 1M", use_container_width=True, key="ves_btn_1m"):
            st.session_state.ves_monto_compra = 1000000
            st.session_state.ves_monto_venta = 1000000
    with b2:
        if st.button("250K / 250K", use_container_width=True, key="ves_btn_250k"):
            st.session_state.ves_monto_compra = 250000
            st.session_state.ves_monto_venta = 250000
    with b3:
        if st.button("50K / 50K", use_container_width=True, key="ves_btn_50k"):
            st.session_state.ves_monto_compra = 50000
            st.session_state.ves_monto_venta = 50000
    with b4:
        if st.button("1M Compra / 200K Venta", use_container_width=True, key="ves_btn_asym"):
            st.session_state.ves_monto_compra = 1000000
            st.session_state.ves_monto_venta = 200000
    with b5:
        if st.button("Sin Filtro (VES)", use_container_width=True, key="ves_btn_all"):
            st.session_state.ves_monto_compra = 0
            st.session_state.ves_monto_venta = 0

    # Controles manuales y bancos Venezuela
    f1, f2, f3 = st.columns([1, 1, 2.2])
    with f1:
        st.session_state.ves_monto_compra = st.number_input(
            "Filtro Compra (Bs.)",
            min_value=0,
            step=10000,
            value=int(st.session_state.ves_monto_compra),
            key="ves_input_compra",
        )
    with f2:
        st.session_state.ves_monto_venta = st.number_input(
            "Filtro Venta (Bs.)",
            min_value=0,
            step=10000,
            value=int(st.session_state.ves_monto_venta),
            key="ves_input_venta",
        )
    with f3:
        metodos_ves = st.multiselect(
            "Métodos de Pago Venezuela",
            options=["PagoMovil", "Banesco", "Mercantil", "Provincial", "Venezuela", "BNC", "Bancamiga"],
            default=["PagoMovil", "Banesco"],
            key="ves_metodos",
        )

    # Consulta de libros VES
    df_buy_ves = fetch_p2p_orderbook(
        fiat="VES",
        trade_type="BUY",
        trans_amount=st.session_state.ves_monto_compra,
        pay_types=metodos_ves,
        verified_only=solo_verificados,
        min_finish_rate=min_tasa,
        min_orders=min_ordenes,
        rows=filas_libro,
    )
    df_sell_ves = fetch_p2p_orderbook(
        fiat="VES",
        trade_type="SELL",
        trans_amount=st.session_state.ves_monto_venta,
        pay_types=metodos_ves,
        verified_only=solo_verificados,
        min_finish_rate=min_tasa,
        min_orders=min_ordenes,
        rows=filas_libro,
    )

    # Cálculo de KPIs VES
    best_buy_ves = df_buy_ves["Precio"].iloc[0] if not df_buy_ves.empty else 0.0
    best_sell_ves = df_sell_ves["Precio"].iloc[0] if not df_sell_ves.empty else 0.0
    avg3_buy_ves = df_buy_ves["Precio"].head(3).mean() if not df_buy_ves.empty else 0.0
    avg3_sell_ves = df_sell_ves["Precio"].head(3).mean() if not df_sell_ves.empty else 0.0

    spread_bs = best_buy_ves - best_sell_ves
    spread_pct_ves = ((best_buy_ves - best_sell_ves) / best_sell_ves * 100) if best_sell_ves > 0 else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        f"🟢 Mejor Compra ({st.session_state.ves_monto_compra:,.0f} Bs.)",
        f"{best_buy_ves:,.2f} Bs.",
        f"Top 3 prom: {avg3_buy_ves:,.2f} Bs.",
    )
    k2.metric(
        f"🔴 Mejor Venta ({st.session_state.ves_monto_venta:,.0f} Bs.)",
        f"{best_sell_ves:,.2f} Bs.",
        f"Top 3 prom: {avg3_sell_ves:,.2f} Bs.",
    )
    k3.metric("Spread Neto (Bs.)", f"{spread_bs:+,.2f} Bs.")
    k4.metric("Margen Bruto (%)", f"{spread_pct_ves:+.2f}%")

    # Tablas lado a lado
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown(f"#### 🟢 Comprar USDT — Filtro: `{st.session_state.ves_monto_compra:,.0f} Bs.`")
        if not df_buy_ves.empty:
            st.dataframe(
                df_buy_ves.style.format(
                    {
                        "Precio": "{:,.2f} Bs.",
                        "Disponible (USDT)": "{:,.2f}",
                        "Mínimo": "{:,.0f}",
                        "Máximo": "{:,.0f}",
                        "Tasa (%)": "{:.1f}%",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("No se encontraron anuncios de compra con estos filtros.")

    with c_right:
        st.markdown(f"#### 🔴 Vender USDT — Filtro: `{st.session_state.ves_monto_venta:,.0f} Bs.`")
        if not df_sell_ves.empty:
            st.dataframe(
                df_sell_ves.style.format(
                    {
                        "Precio": "{:,.2f} Bs.",
                        "Disponible (USDT)": "{:,.2f}",
                        "Mínimo": "{:,.0f}",
                        "Máximo": "{:,.0f}",
                        "Tasa (%)": "{:.1f}%",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("No se encontraron anuncios de venta con estos filtros.")

    # Gráfico de profundidad VES
    if not df_buy_ves.empty or not df_sell_ves.empty:
        st.plotly_chart(
            build_depth_chart(df_buy_ves, df_sell_ves, "Bs.", 2),
            use_container_width=True,
            key="chart_ves_depth",
        )

    # Simulador Avanzado de Operaciones (USDT-B)
    with st.expander("🧮 Simulador Avanzado de Operaciones — USDT-B", expanded=True):
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            cap_ves = st.number_input(
                "Capital a rotar (Bs.)",
                min_value=1000.0,
                value=float(st.session_state.ves_monto_compra if st.session_state.ves_monto_compra > 0 else 1000000.0),
                step=50000.0,
                key="sim_ves_cap",
            )
        with s2:
            tasa_in_ves = st.number_input(
                "Tasa Entrada (Bs./USDT)",
                min_value=0.01,
                value=float(best_sell_ves if best_sell_ves > 0 else 50.0),
                format="%.2f",
                key="sim_ves_in",
            )
        with s3:
            tasa_out_ves = st.number_input(
                "Tasa Salida (Bs./USDT)",
                min_value=0.01,
                value=float(best_buy_ves if best_buy_ves > 0 else 51.0),
                format="%.2f",
                key="sim_ves_out",
            )
        with s4:
            fee_ves_pct = st.number_input(
                "Comisión Maker por lado (%)",
                min_value=0.0,
                max_value=2.0,
                value=0.15,
                step=0.05,
                format="%.2f",
                key="sim_ves_fee",
            )

        fee_factor = 1.0 - (fee_ves_pct / 100.0)
        usdt_netos_ves = (cap_ves / tasa_in_ves) * fee_factor if tasa_in_ves > 0 else 0.0
        bs_finales = (usdt_netos_ves * tasa_out_ves) * fee_factor
        ganancia_bs = bs_finales - cap_ves
        roi_ves = (ganancia_bs / cap_ves * 100) if cap_ves > 0 else 0.0

        r1, r2, r3 = st.columns(3)
        r1.metric("USDT Netos Adquiridos", f"{usdt_netos_ves:,.2f} USDT")
        r2.metric("Retorno Bruto/Neto (Bs.)", f"{bs_finales:,.2f} Bs.")
        r3.metric("Ganancia Neta (Post-Comisiones)", f"{ganancia_bs:+,.2f} Bs.", f"{roi_ves:+.2f}% ROI")


# ==============================================================================
# 7. RENDERIZADO DE PESTAÑA 2: 🇪🇺 EURO-USDT (NUEVA SECCIÓN IDÉNTICA EN EUR)
# ==============================================================================
def render_euro_usdt_section():
    st.markdown("### 🇪🇺 Mercado P2P — EURO-USDT")

    # Perfiles rápidos solicitados para EURO-USDT
    st.caption("⚡ Perfiles rápidos de liquidez (Compra / Venta en EUR):")
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("500 Compra / 500 Venta", use_container_width=True, key="eur_btn_500_500"):
            st.session_state.eur_monto_compra = 500
            st.session_state.eur_monto_venta = 500
    with b2:
        if st.button("1.000 Compra / 200 Venta", use_container_width=True, key="eur_btn_1000_200"):
            st.session_state.eur_monto_compra = 1000
            st.session_state.eur_monto_venta = 200
    with b3:
        if st.button("1.000 Compra / 5.000 Venta", use_container_width=True, key="eur_btn_1000_5000"):
            st.session_state.eur_monto_compra = 1000
            st.session_state.eur_monto_venta = 5000
    with b4:
        if st.button("Sin Filtro (EUR)", use_container_width=True, key="eur_btn_all"):
            st.session_state.eur_monto_compra = 0
            st.session_state.eur_monto_venta = 0

    # Controles manuales y métodos de pago Europa / España
    f1, f2, f3 = st.columns([1, 1, 2.2])
    with f1:
        st.session_state.eur_monto_compra = st.number_input(
            "Filtro Compra (€)",
            min_value=0,
            step=100,
            value=int(st.session_state.eur_monto_compra),
            key="eur_input_compra",
        )
    with f2:
        st.session_state.eur_monto_venta = st.number_input(
            "Filtro Venta (€)",
            min_value=0,
            step=100,
            value=int(st.session_state.eur_monto_venta),
            key="eur_input_venta",
        )
    with f3:
        metodos_eur = st.multiselect(
            "Métodos de Pago Europa / España",
            options=[
                "Bizum",
                "SEPAinstant",
                "SEPA",
                "Revolut",
                "Wise",
                "BBVA",
                "Santander",
                "CaixaBank",
                "BancoSabadell",
                "ZEN",
                "Paysera",
            ],
            default=["Bizum", "SEPAinstant"],
            key="eur_metodos",
        )

    # Consulta de libros EUR y referencia Spot
    spot_eur = get_spot_eur_usdt()
    df_buy_eur = fetch_p2p_orderbook(
        fiat="EUR",
        trade_type="BUY",
        trans_amount=st.session_state.eur_monto_compra,
        pay_types=metodos_eur,
        verified_only=solo_verificados,
        min_finish_rate=min_tasa,
        min_orders=min_ordenes,
        rows=filas_libro,
    )
    df_sell_eur = fetch_p2p_orderbook(
        fiat="EUR",
        trade_type="SELL",
        trans_amount=st.session_state.eur_monto_venta,
        pay_types=metodos_eur,
        verified_only=solo_verificados,
        min_finish_rate=min_tasa,
        min_orders=min_ordenes,
        rows=filas_libro,
    )

    # Cálculo de KPIs EUR
    best_buy_eur = df_buy_eur["Precio"].iloc[0] if not df_buy_eur.empty else 0.0
    best_sell_eur = df_sell_eur["Precio"].iloc[0] if not df_sell_eur.empty else 0.0
    avg3_buy_eur = df_buy_eur["Precio"].head(3).mean() if not df_buy_eur.empty else 0.0
    avg3_sell_eur = df_sell_eur["Precio"].head(3).mean() if not df_sell_eur.empty else 0.0

    spread_eur = best_buy_eur - best_sell_eur
    spread_pct_eur = ((best_buy_eur - best_sell_eur) / best_sell_eur * 100) if best_sell_eur > 0 else 0.0
    spot_gap_pct = ((best_buy_eur - spot_eur) / spot_eur * 100) if (spot_eur and best_buy_eur > 0) else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        f"🟢 Mejor Compra ({st.session_state.eur_monto_compra:,.0f} €)",
        f"{best_buy_eur:.3f} €",
        f"Top 3 prom: {avg3_buy_eur:.3f} €",
    )
    k2.metric(
        f"🔴 Mejor Venta ({st.session_state.eur_monto_venta:,.0f} €)",
        f"{best_sell_eur:.3f} €",
        f"Top 3 prom: {avg3_sell_eur:.3f} €",
    )
    k3.metric(
        "Spread Neto (€) / Spot Ref",
        f"{spread_eur:+.4f} €",
        f"Spot: {spot_eur:.4f} € ({spot_gap_pct:+.2f}%)" if spot_eur else "Spot N/D",
    )
    k4.metric("Margen Bruto (%)", f"{spread_pct_eur:+.2f}%")

    # Tablas lado a lado EUR
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown(f"#### 🟢 Comprar USDT — Filtro: `{st.session_state.eur_monto_compra:,.0f} €`")
        if not df_buy_eur.empty:
            st.dataframe(
                df_buy_eur.style.format(
                    {
                        "Precio": "{:.3f} €",
                        "Disponible (USDT)": "{:,.2f}",
                        "Mínimo": "{:,.0f} €",
                        "Máximo": "{:,.0f} €",
                        "Tasa (%)": "{:.1f}%",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("No se encontraron anuncios de compra en EUR con estos filtros.")

    with c_right:
        st.markdown(f"#### 🔴 Vender USDT — Filtro: `{st.session_state.eur_monto_venta:,.0f} €`")
        if not df_sell_eur.empty:
            st.dataframe(
                df_sell_eur.style.format(
                    {
                        "Precio": "{:.3f} €",
                        "Disponible (USDT)": "{:,.2f}",
                        "Mínimo": "{:,.0f} €",
                        "Máximo": "{:,.0f} €",
                        "Tasa (%)": "{:.1f}%",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("No se encontraron anuncios de venta en EUR con estos filtros.")

    # Gráfico de profundidad EUR
    if not df_buy_eur.empty or not df_sell_eur.empty:
        st.plotly_chart(
            build_depth_chart(df_buy_eur, df_sell_eur, "€", 3),
            use_container_width=True,
            key="chart_eur_depth",
        )

    # Simulador Avanzado de Operaciones (EURO-USDT)
    with st.expander("🧮 Simulador Avanzado de Operaciones — EURO-USDT", expanded=True):
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            cap_eur = st.number_input(
                "Capital a rotar (€)",
                min_value=50.0,
                value=float(st.session_state.eur_monto_compra if st.session_state.eur_monto_compra > 0 else 500.0),
                step=100.0,
                key="sim_eur_cap",
            )
        with s2:
            tasa_in_eur = st.number_input(
                "Tasa Entrada (€/USDT)",
                min_value=0.001,
                value=float(best_sell_eur if best_sell_eur > 0 else 0.905),
                format="%.3f",
                key="sim_eur_in",
            )
        with s3:
            tasa_out_eur = st.number_input(
                "Tasa Salida (€/USDT)",
                min_value=0.001,
                value=float(best_buy_eur if best_buy_eur > 0 else 0.915),
                format="%.3f",
                key="sim_eur_out",
            )
        with s4:
            fee_eur_pct = st.number_input(
                "Comisión Maker por lado (%)",
                min_value=0.0,
                max_value=2.0,
                value=0.10,
                step=0.05,
                format="%.2f",
                key="sim_eur_fee",
            )

        fee_factor_eur = 1.0 - (fee_eur_pct / 100.0)
        usdt_netos_eur = (cap_eur / tasa_in_eur) * fee_factor_eur if tasa_in_eur > 0 else 0.0
        eur_finales = (usdt_netos_eur * tasa_out_eur) * fee_factor_eur
        ganancia_eur = eur_finales - cap_eur
        roi_eur = (ganancia_eur / cap_eur * 100) if cap_eur > 0 else 0.0

        r1, r2, r3 = st.columns(3)
        r1.metric("USDT Netos Adquiridos", f"{usdt_netos_eur:,.2f} USDT")
        r2.metric("Retorno Bruto/Neto (€)", f"{eur_finales:,.2f} €")
        r3.metric("Ganancia Neta (Post-Comisiones)", f"{ganancia_eur:+,.2f} €", f"{roi_eur:+.2f}% ROI")


# ==============================================================================
# 8. CUERPO PRINCIPAL CON SISTEMA ANTI-PESTAÑEO Y PESTAÑAS UNIFICADAS
# ==============================================================================
st.title("🐻 BEARS Terminal P2P")

# Panel opcional de anuncios propios si se ingresan API Keys
if st.session_state.binance_api_key and st.session_state.binance_api_secret:
    df_my_ads = fetch_merchant_active_ads(
        st.session_state.binance_api_key,
        st.session_state.binance_api_secret,
    )
    if not df_my_ads.empty:
        with st.expander("📋 Mis Anuncios Activos en Binance P2P", expanded=False):
            st.dataframe(df_my_ads, use_container_width=True, hide_index=True)


def render_terminal_workspace():
    tab_ves, tab_eur = st.tabs(["🇻🇪 USDT-B", "🇪🇺 EURO-USDT"])
    with tab_ves:
        render_usdt_b_section()
    with tab_eur:
        render_euro_usdt_section()


# Ejecución con st.fragment para evitar parpadeo de página completa al auto-refrescar
if hasattr(st, "fragment") and auto_refresh:
    @st.fragment(run_every=refresh_seconds)
    def live_terminal_fragment():
        render_terminal_workspace()

    live_terminal_fragment()
else:
    render_terminal_workspace()
