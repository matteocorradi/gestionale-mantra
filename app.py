import streamlit as st
import pandas as pd
import sqlite3
import pulp
import os

# --- COSTANTI E CONFIGURAZIONI ---
DB_NAME = "fanta_db.sqlite"
EXCEL_FILE = "lista_calciatori_lista calciatori_mantra_premier-sif-elite.xlsx"
EXCEL_CARMY = "Carmy Mantra 26_27.xlsx"

# Definizione dei moduli Mantra e dei ruoli accettati per ogni singolo slot
MODULI = {
    "3-4-3":   [['Por'], ['Dc', 'B'], ['Dc'], ['Dc', 'B'], ['E'], ['M', 'C'], ['C'], ['E'], ['W', 'A'], ['W', 'A'], ['Pc', 'A']],
    "3-4-1-2": [['Por'], ['Dc', 'B'], ['Dc'], ['Dc', 'B'], ['E'], ['M', 'C'], ['C'], ['E'], ['T'], ['Pc', 'A'], ['Pc', 'A']],
    "3-4-2-1": [['Por'], ['Dc', 'B'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M', 'C'], ['M', 'C'], ['E', 'W'], ['T', 'A'], ['T', 'A'], ['Pc', 'A']],
    "3-5-2":   [['Por'], ['Dc', 'B'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M'], ['M', 'C'], ['C'], ['E', 'W'], ['Pc', 'A'], ['Pc', 'A']],
    "3-5-1-1": [['Por'], ['Dc', 'B'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M'], ['C'], ['M'], ['E', 'W'], ['T', 'A'], ['Pc', 'A']],
    "4-3-3":   [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M', 'C'], ['M'], ['C'], ['W', 'A'], ['W', 'A'], ['Pc', 'A']],
    "4-3-1-2": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M', 'C'], ['M'], ['C'], ['T'], ['Pc', 'A'], ['Pc', 'A']],
    "4-4-2":   [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['E', 'W'], ['M', 'C'], ['C'], ['E', 'W'], ['Pc', 'A'], ['Pc', 'A']],
    "4-1-4-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M'], ['C', 'T'], ['T'], ['E', 'W'], ['W'], ['Pc', 'A']],
    "4-4-1-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['E', 'W'], ['M'], ['C'], ['E', 'W'], ['T', 'A'], ['Pc', 'A']],
    "4-2-3-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M'], ['M', 'C'], ['W', 'T'], ['T'], ['W', 'A'], ['Pc', 'A']]
}

# --- FUNZIONI DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY,
                    nome TEXT,
                    ruoli TEXT,
                    squadra TEXT,
                    fvm INTEGER,
                    fanta_media REAL,
                    titolarita INTEGER
                )''')
    conn.commit()
    conn.close()

def sync_excel_to_db():
    if not os.path.exists(EXCEL_FILE):
        st.error(f"File {EXCEL_FILE} non trovato!")
        return
    
    df = pd.read_excel(EXCEL_FILE)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    for _, row in df.iterrows():
        p_id = row['#']
        nome = row['Nome']
        ruoli = str(row['R.MANTRA'])
        squadra = str(row['FantaSquadra']) if pd.notna(row['FantaSquadra']) else ""
        fvm = row['FVM/1000'] if pd.notna(row['FVM/1000']) else 0
        
        c.execute("SELECT fanta_media, titolarita FROM players WHERE id=?", (p_id,))
        res = c.fetchone()
        
        if res:
            c.execute("UPDATE players SET ruoli=?, squadra=?, fvm=? WHERE id=?", (ruoli, squadra, fvm, p_id))
        else:
            # Di base la titolarità è settata a 3 (scala 1-5)
            c.execute("INSERT INTO players (id, nome, ruoli, squadra, fvm, fanta_media, titolarita) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                      (p_id, nome, ruoli, squadra, fvm, 6.0, 3))
    conn.commit()
    conn.close()
    st.success("Struttura base e trasferimenti sincronizzati!")

def sync_carmy_to_db():
    if not os.path.exists(EXCEL_CARMY):
        st.error(f"File {EXCEL_CARMY} non trovato!")
        return
    
    xls = pd.ExcelFile(EXCEL_CARMY)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    updated_count = 0
    # Cicla su tutti i fogli dell'excel (un foglio per ruolo)
    for sheet in xls.sheet_names:
        df = pd.read_excel(EXCEL_CARMY, sheet_name=sheet)
        for _, row in df.iterrows():
            nome = row.get('Nome')
            if pd.isna(nome): 
                continue
            
            fmv_exp = row.get('FMV Exp.', 6.0)
            titolarita = row.get('Titolarità', 1)
            
            if pd.isna(fmv_exp): fmv_exp = 6.0
            if pd.isna(titolarita): titolarita = 1
            
            # Aggiorna il giocatore corrispondente nel DB basandosi sul nome esatto
            c.execute("UPDATE players SET fanta_media=?, titolarita=? WHERE nome=?", 
                      (float(fmv_exp), int(titolarita), str(nome)))
            
            # Se ha trovato un giocatore con quel nome ed è stato modificato, incrementa il conteggio
            if c.rowcount > 0:
                updated_count += 1
                
    conn.commit()
    conn.close()
    st.success(f"Aggiornate FantaMedia e Titolarità per {updated_count} giocatori dal file di Carmy!")

# --- MOTORE DI OTTIMIZZAZIONE ---
def calcola_formazione(df_rosa, modulo_slots):
    giocatori = df_rosa.to_dict('index')
    p_ids = list(giocatori.keys())
    
    def solve_squadra(pool_ids):
        prob = pulp.LpProblem("Formazione", pulp.LpMaximize)
        x = pulp.LpVariable.dicts("x", (pool_ids, range(11)), cat='Binary')
        
        prob += pulp.lpSum(x[i][s] * (giocatori[i]['fanta_media'] * 1000 + giocatori[i]['fvm']) 
                           for i in pool_ids for s in range(11))
        
        for i in pool_ids:
            prob += pulp.lpSum(x[i][s] for s in range(11)) <= 1
            
        for s in range(11):
            prob += pulp.lpSum(x[i][s] for i in pool_ids) <= 1
            
        for i in pool_ids:
            ruoli_p = [r.strip() for r in str(giocatori[i]['ruoli']).split('/')]
            for s in range(11):
                ruoli_accettati = modulo_slots[s]
                if not set(ruoli_p).intersection(set(ruoli_accettati)):
                    prob += x[i][s] == 0
                    
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        
        schierati = []
        usati = []
        fm_tot = 0
        for s in range(11):
            trovato = False
            for i in pool_ids:
                if x[i][s].varValue == 1.0:
                    schierati.append(f"{giocatori[i]['nome']} ({giocatori[i]['ruoli']}) - {giocatori[i]['fanta_media']:.2f}")
                    fm_tot += giocatori[i]['fanta_media']
                    usati.append(i)
                    trovato = True
                    break
            if not trovato:
                schierati.append("Nessuna disponibilità (Slot Vuoto)")
        return schierati, usati, fm_tot

    tit, usati_A, fm_A = solve_squadra(p_ids)
    
    if len(usati_A) < 11:
        return None, None, 0
        
    pool_B = [p for p in p_ids if p not in usati_A]
    riserve, _, _ = solve_squadra(pool_B)
    
    return tit, riserve, fm_A

# --- INTERFACCIA WEB (STREAMLIT) ---
st.set_page_config(page_title="Mantra Manager", layout="wide")
init_db()

st.title("⚽ Gestionale FantaCalcio Mantra")

# Sincronizzazione Dati
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 1. Importa/Aggiorna Base da Lista Calciatori"):
        sync_excel_to_db()
with col2:
    if st.button("📥 2. Importa FantaMedia e Titolarità (da file Carmy)"):
        sync_carmy_to_db()

# Selezione Squadra
conn = sqlite3.connect(DB_NAME)
squadre_df = pd.read_sql("SELECT DISTINCT squadra FROM players WHERE squadra != ''", conn)
squadre_list = squadre_df['squadra'].tolist()

if squadre_list:
    mia_squadra = st.selectbox("Seleziona la tua FantaSquadra:", ["-- Seleziona --"] + squadre_list)
    
    if mia_squadra != "-- Seleziona --":
        st.divider()
        st.subheader(f"La Rosa: {mia_squadra}")
        
        # Slider Titolarità (Ora da 1 a 5)
        soglia = st.slider("Soglia Minima Titolarità per la formazione:", min_value=1, max_value=5, value=3, step=1)
        
        # Carica Rosa dal DB
        df_rosa = pd.read_sql("SELECT id, nome, ruoli, fvm, fanta_media, titolarita FROM players WHERE squadra=?", conn, params=(mia_squadra,))
        df_rosa.set_index('id', inplace=True)
        
        # --- LOGICA DI ORDINAMENTO RUOLI ---
        ruoli_ordine = ['Por', 'Dc', 'Ds', 'Dd', 'E', 'M', 'C', 'T', 'W', 'A', 'Pc']
        
        def calcola_rank_ruolo(ruoli_str):
            ruoli_singoli = [r.strip() for r in str(ruoli_str).split('/')]
            rank_minimo = 99
            for r in ruoli_singoli:
                if r.upper() == 'PC': r = 'Pc'
                if r in ruoli_ordine:
                    rank = ruoli_ordine.index(r)
                    if rank < rank_minimo:
                        rank_minimo = rank
            return rank_minimo
            
        df_rosa['rank_ordinamento'] = df_rosa['ruoli'].apply(calcola_rank_ruolo)
        df_rosa = df_rosa.sort_values(by=['rank_ordinamento', 'fvm'], ascending=[True, False])
        df_rosa = df_rosa.drop(columns=['rank_ordinamento'])
        # -----------------------------------
        
        st.write("Modifica i campi se necessario (i dati di Carmy vengono applicati al volo):")
        edited_df = st.data_editor(
            df_rosa,
            column_config={
                "nome": st.column_config.TextColumn("Nome", disabled=True),
                "ruoli": st.column_config.TextColumn("Ruoli", disabled=True),
                "fvm": st.column_config.NumberColumn("FVM", disabled=True),
                "fanta_media": st.column_config.NumberColumn("FantaMedia Attesa", format="%.2f", step=0.01),
                "titolarita": st.column_config.NumberColumn("Titolarità (1-5)", min_value=1, max_value=5, step=1)
            },
            use_container_width=True
        )
        
        if st.button("💾 Salva Modifiche Manuali"):
            c = conn.cursor()
            for p_id, row in edited_df.iterrows():
                c.execute("UPDATE players SET fanta_media=?, titolarita=? WHERE id=?", 
                          (row['fanta_media'], row['titolarita'], p_id))
            conn.commit()
            st.success("Modifiche manuali salvate!")
            
        st.divider()
        st.subheader("⚙️ Calcolo Miglior Formazione")
        
        if st.button("🚀 Calcola Moduli e Riserve"):
            with st.spinner("Ottimizzazione in corso..."):
                # Eccezione Portieri: filtrati indipendentemente dallo slider
                df_filtrato = edited_df[(edited_df['titolarita'] >= soglia) | (edited_df['ruoli'].str.contains('Por'))]
                
                risultati = []
                for nome_modulo, slots in MODULI.items():
                    titolari, riserve, fm_tot = calcola_formazione(df_filtrato, slots)
                    if titolari is not None:
                        risultati.append({
                            "modulo": nome_modulo,
                            "fm": fm_tot,
                            "titolari": titolari,
                            "riserve": riserve,
                            "slots": slots
                        })
                
                if not risultati:
                    st.warning("Nessun modulo schierabile con i giocatori a disposizione e i filtri impostati.")
                else:
                    risultati.sort(key=lambda x: x["fm"], reverse=True)
                    st.success(f"Trovati {len(risultati)} moduli validi!")
                    
                    for res in risultati:
                        with st.expander(f"🏆 {res['modulo']} - FantaMedia Totale: {res['fm']:.2f}"):
                            col_tit, col_ris = st.columns(2)
                            
                            with col_tit:
                                st.markdown("### 🟢 TITOLARI (Squadra A)")
                                for i in range(11):
                                    ruoli_richiesti = "/".join(res['slots'][i])
                                    st.write(f"**[{ruoli_richiesti}]** {res['titolari'][i]}")
                                    
                            with col_ris:
                                st.markdown("### 🟡 RISERVE (Squadra B)")
                                for i in range(11):
                                    ruoli_richiesti = "/".join(res['slots'][i])
                                    st.write(f"**[{ruoli_richiesti}]** {res['riserve'][i]}")

conn.close()
