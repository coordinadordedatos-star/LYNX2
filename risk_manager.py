import pandas as pd
import numpy as np

class LynxRiskEngine:
    def __init__(self):
        # 1. SSF: Sector Sensitivity Factors [Fuente: PDF Pag 3]
        self.SSF = {
            "Utilities": 0.85, "Consumer Defensive": 0.85, 
            "Healthcare": 0.95, 
            "Industrials": 1.00, "Basic Materials": 1.00, "Real Estate": 1.00,
            "Financial Services": 1.05, "Consumer Cyclical": 1.05,
            "Technology": 1.15, "Communication Services": 1.15,
            "Biotechnology": 1.25, "Energy": 1.10
        }
        
        # 2. Multiplicadores Base por Régimen VIX [Fuente: PDF Pag 3]
        self.BASE_MULT = {
            "COMPRESSION": 1.3,
            "NORMAL": 1.6,
            "EXPANSION": 2.1,
            "STRESS": 2.8
        }

        # 3. Perfiles de Swing (Dual Profile) [Fuente: PDF Pag 3-4]
        self.PROFILES = {
            "SWING_SHORT": {
                "DESC": "Corto Plazo (3-7 días)",
                "ATR_FAST": 14, 
                "ATR_SLOW": 50, 
                "EXP_MIN": 0.80, 
                "EXP_MAX": 1.60
            },
            "SWING_LONG": {
                "DESC": "Largo Plazo (2-6 semanas)",
                "ATR_FAST": 14, 
                "ATR_SLOW": 100, 
                "EXP_MIN": 0.85, 
                "EXP_MAX": 1.45
            }
        }

    def _get_vix_regime(self, vix_value):
        """Define el régimen macro basado en VIX (PDF Sección 2.1)"""
        if vix_value < 14: return "COMPRESSION"
        if vix_value < 18: return "NORMAL"
        if vix_value < 25: return "EXPANSION"
        return "STRESS"

    def _get_gamma_state_proxy(self, vix_value, spx_trend):
        """
        Aproximación de Gamma (GEX) ya que YFinance no da Call Walls.
        Lógica PDF: VIX alto (>25) o SPX cayendo fuerte suele implicar Gamma Negativa.
        """
        if vix_value >= 25: return "NEGATIVE" 
        if spx_trend == "BAJISTA": return "NEGATIVE"
        return "POSITIVE" # Asumimos positivo/neutral en mercados normales

    def _get_atr_expansion(self, df, fast_len, slow_len, exp_min, exp_max):
        """Calcula la expansión de volatilidad (ATR Fast / ATR Slow)"""
        if len(df) < slow_len: return 1.0
        
        # Calculamos ATR dinámicamente según el perfil
        high_low = df['alto'] - df['bajo']
        high_close = (df['alto'] - df['cierre'].shift()).abs()
        low_close = (df['bajo'] - df['cierre'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        atr_fast = tr.rolling(fast_len).mean().iloc[-1]
        atr_slow = tr.rolling(slow_len).mean().iloc[-1]
        
        if atr_slow == 0: return 1.0
        
        ratio = atr_fast / atr_slow
        # Clamp (limitar valores) según PDF
        return max(min(ratio, exp_max), exp_min)

    def seleccionar_perfil(self, setup_type, vix_value, gamma_state):
        """Selecciona SWING_SHORT o SWING_LONG (PDF Sección 2.4 y 4)"""
        # A) Por tipo de setup
        if setup_type in ["BREAKOUT", "TREND_CONTINUATION"]:
            return "SWING_LONG"
        if setup_type in ["MEAN_REVERSION", "PULLBACK"]:
            return "SWING_SHORT"
        
        # B) Tie-breaker por Estrés Macro
        if vix_value >= 20 or gamma_state == "NEGATIVE":
            return "SWING_LONG" # Stops más amplios en estrés
            
        return "SWING_SHORT"

    def calcular_stop_dinamico(self, df_ticker, precio_entrada, direccion, sector, vix_val, spx_trend, setup_type):
        """
        Fórmula Maestra:
        Stop_Mult = Base_Mult(VIX) * ATR_Expansion * Gamma_Factor * SSF
        """
        if df_ticker is None or df_ticker.empty: return None

        # 1. Obtener Régimen
        regime = self._get_vix_regime(vix_val)
        base_mult = self.BASE_MULT[regime]
        
        # 2. Gamma Factor (Proxy)
        gamma_state = self._get_gamma_state_proxy(vix_val, spx_trend)
        # PDF Pag 3: Negative=1.15, Neutral=1.00, Positive=0.90
        gamma_mult = 1.15 if gamma_state == "NEGATIVE" else 0.90

        # 3. Sector Sensitivity (SSF)
        # Mapeo simple de sectores de YFinance a las claves del PDF
        ssf = 1.0
        for k, v in self.SSF.items():
            if k in sector:
                ssf = v
                break

        # 4. Seleccionar Perfil
        profile_name = self.seleccionar_perfil(setup_type, vix_val, gamma_state)
        params = self.PROFILES[profile_name]

        # 5. Calcular ATR Expansion y Distancia
        atr_exp = self._get_atr_expansion(df_ticker, params['ATR_FAST'], params['ATR_SLOW'], params['EXP_MIN'], params['EXP_MAX'])
        
        # Cálculo del Multiplicador Final
        stop_multiplier = base_mult * atr_exp * gamma_mult * ssf
        
        # Distancia en Precio (Usando ATR Fast del perfil)
        # Recalculamos el ATR actual rápido para la distancia base
        high_low = df_ticker['alto'] - df_ticker['bajo']
        atr_actual = high_low.rolling(params['ATR_FAST']).mean().iloc[-1]
        
        vol_distance = atr_actual * stop_multiplier
        
        # 6. Colocación del Stop
        if direccion == "ALCISTA":
            stop_price = precio_entrada - vol_distance
        else: # BAJISTA
            stop_price = precio_entrada + vol_distance
            
        return {
            "Stop_Price": round(stop_price, 2),
            "Profile": profile_name,
            "Regime": regime,
            "Stop_Multiplier": round(stop_multiplier, 2),
            "Gamma_State": gamma_state,
            "Risk_Distance": round(vol_distance, 2)
        }