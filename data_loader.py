import yfinance as yf
import pandas as pd
import logging

class LynxDataLoader:
    def __init__(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("Lynx.Data")

    def obtener_historial(self, ticker, periodo="2y"): # Aumentado a 2y para ATR Slow 100
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=periodo, auto_adjust=True)
            if df.empty:
                self.logger.warning(f"No hay datos para {ticker}")
                return None
            df = df.reset_index()
            # Estandarizar nombres
            df.rename(columns={"Date": "fecha", "Close": "cierre", "Volume": "volumen", "High": "alto", "Low": "bajo", "Open": "apertura"}, inplace=True)
            return df
        except Exception as e:
            self.logger.error(f"Error en historial {ticker}: {e}")
            return None

    def obtener_precio_actual(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            return stock.fast_info.last_price
        except:
            return 0.0
            
    def obtener_info_ticker(self, ticker):
        """Obtiene sector para el cálculo de SSF"""
        try:
            tk = yf.Ticker(ticker)
            info = tk.info
            return {
                "sector": info.get('sector', 'Industrials'), 
                "industry": info.get('industry', ''),
                "beta": info.get('beta', 1.0)
            }
        except:
            return {"sector": "Industrials", "beta": 1.0}

    def obtener_datos_macro(self):
        """Descarga VIX y SPX para determinar régimen de mercado"""
        try:
            # VIX para volatilidad implícita
            vix = yf.Ticker("^VIX").history(period="5d")
            # SPX para tendencia general (Proxy de Gamma)
            spx = yf.Ticker("^GSPC").history(period="10d")
            
            if vix.empty or spx.empty: 
                return None
            
            # Determinar tendencia de SPX (Simple: Precio sobre media de 5 días)
            spx_trend = "ALCISTA" if spx['Close'].iloc[-1] > spx['Close'].mean() else "BAJISTA"
            
            return {
                "VIX": vix['Close'].iloc[-1],
                "SPX_Trend": spx_trend
            }
        except Exception as e:
            self.logger.error(f"Error macro data: {e}")
            return None

    def obtener_cadenas_opciones(self, ticker):
        return yf.Ticker(ticker)