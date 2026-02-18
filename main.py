import pandas as pd
import time
import schedule
import requests
import pytz
import os
from datetime import datetime
from data_loader import LynxDataLoader
from signal_analyzer import LynxAnalyzer
from options_manager import LynxOptionsManager
from risk_manager import LynxRiskEngine # Nuevo Módulo

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = "8552850614:AAEX3r6YO6SVnFRM30VjefPQ2uYRBslgW-c" 
TELEGRAM_CHAT_ID = "664346205" 

# Configuración de Zona Horaria (Eastern Time)
TZ_NY = pytz.timezone('US/Eastern')

def get_ny_time():
    return datetime.now(TZ_NY)

def get_market_status():
    """Detecta sesión de mercado basado en hora NY"""
    now = get_ny_time()
    current_time = now.time()
    
    # Horarios (Formato 24h)
    pre_start = datetime.strptime("04:00", "%H:%M").time()
    market_open = datetime.strptime("09:30", "%H:%M").time()
    market_close = datetime.strptime("16:00", "%H:%M").time()
    post_end = datetime.strptime("20:00", "%H:%M").time()

    if pre_start <= current_time < market_open: return "PRE-MARKET"
    elif market_open <= current_time < market_close: return "OPEN"
    elif market_close <= current_time < post_end: return "AFTER-HOURS"
    else: return "CLOSED"

def enviar_telegram(mensaje):
    if "TU_TOKEN" in TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, data=payload)
    except: pass

class LynxEngine:
    def __init__(self, tickers, perfil="moderado"):
        self.tickers = tickers
        self.perfil = perfil
        self.loader = LynxDataLoader()
        self.analyzer = LynxAnalyzer()
        self.opt_manager = LynxOptionsManager(self.loader)
        self.risk_engine = LynxRiskEngine() # Instancia del motor de riesgo
        
        if not os.path.exists("reportes"): os.makedirs("reportes")
        
        print(f"--- Lynx Engine v2.5 (Dual-Profile Risk) ---")

    def generar_excel(self, resultados, session_name):
        if not resultados: return
        
        timestamp_str = get_ny_time().strftime("%m-%d-%Y_%H%M")
        filename = f"reportes/Lynx_Señales_{timestamp_str}_{session_name}.xlsx"
        
        df_res = pd.DataFrame(resultados)
        
        col_order = ['Ticker', 'Precio', 'Tendencia', 'Calidad', 'Score', 'RSI', 'Estrategia', 'SL', 'TP1', 'Risk_Profile', 'Regime']
        for col in col_order:
            if col not in df_res.columns: df_res[col] = "-"
            
        with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
            df_res[col_order].to_excel(writer, sheet_name='Señales', index=False)
            print(f"📁 Reporte Excel generado: {filename}")

    def ejecutar_analisis(self):
        status = get_market_status()
        print(f"\n[{get_ny_time().strftime('%m/%d/%Y %H:%M:%S')} ET] Status: {status}")
        
        if status == "CLOSED" and self.perfil != "agresivo":
            print("Mercado cerrado. Saltando escaneo.")
            return

        # 1. OBTENER DATOS MACRO (Una vez por ciclo)
        macro_data = self.loader.obtener_datos_macro()
        if not macro_data:
            print("⚠️ Falla en datos Macro (VIX/SPX). Usando valores neutros.")
            macro_data = {"VIX": 20.0, "SPX_Trend": "ALCISTA"}
        
        print(f"🌍 Macro Regime: VIX={macro_data['VIX']:.2f} | SPX={macro_data['SPX_Trend']}")

        resultados_excel = []

        for ticker in self.tickers:
            # 2. Datos Ticker y Sector
            df = self.loader.obtener_historial(ticker)
            precio = self.loader.obtener_precio_actual(ticker)
            info_ticker = self.loader.obtener_info_ticker(ticker) # Sector y Beta
            
            if df is None: continue

            # 3. Análisis Técnico
            df = self.analyzer.calcular_indicadores(df)
            senal = self.analyzer.evaluar_signal(df)
            winrate = self.analyzer.calcular_winrate_historico(df)

            # 4. GESTIÓN DE RIESGO AVANZADA (PDF Logic)
            # Calculamos el Stop dinámico usando el motor nuevo
            datos_riesgo = self.risk_engine.calcular_stop_dinamico(
                df_ticker=df,
                precio_entrada=precio,
                direccion=senal['tendencia'],
                sector=info_ticker['sector'],
                vix_val=macro_data['VIX'],
                spx_trend=macro_data['SPX_Trend'],
                setup_type=senal['setup_type']
            )

            # Cálculo de TPs basado en la distancia del nuevo Stop
            sl_precio = datos_riesgo['Stop_Price']
            risk_dist = datos_riesgo['Risk_Distance']
            
            if senal['tendencia'] == "ALCISTA":
                tp1 = precio + (risk_dist * 1.5)
                tp3 = precio + (risk_dist * 3.0)
            else:
                tp1 = precio - (risk_dist * 1.5)
                tp3 = precio - (risk_dist * 3.0)

            niveles = {"SL": sl_precio, "TP1": round(tp1, 2), "TP3": round(tp3, 2), "RR_Ratio": 1.5}

            # 5. Opciones
            estrat_txt = "Spot / N/A"
            estrat_obj = None
            try:
                estrat_obj = self.opt_manager.seleccionar_estrategia(ticker, precio, senal['tendencia'], self.perfil)
                if estrat_obj:
                    estrat_txt = f"{estrat_obj['Nombre']} (Exp: {estrat_obj['Expiracion']})"
            except: pass

            # 6. Filtros y Alertas
            min_score = 7 if status == "OPEN" else 9
            if senal['score'] >= min_score and winrate >= 45:
                
                self.enviar_alerta_vip(ticker, precio, senal, winrate, niveles, estrat_obj, datos_riesgo)
                print(f"✅ Signal: {ticker} ({senal['calidad']}) | {datos_riesgo['Profile']}")
                
                resultados_excel.append({
                    "Ticker": ticker,
                    "Precio": precio,
                    "Tendencia": senal['tendencia'],
                    "Calidad": senal['calidad'],
                    "Score": senal['score'],
                    "RSI": senal['RSI'],
                    "Estrategia": estrat_txt,
                    "SL": niveles['SL'],
                    "TP1": niveles['TP1'],
                    "Risk_Profile": datos_riesgo['Profile'],
                    "Regime": datos_riesgo['Regime']
                })
        
        self.generar_excel(resultados_excel, status)

    def enviar_alerta_vip(self, ticker, precio, senal, winrate, niveles, estrat, risk_data):
        icono = "🟢 BUY" if "ALCISTA" in senal['tendencia'] else "🔴 SELL"
        estrat_msg = ""
        if estrat:
            legs_str = "\n".join([f"  └ {leg}" for leg in estrat['Legs']])
            estrat_msg = f"📜 **Estrategia:** {estrat['Nombre']}\n**Exp:** {estrat['Expiracion']}\n{legs_str}\n"

        # Mensaje con detalles del PDF (Profile y Regime)
        msg = (
            f"{icono} **#{ticker}** ({senal['calidad']})\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"💰 **Precio:** ${precio:.2f}\n"
            f"📊 **Winrate:** {winrate}% | **Score:** {senal['score']}/15\n"
            f"🏗 **Setup:** {senal['setup_type']}\n\n"
            
            f"🛡 **Smart Stop:** ${niveles['SL']}\n"
            f"   ├ Profile: {risk_data['Profile'].replace('SWING_', '')}\n"
            f"   ├ Regime: {risk_data['Regime']} (Mult: {risk_data['Stop_Multiplier']}x)\n"
            f"   └ Gamma: {risk_data['Gamma_State']}\n\n"
            
            f"🎯 **TP 1:** ${niveles['TP1']} (1.5R)\n"
            f"🎯 **TP 3:** ${niveles['TP3']} (3.0R)\n\n"
            
            f"{estrat_msg}\n"
            f"⏰ *{get_ny_time().strftime('%m/%d/%Y %H:%M')} ET*"
        )
        enviar_telegram(msg)

# --- AUTOMATIZACIÓN ---
def trabajo_programado():
    ACTIVOS = [
        "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", # Tech
        "SPY", "QQQ", "IWM", # ETFs
        "GC=F", "CL=F", "BTC-USD", "ETH-USD" # Futuros/Cripto
    ]
    
    status = get_market_status()
    perfil_dinamico = "agresivo" if status == "OPEN" else "conservador"
    
    bot = LynxEngine(ACTIVOS, perfil=perfil_dinamico)
    bot.ejecutar_analisis()

if __name__ == "__main__":
    print("--- SISTEMA LYNX 2.5 (ET TIMEZONE) ---")
    
    # Horarios ET
    schedule.every().day.at("09:35").do(trabajo_programado) # Open
    schedule.every().day.at("12:00").do(trabajo_programado) # Mid-day
    schedule.every().day.at("15:45").do(trabajo_programado) # Close check
    
    # Ejecución inmediata para prueba
    trabajo_programado()
    
    while True:
        schedule.run_pending()
        time.sleep(60)