import pandas as pd
import numpy as np

class LynxAnalyzer:
    def calcular_indicadores(self, df):
        if df is None or len(df) < 200:
            return df
        
        # --- Medias Móviles ---
        df['SMA_50'] = df['cierre'].rolling(window=50).mean()
        df['SMA_200'] = df['cierre'].rolling(window=200).mean()
        df['EMA_9'] = df['cierre'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['cierre'].ewm(span=21, adjust=False).mean()

        # --- Maximos/Minimos para Breakouts ---
        df['max_20d'] = df['alto'].rolling(window=20).max()
        df['min_20d'] = df['bajo'].rolling(window=20).min()

        # --- Volatilidad (ATR) ---
        high_low = df['alto'] - df['bajo']
        high_close = (df['alto'] - df['cierre'].shift()).abs()
        low_close = (df['bajo'] - df['cierre'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['ATR'] = ranges.max(axis=1).rolling(14).mean()

        # --- RSI ---
        delta = df['cierre'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # --- MACD ---
        exp1 = df['cierre'].ewm(span=12, adjust=False).mean()
        exp2 = df['cierre'].ewm(span=26, adjust=False).mean()
        df['MACD_Line'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()

        # --- ADX (Suavizado) ---
        df['up_move'] = df['alto'] - df['alto'].shift(1)
        df['down_move'] = df['bajo'].shift(1) - df['bajo']
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
        
        df['plus_di'] = 100 * (df['plus_dm'].rolling(window=14).mean() / df['ATR'])
        df['minus_di'] = 100 * (df['minus_dm'].rolling(window=14).mean() / df['ATR'])
        df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
        df['ADX'] = df['dx'].rolling(window=14).mean()

        # --- Volumen Relativo ---
        df['Vol_Promedio'] = df['volumen'].rolling(window=20).mean()
        df['RVOL'] = df['volumen'] / df['Vol_Promedio']

        df.fillna(0, inplace=True)
        return df

    def calcular_winrate_historico(self, df, dias_proyeccion=5):
        if df is None or df.empty: return 0.0
        wins = 0
        total = 0
        start_idx = max(200, len(df) - 500) 
        
        for i in range(start_idx, len(df) - dias_proyeccion):
            row = df.iloc[i]
            futuro = df.iloc[i + dias_proyeccion]
            es_alcista = (row['EMA_9'] > row['EMA_21']) and (row['cierre'] > row['SMA_200'])
            
            if es_alcista:
                total += 1
                if futuro['cierre'] > row['cierre']: wins += 1
                
        return round((wins / total) * 100, 2) if total > 0 else 0.0

    def evaluar_signal(self, df):
        if df is None or df.empty:
            return {"tendencia": "NEUTRA", "score": 0, "razon": "Sin datos"}

        ult = df.iloc[-1]
        score = 0
        razones = []
        
        # --- FILTRO 1: ADX (Mercado Muerto) ---
        if ult['ADX'] < 15:
            return {"tendencia": "NEUTRA", "score": 0, "razon": ["Mercado Plano"], "setup_type": "NONE"}

        # 1. TENDENCIA
        if ult['EMA_9'] > ult['EMA_21']: score += 3; razones.append("EMA Alcista")
        if ult['cierre'] > ult['SMA_50']: score += 1
        if ult['cierre'] > ult['SMA_200']: score += 2; razones.append("Tendencia Alcista (Largo)")

        # 2. MOMENTUM
        if ult['MACD_Line'] > ult['MACD_Signal']: score += 2; razones.append("MACD Buy")
        
        if ult['RSI'] > 50:
            score += 1
            if ult['RSI'] > 70 and ult['RSI'] < 85:
                score += 1 
                razones.append("Momentum Fuerte")
            elif ult['RSI'] >= 85:
                score -= 2 
        
        # 3. VOLUMEN
        if ult['RVOL'] > 1.2: score += 1

        # --- Evaluación Final y CLASIFICACIÓN DE SETUP ---
        tendencia = "NEUTRA"
        calidad = "DÉBIL"
        setup_type = "MEAN_REVERSION" # Default
        
        if score >= 6: 
            tendencia = "ALCISTA"
            if score >= 8: calidad = "FUERTE"
            else: calidad = "MODERADA"
            
            # Clasificación para Risk Engine
            if ult['cierre'] >= ult['max_20d'] * 0.98: # Cerca o rompiendo maximos
                setup_type = "BREAKOUT"
            elif ult['ADX'] > 25:
                setup_type = "TREND_CONTINUATION"
            else:
                setup_type = "PULLBACK"
                
        elif score <= 2: 
            # Lógica simple bajista 
            pass

        return {
            "tendencia": tendencia,
            "calidad": calidad,
            "score": score, 
            "razon": razones,
            "RSI": round(ult['RSI'], 2),
            "MACD": round(ult['MACD_Line'], 4),
            "setup_type": setup_type # Campo clave para Dual Profile
        }