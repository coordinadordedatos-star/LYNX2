import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy.stats import norm
import logging

class LynxOptionsManager:
    def __init__(self, data_loader):
        self.loader = data_loader
        self.logger = logging.getLogger("Lynx.Options")
        self.rf_rate = 0.045 

    def _get_expiration(self, exps, days_target):
        target_date = datetime.now() + timedelta(days=days_target)
        # Buscar la fecha más cercana pero que no sea hoy
        valid_exps = [e for e in exps if (datetime.strptime(e, "%Y-%m-%d") - datetime.now()).days > 3]
        if not valid_exps: return None
        return min(valid_exps, key=lambda x: abs((datetime.strptime(x, "%Y-%m-%d") - target_date).days))

    def _filter_chain(self, chain_df, min_vol=10, min_oi=50):
        return chain_df[(chain_df['volume'] >= min_vol) & (chain_df['openInterest'] >= min_oi)].copy()

    def seleccionar_estrategia(self, ticker, precio_spot, tendencia, perfil="moderado"):
        """
        Selecciona Call/Put simple o Spreads según el perfil.
        Devuelve un diccionario con la estructura de la estrategia.
        """
        yf_tk = self.loader.obtener_cadenas_opciones(ticker)
        try:
            exps = yf_tk.options
            if not exps: return None
        except: return None

        # Configuración según perfil
        if perfil == "agresivo":
            dias_obj = 14
            tipo_est = "SIMPLE" # Compra directa Call/Put
        elif perfil == "moderado":
            dias_obj = 30
            tipo_est = "SPREAD_VERTICAL" # Bull Call / Bear Put Spread
        else: # Conservador
            dias_obj = 45
            tipo_est = "SPREAD_CREDITO" # Venta de riesgo limitado

        exp_date = self._get_expiration(exps, dias_obj)
        if not exp_date: return None

        try:
            chain = yf_tk.option_chain(exp_date)
            calls = self._filter_chain(chain.calls)
            puts = self._filter_chain(chain.puts)
        except: return None

        estrategia = {}

        # --- Lógica de Selección ---
        if tendencia == "ALCISTA":
            if tipo_est == "SIMPLE":
                # Buy Call (Delta ~0.50 ATM)
                leg1 = self._find_contract(calls, precio_spot, delta_target=0.50)
                if leg1: estrategia = {"Nombre": "LONG CALL", "Legs": [f"Buy {leg1['contractSymbol']} (Strike {leg1['strike']})"]}

            elif tipo_est == "SPREAD_VERTICAL":
                # Bull Call Spread: Buy ATM Call / Sell OTM Call
                buy_leg = self._find_contract(calls, precio_spot, delta_target=0.55) # ITM/ATM
                sell_leg = self._find_contract(calls, precio_spot * 1.05, delta_target=0.30) # OTM
                if buy_leg and sell_leg:
                    estrategia = {
                        "Nombre": "BULL CALL SPREAD",
                        "Legs": [f"🟢 Buy {buy_leg['strike']} Call", f"🔴 Sell {sell_leg['strike']} Call"],
                        "Costo_Est": f"Debit Spread (Max Profit: {sell_leg['strike'] - buy_leg['strike']})"
                    }

            elif tipo_est == "SPREAD_CREDITO":
                # Bull Put Spread (Credit): Sell OTM Put / Buy Further OTM Put
                sell_leg = self._find_contract(puts, precio_spot * 0.95, delta_target=0.30) # OTM
                buy_leg = self._find_contract(puts, precio_spot * 0.90, delta_target=0.15) # Far OTM
                if sell_leg and buy_leg:
                    estrategia = {
                        "Nombre": "BULL PUT SPREAD (Credit)",
                        "Legs": [f"🔴 Sell {sell_leg['strike']} Put", f"🟢 Buy {buy_leg['strike']} Put"],
                        "Nota": "Ingreso de Crédito (Bullish/Neutral)"
                    }

        elif tendencia == "BAJISTA":
             # Lógica espejo para PUTs...
             # Para brevedad del ejemplo, implemento SIMPLE
             leg1 = self._find_contract(puts, precio_spot, delta_target=-0.50)
             if leg1: estrategia = {"Nombre": "LONG PUT", "Legs": [f"Buy {leg1['contractSymbol']} (Strike {leg1['strike']})"]}

        if not estrategia: return None
        estrategia['Expiracion'] = datetime.strptime(exp_date, "%Y-%m-%d").strftime("%m/%d/%Y")
        return estrategia

    def _find_contract(self, df, price_target, delta_target=None):
        """Busca el strike más cercano al precio objetivo"""
        if df.empty: return None
        # Simplificación: Busca strike más cercano al precio target
        best = df.iloc[(df['strike'] - price_target).abs().argsort()[:1]]
        return best.iloc[0] if not best.empty else None