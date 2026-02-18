import pandas as pd
import numpy as np
import yfinance as yf
from datetime import timedelta
from signal_analyzer import LynxAnalyzer

# Configuración
CAPITAL_INICIAL = 10000
RIESGO_POR_OPERACION = 0.02  # 2% del capital por trade
TICKERS = ["AAPL", "NVDA", "TSLA", "BTC-USD", "ETH-USD", "AMD", "MSFT"]

class LynxBacktester:
    def __init__(self):
        self.analyzer = LynxAnalyzer()
        self.log_operaciones = []

    def obtener_datos_2025(self, ticker):
        """Descarga datos desde 2024 para tener indicadores listos el 1 de Enero de 2025"""
        print(f"📥 Descargando datos para {ticker}...")
        try:
            # Bajamos desde mid-2024 para que la SMA_200 tenga datos suficientes
            df = yf.Ticker(ticker).history(start="2024-01-01", end="2026-01-01", interval="1d")
            if df.empty: return None
            
            df = df.reset_index()
            # Estandarizar nombres al español como usa tu bot
            df.rename(columns={
                "Date": "fecha", "Close": "cierre", "Volume": "volumen", 
                "High": "alto", "Low": "bajo", "Open": "apertura"
            }, inplace=True)
            
            # Asegurar que las fechas no tengan zona horaria para filtrar fácil
            df['fecha'] = df['fecha'].dt.tz_localize(None)
            return df
        except Exception as e:
            print(f"Error descargando {ticker}: {e}")
            return None

    def ejecutar_test(self):
        print(f"--- INICIANDO BACKTEST 2025 (Capital: ${CAPITAL_INICIAL}) ---")
        
        balance = CAPITAL_INICIAL
        equity_curve = []
        
        for ticker in TICKERS:
            df = self.obtener_datos_2025(ticker)
            if df is None: continue

            # 1. Calcular Indicadores sobre TODO el historial
            df = self.analyzer.calcular_indicadores(df)

            # 2. Filtrar solo el año 2025 para la simulación
            df_2025 = df[(df['fecha'] >= "2025-01-01") & (df['fecha'] <= "2025-12-31")].copy()
            
            if df_2025.empty:
                print(f"⚠️ No hay datos 2025 para {ticker}")
                continue

            operacion_activa = None # Solo una operación a la vez por ticker

            # 3. Iterar día por día
            for i in range(len(df_2025)):
                idx_actual = df_2025.index[i]
                
                # Necesitamos pasar al analyzer los datos HASTA el día de hoy
                # Para ser eficientes, ya tenemos los indicadores calculados,
                # así que pasamos un slice del DF original hasta el índice actual
                df_slice = df.loc[:idx_actual]
                
                # Datos del día (supongamos que operamos al Cierre o validamos al final del día)
                vela_hoy = df.loc[idx_actual]
                precio_cierre = vela_hoy['cierre']
                fecha_hoy = vela_hoy['fecha']

                # --- GESTIÓN DE SALIDA (Si hay operación abierta) ---
                if operacion_activa:
                    sl = operacion_activa['SL']
                    tp = operacion_activa['TP1']
                    entrada = operacion_activa['precio_entrada']
                    tipo = operacion_activa['tipo'] # ALCISTA o BAJISTA
                    
                    resultado = 0
                    cerrar = False
                    
                    # Verificamos Low/High del día para ver si tocó SL o TP
                    if tipo == "ALCISTA":
                        if vela_hoy['bajo'] <= sl: # Toco Stop Loss
                            resultado = -1 * (operacion_activa['riesgo_usd'])
                            motivo = "Stop Loss"
                            cerrar = True
                        elif vela_hoy['alto'] >= tp: # Toco Take Profit
                            # Calculamos ganancia basada en Ratio (ej: si arriesgué 100 y RR es 1.5, gano 150)
                            ratio = (tp - entrada) / (entrada - sl)
                            resultado = operacion_activa['riesgo_usd'] * ratio
                            motivo = "Take Profit 1"
                            cerrar = True
                    
                    elif tipo == "BAJISTA": # SHORT
                        if vela_hoy['alto'] >= sl:
                            resultado = -1 * (operacion_activa['riesgo_usd'])
                            motivo = "Stop Loss"
                            cerrar = True
                        elif vela_hoy['bajo'] <= tp:
                            ratio = (entrada - tp) / (sl - entrada)
                            resultado = operacion_activa['riesgo_usd'] * ratio
                            motivo = "Take Profit 1"
                            cerrar = True

                    if cerrar:
                        balance += resultado
                        operacion_activa['salida'] = resultado
                        operacion_activa['fecha_salida'] = fecha_hoy
                        operacion_activa['motivo'] = motivo
                        self.log_operaciones.append(operacion_activa)
                        operacion_activa = None
                        continue # Si cerramos, no abrimos otra el mismo día

                # --- BÚSQUEDA DE ENTRADA ---
                # Evaluamos señal con la lógica de tu bot
                senal = self.analyzer.evaluar_signal(df_slice)
                
                # Filtros del Backtest (Score alto para entrar)
                if senal['score'] >= 6 and operacion_activa is None:
                    # Calcular niveles
                    niveles = self.analyzer.calcular_niveles_salida(precio_cierre, senal['tendencia'], vela_hoy['ATR'])
                    
                    # Gestión de Riesgo
                    riesgo_usd = balance * RIESGO_POR_OPERACION
                    
                    operacion_activa = {
                        "ticker": ticker,
                        "fecha_entrada": fecha_hoy,
                        "tipo": senal['tendencia'],
                        "precio_entrada": precio_cierre,
                        "SL": niveles['SL'],
                        "TP1": niveles['TP1'],
                        "score": senal['score'],
                        "riesgo_usd": riesgo_usd,
                        "salida": 0 # Pendiente
                    }

        # --- REPORTE FINAL ---
        self.generar_reporte(balance)

    def generar_reporte(self, balance_final):
        if not self.log_operaciones:
            print("No se generaron operaciones.")
            return

        df_ops = pd.DataFrame(self.log_operaciones)
        
        wins = df_ops[df_ops['salida'] > 0]
        losses = df_ops[df_ops['salida'] <= 0]
        
        winrate = (len(wins) / len(df_ops)) * 100
        total_pnl = balance_final - CAPITAL_INICIAL
        roi = (total_pnl / CAPITAL_INICIAL) * 100
        
        print("\n" + "="*40)
        print(f"📊 RESULTADOS BACKTEST 2025")
        print("="*40)
        print(f"💰 Capital Final: ${balance_final:,.2f}")
        print(f"🚀 ROI Total: {roi:.2f}%")
        print(f"✅ Winrate: {winrate:.2f}%")
        print(f"🔢 Total Operaciones: {len(df_ops)}")
        print(f"🟢 Ganadoras: {len(wins)} | 🔴 Perdedoras: {len(losses)}")
        print(f"🏆 Mejor Trade: ${df_ops['salida'].max():.2f}")
        print(f"💀 Peor Trade: ${df_ops['salida'].min():.2f}")
        print("="*40)
        
        # Exportar a Excel
        df_ops.to_excel("reportes/Backtest_Resultados_2025.xlsx", index=False)
        print("📁 Detalle guardado en 'reportes/Backtest_Resultados_2025.xlsx'")

if __name__ == "__main__":
    tester = LynxBacktester()
    tester.ejecutar_test()