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
    "3-4-3":   [['Por'], ['Dc'], ['Dc'], ['Dc', 'B'], ['E'], ['M', 'C'], ['C'], ['E'], ['W', 'A'], ['A', 'Pc'], ['W', 'A']],
    "3-4-1-2": [['Por'], ['Dc'], ['Dc'], ['Dc', 'B'], ['E'], ['M', 'C'], ['C'], ['E'], ['T'], ['A', 'Pc'], ['A', 'Pc']],
    "3-4-2-1": [['Por'], ['Dc'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M', 'C'], ['M', 'C'], ['E'], ['T'], ['T', 'A'], ['A', 'Pc']],
    "3-5-2":   [['Por'], ['Dc'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M', 'C'], ['M'], ['C'], ['E'], ['A', 'Pc'], ['A', 'Pc']],
    "3-5-1-1": [['Por'], ['Dc'], ['Dc'], ['Dc', 'B'], ['E', 'W'], ['M'], ['C'], ['M'], ['E', 'W'], ['T', 'A'], ['A', 'Pc']],
    "4-3-3":   [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M', 'C'], ['M'], ['C'], ['W', 'A'], ['A', 'Pc'], ['W', 'A']],
    "4-3-1-2": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M', 'C'], ['M'], ['C'], ['T'], ['T', 'A', 'Pc'], ['A', 'Pc']],
    "4-4-2":   [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['E', 'W'], ['M', 'C'], ['C'], ['E'], ['A', 'Pc'], ['A', 'Pc']],
    "4-1-4-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M'], ['C', 'T'], ['T'], ['E', 'W'], ['W'], ['A', 'Pc']],
    "4-4-1-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['E', 'W'], ['M'], ['C'], ['E', 'W'], ['T', 'A'], ['A', 'Pc']],
    "4-2-3-1": [['Por'], ['Dd', 'B'], ['Dc'], ['Dc'], ['Ds', 'B'], ['M'], ['M', 'C'], ['W', 'T'], ['T'], ['W', 'A'], ['A', 'Pc']]
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
            
            c.execute("UPDATE players SET fanta_media=?, titolarita=? WHERE nome=?", 
                      (float(fmv_exp), int(titolarita), str(nome)))
            
            if c.rowcount > 0:
                updated_count += 1
                
    conn.commit()
    conn.close()
    st.success(f"Aggiornate FantaMedia e Titolarità per {updated_count} giocatori dal file di Carmy!")

# --- MOTORE DI OTTIMIZZAZIONE ---
def calcola_formazione(df_rosa, modulo_slots):
    giocatori = df_rosa.to_dict('index')
    
    def solve_squadra(pool_ids, is_squadra_c=False):
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
                    player_str = f"{giocatori[i]['nome']} ({giocatori[i]['ruoli']}) - {giocatori[i]['fanta_media']:.2f}"
                    
                    # Evidenzia in rosso se è nella Squadra C e ha titolarità 1
                    if is_squadra_c and giocatori[i]['titolarita'] == 1:
                        player_str = f":red[{player_str} (Tit. 1)]"
                        
                    schierati.append(player_str)
                    fm_tot += giocatori[i]['fanta_media']
                    usati.append(i)
                    trovato = True
                    break
            if not trovato:
                schierati.append("Nessuna disponibilità")
        return schierati, usati, fm_tot

    # Filtro Squadra A: Titolarità >= 3 OPPURE è un portiere
    pool_A = [i for i, d in giocatori.items() if d['titolarita'] >= 3 or 'Por' in str(d['ruoli'])]
    tit_A, usati_A, fm_A = solve_squadra(pool_A)
    
    # Se i titolari non sono sufficienti per coprire il modulo, lo scartiamo
    if len(usati_A) < 11:
        return None
        
    # Filtro Squadra B: Non usati in A, Titolarità >= 2 OPPURE portiere
    pool_B = [i for i, d in giocatori.items() if i not in usati_A and (d['titolarita'] >= 2 or 'Por' in str(d['ruoli']))]
    tit_B, usati_B, _ = solve_squadra(pool_B)
    
    # Filtro Squadra C: Tutti quelli non usati in A e B
    pool_C = [i for i in giocatori.keys() if i not in usati_A and i not in usati_B]
    tit_C, usati_C, _ = solve_squadra(pool_C, is_squadra_c=True)
    
    # Esuberi: Quelli rimasti fuori da tutte le tre formazioni
    usati_tutti = set(usati_A + usati_B + usati_C)
    esuberi = [f"{d['nome']} ({d['ruoli']})" for i, d in giocatori.items() if i not in usati_tutti]
    
    return {
        "tit_A": tit_A,
        "tit_B": tit_B,
        "tit_C": tit_C,
        "esuberi": esuberi,
        "fm_A": fm_A
    }

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

conn = sqlite3.connect(DB_NAME)
squadre_df = pd.read_sql("SELECT DISTINCT squadra FROM players WHERE squadra != ''", conn)
squadre_list = squadre_df['squadra'].tolist()

if squadre_list:
    mia_squadra = st.selectbox("Seleziona la tua FantaSquadra:", ["-- Seleziona --"] + squadre_list)
    
    if mia_squadra != "-- Seleziona --":
        st.divider()
        st.subheader(f"La Rosa: {mia_squadra}")
        
        # Carica Rosa dal DB
        df_rosa = pd.read_sql("SELECT id, nome, ruoli, fvm, fanta_media, titolarita FROM players WHERE squadra=?", conn, params=(mia_squadra,))
        df_rosa.set_index('id', inplace=True)
        
        # Svincolo Veloce
        with st.container():
            col_testo, col_select, col_btn = st.columns([2, 3, 2])
            with col_testo:
                st.write("🗑️ **Svincola un calciatore:**")
            with col_select:
                nomi_rosa_ordinati = sorted(df_rosa['nome'].tolist())
                giocatore_da_svincolare = st.selectbox("Seleziona giocatore", ["-- Nessuno --"] + nomi_rosa_ordinati, label_visibility="collapsed")
            with col_btn:
                if st.button("Svincola", type="primary") and giocatore_da_svincolare != "-- Nessuno --":
                    c = conn.cursor()
                    # Rimuoviamo il giocatore dalla squadra invece di eliminarlo, così se viene ri-comprato i dati storici restano
                    c.execute("UPDATE players SET squadra='' WHERE nome=? AND squadra=?", (giocatore_da_svincolare, mia_squadra))
                    conn.commit()
                    st.rerun()

        # Ordinamento per Ruoli e FVM
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
        
        # Griglia Dati
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
        
        if st.button("🚀 Calcola Moduli"):
            with st.spinner("Calcolo combinazioni in corso..."):
                risultati = []
                for nome_modulo, slots in MODULI.items():
                    res = calcola_formazione(edited_df, slots)
                    if res is not None:
                        risultati.append({
                            "modulo": nome_modulo,
                            "fm": res["fm_A"],
                            "titolari": res["tit_A"],
                            "riserve": res["tit_B"],
                            "squadra_c": res["tit_C"],
                            "esuberi": res["esuberi"],
                            "slots": slots
                        })
                
                if not risultati:
                    st.warning("Nessun modulo schierabile con i giocatori a disposizione (Titolarità >= 3 richiesta per i titolari).")
                else:
                    risultati.sort(key=lambda x: x["fm"], reverse=True)
                    st.success(f"Trovati {len(risultati)} moduli validi!")
                    
                    for res in risultati:
                        with st.expander(f"🏆 {res['modulo']} - FantaMedia Totale Squadra A: {res['fm']:.2f}"):
                            # Divide lo spazio in 4 colonne per far stare tutto ordinatamente
                            col_A, col_B, col_C, col_Esub = st.columns(4)
                            
                            with col_A:
                                st.markdown("### 🟢 SQUADRA A")
                                for i in range(11):
                                    ruoli_richiesti = "/".join(res['slots'][i])
                                    st.write(f"**[{ruoli_richiesti}]** {res['titolari'][i]}")
                                    
                            with col_B:
                                st.markdown("### 🟡 SQUADRA B")
                                for i in range(11):
                                    ruoli_richiesti = "/".join(res['slots'][i])
                                    st.write(f"**[{ruoli_richiesti}]** {res['riserve'][i]}")

                            with col_C:
                                st.markdown("### 🟠 SQUADRA C")
                                for i in range(11):
                                    ruoli_richiesti = "/".join(res['slots'][i])
                                    st.write(f"**[{ruoli_richiesti}]** {res['squadra_c'][i]}")
                                    
                            with col_Esub:
                                st.markdown("### ⚪ ESUBERI")
                                if res['esuberi']:
                                    for esub in res['esuberi']:
                                        st.write(f"• {esub}")
                                else:
                                    st.write("Nessun esubero")

conn.close()
