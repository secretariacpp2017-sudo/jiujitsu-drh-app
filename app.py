import streamlit as st
import pandas as pd
from datetime import date
import hashlib
from supabase import create_client, Client

st.set_page_config(
    page_title="Jiu-Jitsu DRH / PMMG",
    page_icon="🥋",
    layout="wide"
)

# --- CREDENCIAIS DO SUPABASE ---
SUPABASE_URL = "https://avrbcdqniodrfwhbflsf.supabase.co"
SUPABASE_KEY = "sb_publishable_ynBzUyKq2VmfnmfFjwGSrg_bGwZBAmd"

@st.cache_resource
def obter_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = obter_supabase()

SENHA_PADRAO_INICIAL = "pmmg123"

def gerar_hash(senha: str) -> str:
    """Gera hash SHA-256 para armazenamento seguro de senhas."""
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()

# --- LINKS DA PLANILHA GOOGLE ---
URLS = {
    "cadastro": "https://docs.google.com/spreadsheets/d/e/2PACX-1vSigOP3IOPLpSCZieNHkumi_eMwGXjEfqsP9XpZ6GcvvcXhGqV8Kj94qU_V45sfZLpgL-Ifo9u6Sf3X/pub?gid=924397416&single=true&output=csv",
    "frequencia": "https://docs.google.com/spreadsheets/d/e/2PACX-1vSigOP3IOPLpSCZieNHkumi_eMwGXjEfqsP9XpZ6GcvvcXhGqV8Kj94qU_V45sfZLpgL-Ifo9u6Sf3X/pub?gid=1517915604&single=true&output=csv",
    "diario": "https://docs.google.com/spreadsheets/d/e/2PACX-1vSigOP3IOPLpSCZieNHkumi_eMwGXjEfqsP9XpZ6GcvvcXhGqV8Kj94qU_V45sfZLpgL-Ifo9u6Sf3X/pub?gid=146821828&single=true&output=csv"
}

@st.cache_data(ttl=60)
def carregar_dados_planilha():
    try:
        df_cad = pd.read_csv(URLS["cadastro"])
        df_cad.columns = df_cad.columns.astype(str).str.strip()
        
        df_freq = pd.read_csv(URLS["frequencia"], header=1)
        df_freq.columns = df_freq.columns.astype(str).str.strip()
        df_freq = df_freq.dropna(how="all")
        
        df_diario = pd.read_csv(URLS["diario"])
        df_diario.columns = df_diario.columns.astype(str).str.strip()
        df_diario = df_diario.dropna(subset=[df_diario.columns[0]])
        
        return df_cad, df_freq, df_diario
    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def localizar_coluna(df, termos):
    for termo in termos:
        for c in df.columns:
            if termo.upper() in c.upper():
                return c
    return None

def normalizar_num_policia(val: str) -> str:
    """Remove caracteres especiais deixando apenas os dígitos para busca segura."""
    return "".join(filter(str.isdigit, str(val)))

def sincronizar_efetivo_usuarios(df_cad):
    """Garante que todo militar ativo na planilha exista na tabela de usuários do Supabase."""
    if df_cad.empty:
        return
    try:
        resp_users = supabase.table("usuarios").select("numero_policia").execute()
        existentes_raw = [u["numero_policia"] for u in resp_users.data] if resp_users else []
        existentes = [normalizar_num_policia(n) for n in existentes_raw]

        col_np = localizar_coluna(df_cad, ["Nº DE POLÍCIA", "NUMERO", "POLICIA", "POLÍCIA"])
        col_nome = localizar_coluna(df_cad, ["NOME COMPLETO", "NOME"])
        col_posto = localizar_coluna(df_cad, ["POSTO", "GRADUAÇÃO", "GRADUACAO"])
        col_secao = localizar_coluna(df_cad, ["SEÇÃO", "SECAO", "FRAÇÃO"])
        col_faixa = localizar_coluna(df_cad, ["FAIXA"])

        novos_usuarios = []
        hash_inicial = gerar_hash(SENHA_PADRAO_INICIAL)

        for _, row in df_cad.iterrows():
            np_original = str(row.get(col_np, "")).strip()
            np_digitos = normalizar_num_policia(np_original)
            nome = str(row.get(col_nome, "")).strip()
            posto = str(row.get(col_posto, "")).strip()
            secao = str(row.get(col_secao, "")).strip()
            faixa = str(row.get(col_faixa, "")).strip().upper()

            if np_digitos and np_digitos not in existentes:
                # Regra de perfil inicial baseada na hierarquia e faixa
                if "LUCIANO PIRES" in nome.upper():
                    perfil = "Administrador"
                elif any(f in faixa for f in ["ROXA", "MARROM", "PRETA"]):
                    perfil = "Instrutor"
                else:
                    perfil = "Praticante"

                novos_usuarios.append({
                    "numero_policia": np_original,
                    "login_usuario": np_digitos, # Login inicial é o próprio número de polícia
                    "nome_completo": nome,
                    "posto_graduacao": posto,
                    "secao": secao,
                    "perfil": perfil,
                    "senha_hash": hash_inicial,
                    "primeiro_acesso": True
                })

        if novos_usuarios:
            supabase.table("usuarios").insert(novos_usuarios).execute()
    except Exception as e:
        # Se ocorrer instabilidade de conexão na sincronização, segue em frente
        pass

def obter_dados_supabase():
    try:
        resp_pres = supabase.table("presencas_aula").select("*").eq("presenca_homologada", True).execute()
        presencas_homologadas = resp_pres.data if resp_pres else []

        resp_aulas = supabase.table("aulas").select("*").execute()
        aulas_todas = resp_aulas.data if resp_aulas else []
        
        return presencas_homologadas, aulas_todas
    except Exception:
        return [], []

def processar_dados_unificados(df_cad, df_freq, df_diario, presencas_supa, aulas_supa):
    if df_cad.empty or df_freq.empty:
        return pd.DataFrame(), pd.DataFrame(), 0

    col_sit = localizar_coluna(df_cad, ["SITUAÇÃO", "SITUACAO"])
    if col_sit:
        cad_ativos = df_cad[df_cad[col_sit].astype(str).str.strip().str.upper() == "ATIVO"].copy()
    else:
        cad_ativos = df_cad.copy()

    col_nome_freq = localizar_coluna(df_freq, ["NOME COMPLETO", "NOME"]) or df_freq.columns[0]
    col_nome_cad = localizar_coluna(cad_ativos, ["NOME COMPLETO", "NOME"]) or cad_ativos.columns[2]

    cad_ativos["chave_busca"] = cad_ativos[col_nome_cad].astype(str).str.strip().str.upper()
    df_freq["chave_busca"] = df_freq[col_nome_freq].astype(str).str.strip().str.upper()

    df_consolidado = pd.merge(
        cad_ativos,
        df_freq,
        on="chave_busca",
        how="inner",
        suffixes=("", "_freq")
    )

    pres_col = localizar_coluna(df_consolidado, ["TOTAL PRESEN"])
    df_consolidado["Presencas_Base"] = pd.to_numeric(df_consolidado[pres_col], errors="coerce").fillna(0).astype(int) if pres_col else 0

    presencas_supa_dict = {}
    for p in presencas_supa:
        nome_m = p.get("militar_nome", "").strip().upper()
        presencas_supa_dict[nome_m] = presencas_supa_dict.get(nome_m, 0) + 1

    def somar_presencas_supa(row):
        nome_completo = str(row.get("Nome Completo", "")).strip().upper()
        adicionais = 0
        for k_nome, qtd in presencas_supa_dict.items():
            if k_nome in nome_completo or nome_completo in k_nome:
                adicionais += qtd
        return adicionais

    df_consolidado["Presencas_Supa"] = df_consolidado.apply(somar_presencas_supa, axis=1)
    df_consolidado["Presenças"] = df_consolidado["Presencas_Base"] + df_consolidado["Presencas_Supa"]
    df_consolidado["XP"] = df_consolidado["Presenças"] * 100

    aulas_supa_finalizadas = [a for a in aulas_supa if a.get("status") == "FINALIZADA"]
    total_aulas_geral = len(df_diario) + len(aulas_supa_finalizadas)

    def calcular_assiduidade(row):
        if total_aulas_geral == 0:
            return "0,0%"
        pres = row["Presenças"]
        pct = min((pres / total_aulas_geral) * 100.0, 100.0)
        return f"{pct:.1f}%".replace(".", ",")

    df_consolidado["% Assiduidade"] = df_consolidado.apply(calcular_assiduidade, axis=1)

    def definir_insignia(row):
        val = str(row.get("% Assiduidade", "0%")).replace("%", "").replace(",", ".").strip()
        try:
            pct = float(val)
        except ValueError:
            pct = 0.0
        
        if pct >= 90.0:
            return "🥇 Diamante (Elite Tatame)"
        elif pct >= 75.0:
            return "🥈 Ouro (Constância de Ferro)"
        elif pct >= 50.0:
            return "🥉 Prata (Evolução Contínua)"
        else:
            return "🥋 Bronze (Em Desenvolvimento)"

    df_consolidado["Insígnia"] = df_consolidado.apply(definir_insignia, axis=1)

    faixas_docentes = ["ROXA", "MARROM", "PRETA", "VERMELHA"]
    col_faixa = localizar_coluna(df_consolidado, ["FAIXA"]) or "Faixa Jiu-Jitsu"
    
    df_consolidado["Eh_Instrutor"] = df_consolidado[col_faixa].astype(str).str.upper().apply(
        lambda f: any(grad in f for grad in faixas_docentes)
    )

    df_alunos = df_consolidado[~df_consolidado["Eh_Instrutor"]].copy()
    df_alunos = df_alunos.sort_values(by=["Presenças", "XP"], ascending=False).reset_index(drop=True)
    df_alunos.index = df_alunos.index + 1

    df_instrutores = df_consolidado[df_consolidado["Eh_Instrutor"]].copy()
    
    col_inst_diario = localizar_coluna(df_diario, ["INSTRUTOR"])
    def contar_aulas_ministradas(nome):
        partes = [p.upper() for p in str(nome).split() if len(p) > 2]
        total_planilha = 0
        if not df_diario.empty and col_inst_diario:
            total_planilha = int(df_diario[col_inst_diario].astype(str).apply(
                lambda x: any(p in x.upper() for p in partes)
            ).sum())
        
        total_supa = 0
        for aula in aulas_supa_finalizadas:
            inst_aula = str(aula.get("instrutor", "")).upper()
            if any(p in inst_aula for p in partes):
                total_supa += 1

        return total_planilha + total_supa

    df_instrutores["Aulas Ministradas"] = df_instrutores["Nome Completo"].apply(contar_aulas_ministradas)

    return df_alunos, df_instrutores, total_aulas_geral

# --- CONTROLE DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario_dados"] = None

def realizar_login(login_ou_np: str, senha_plana: str):
    login_limpo = login_ou_np.strip()
    np_limpo = normalizar_num_policia(login_limpo)
    senha_hash = gerar_hash(senha_plana.strip())

    try:
        # Busca por login personalizado OU por número de polícia
        query = supabase.table("usuarios").select("*")
        if np_limpo:
            query = query.or_(f"login_usuario.eq.{login_limpo},numero_policia.ilike.%{np_limpo}%")
        else:
            query = query.eq("login_usuario", login_limpo)

        resp = query.execute()
        if resp and resp.data:
            user = resp.data[0]
            if user["senha_hash"] == senha_hash:
                st.session_state["autenticado"] = True
                st.session_state["usuario_dados"] = user
                return True, "Login realizado com sucesso."
            else:
                return False, "Senha incorreta."
        return False, "Usuário ou Nº de Polícia não encontrado."
    except Exception as e:
        return False, f"Erro de autenticação: {e}"

def realizar_logout():
    st.session_state["autenticado"] = False
    st.session_state["usuario_dados"] = None

# =========================================================
# FLUXO 1: TELA DE LOGIN OU PRIMEIRO ACESSO
# =========================================================
df_cad, df_freq, df_diario = carregar_dados_planilha()
sincronizar_efetivo_usuarios(df_cad)

if not st.session_state["autenticado"]:
    st.markdown("<h2 style='text-align: center; color: #1f4e78;'>🥋 Programa Jiu-Jitsu Institucional (DRH / PMMG)</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #555;'>Acesso ao Sistema de Instrução e Frequência</p>", unsafe_allow_html=True)
    
    col_l1, col_l2, col_l3 = st.columns([1, 1.4, 1])
    with col_l2:
        with st.container(border=True):
            st.subheader("Entrar no Sistema")
            login_input = st.text_input("Nº de Polícia ou Login Cadastrado", placeholder="Ex: 1351162 ou seu login")
            senha_input = st.text_input("Senha", type="password")
            
            st.caption(f"💡 *Primeiro acesso? Digite o seu Nº de Polícia e a senha padrão institucional (`{SENHA_PADRAO_INICIAL}`).*")
            
            if st.button("Acessar Tatame", type="primary", use_container_width=True):
                if login_input and senha_input:
                    ok, msg = realizar_login(login_input, senha_input)
                    if ok:
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Preencha todos os campos para continuar.")

# =========================================================
# FLUXO 2: OBRIGATORIEDADE DE TROCA NO PRIMEIRO ACESSO
# =========================================================
elif st.session_state["usuario_dados"].get("primeiro_acesso", False):
    u = st.session_state["usuario_dados"]
    st.markdown("<h2 style='text-align: center; color: #1f4e78;'>🔒 Atualização Obrigatória de Credenciais</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center;'>Bem-vindo(a), <b>{u['posto_graduacao']} {u['nome_completo']}</b>. Para garantir a segurança institucional, defina o seu novo login e a sua nova senha pessoal de acesso.</p>", unsafe_allow_html=True)

    col_t1, col_t2, col_t3 = st.columns([1, 1.5, 1])
    with col_t2:
        with st.container(border=True):
            with st.form("form_troca_senha"):
                st.markdown("### Suas Novas Credenciais")
                novo_login = st.text_input("Novo Nome de Usuário / Login", value=u["login_usuario"], help="Pode ser um login curto de sua preferência (ex: luciano.pires ou seu número)")
                nova_senha = st.text_input("Nova Senha Pessoal", type="password")
                confirma_senha = st.text_input("Confirme a Nova Senha", type="password")
                
                # Apenas Administradores podem redefinir perfis nesta tela
                if u.get("perfil") == "Administrador":
                    novo_perfil = st.selectbox("Perfil de Acesso", ["Administrador", "Instrutor", "Praticante"], index=0)
                else:
                    novo_perfil = u.get("perfil", "Praticante")

                btn_salvar_credenciais = st.form_submit_button("Salvar e Acessar o Sistema", type="primary", use_container_width=True)
                
                if btn_salvar_credenciais:
                    if len(nova_senha) < 4:
                        st.error("A nova senha deve possuir pelo menos 4 caracteres.")
                    elif nova_senha != confirma_senha:
                        st.error("As senhas informadas não coincidem.")
                    elif not novo_login.strip():
                        st.error("O nome de usuário não pode estar em branco.")
                    else:
                        try:
                            supabase.table("usuarios").update({
                                "login_usuario": novo_login.strip().lower(),
                                "senha_hash": gerar_hash(nova_senha),
                                "perfil": novo_perfil,
                                "primeiro_acesso": False
                            }).eq("id", u["id"]).execute()
                            
                            st.session_state["usuario_dados"]["login_usuario"] = novo_login.strip().lower()
                            st.session_state["usuario_dados"]["perfil"] = novo_perfil
                            st.session_state["usuario_dados"]["primeiro_acesso"] = False
                            st.success("Credenciais atualizadas com êxito! Redirecionando...")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao salvar: {e}. Tente outro nome de login.")

# =========================================================
# FLUXO 3: APLICAÇÃO PRINCIPAL AUTENTICADA
# =========================================================
else:
    u = st.session_state["usuario_dados"]
    presencas_supa, aulas_supa = obter_dados_supabase()
    df_alunos, df_instrutores, total_aulas_geral = processar_dados_unificados(
        df_cad, df_freq, df_diario, presencas_supa, aulas_supa
    )

    st.sidebar.markdown(f"### 🥋 {u['posto_graduacao']} {u['nome_completo']}")
    st.sidebar.caption(f"Perfil: **{u['perfil']}** | Seção: **{u.get('secao', 'DRH')}**")
    
    with st.sidebar.expander("🔑 Alterar Minha Senha"):
        with st.form("form_alterar_senha_lateral"):
            pwd_atual = st.text_input("Senha Atual", type="password")
            pwd_nova = st.text_input("Nova Senha", type="password")
            if st.form_submit_button("Atualizar Senha"):
                if gerar_hash(pwd_atual) == u["senha_hash"]:
                    if len(pwd_nova) >= 4:
                        supabase.table("usuarios").update({"senha_hash": gerar_hash(pwd_nova)}).eq("id", u["id"]).execute()
                        st.session_state["usuario_dados"]["senha_hash"] = gerar_hash(pwd_nova)
                        st.success("Senha alterada!")
                    else:
                        st.error("Mínimo de 4 dígitos.")
                else:
                    st.error("Senha atual incorreta.")

    if st.sidebar.button("Sair (Logout)"):
        realizar_logout()
        st.rerun()
        
    st.sidebar.divider()

    # Opções do menu por perfil
    opcoes = ["📅 Aulas & Check-in", "🏆 Ranking de Alunos", "👨‍🏫 Corpo de Instrutores", "👤 Área Individual"]
    if u["perfil"] == "Administrador":
        opcoes.append("⚙️ Gestão Executiva (Admin)")
        opcoes.append("👥 Gestão de Contas & Perfis")
    elif u["perfil"] == "Instrutor":
        opcoes.append("⚙️ Gestão Executiva (Admin)")

    menu = st.sidebar.radio("Navegação do Módulo", opcoes)

    # 1. MÓDULO AULAS & CHECK-IN
    if menu == "📅 Aulas & Check-in":
        st.title("📅 Quadro de Instruções & Presença")
        st.caption("Confirme sua presença antecipadamente. Ao final da aula, a chamada é homologada pelo instrutor.")

        eh_gestor = u["perfil"] in ["Administrador", "Instrutor"]

        if eh_gestor:
            with st.expander("➕ Criar / Agendar Nova Instrução", expanded=False):
                with st.form("form_criar_aula", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    data_aula = c1.date_input("Data do Treino", min_value=date.today())
                    horario_aula = c2.selectbox("Horário", ["07h00 às 08h15 (Sem TFM)", "18h30 às 19h45"])
                    
                    c3, c4 = st.columns(2)
                    local_aula = c3.text_input("Local da Instrução", value="6º Andar - DRH")
                    instrutor_aula = c4.text_input("Instrutor Responsável", value=f"{u['posto_graduacao']} {u['nome_completo']}")
                    
                    tema_aula = st.text_input("Tema / Técnicas Previstas", placeholder="Ex: Raspagem de gancho e passagem toureada")
                    
                    if st.form_submit_button("Publicar Aula no Quadro"):
                        if tema_aula.strip():
                            supabase.table("aulas").insert({
                                "data_aula": str(data_aula),
                                "horario": horario_aula,
                                "local": local_aula,
                                "instrutor": instrutor_aula,
                                "tema": tema_aula,
                                "status": "ABERTA"
                            }).execute()
                            st.success("Aula aberta para inscrições!")
                            st.rerun()
                        else:
                            st.error("Preencha o tema/conteúdo técnico da aula.")

        try:
            resp_aulas = supabase.table("aulas").select("*").order("data_aula", desc=True).limit(8).execute()
            aulas = resp_aulas.data if resp_aulas else []
        except Exception as e:
            st.error(f"Erro ao conectar com o banco de dados: {e}")
            aulas = []

        if not aulas:
            st.info("Nenhuma instrução agendada no momento. Aguarde a abertura de novos treinos.")
        else:
            for aula in aulas:
                aula_id = aula["id"]
                status_aula = aula.get("status", "ABERTA")
                
                resp_chk = supabase.table("presencas_aula").select("*").eq("aula_id", aula_id).execute()
                checkins = resp_chk.data if resp_chk else []
                nomes_confirmados = [c["militar_nome"] for c in checkins]

                with st.container():
                    st.markdown(
                        f"""
                        <div style='background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px; margin-bottom: 8px;'>
                            <span style='background-color: #0284c7; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem;'>⏰ {aula['horario']}</span>
                            <span style='background-color: #334155; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; margin-left: 6px;'>📍 {aula['local']}</span>
                            <h3 style='margin-top: 8px; margin-bottom: 2px; color: #0f172a;'>Data: {pd.to_datetime(aula['data_aula']).strftime('%d/%m/%Y')}</h3>
                            <p style='margin-bottom: 2px; color: #334155;'><b>Tema:</b> {aula['tema']}</p>
                            <p style='margin-bottom: 4px; color: #334155;'><b>Instrutor:</b> {aula['instrutor']}</p>
                            <p style='margin-bottom: 0px; color: #0369a1; font-weight: bold;'>👥 {len(checkins)} militar(es) com presença sinalizada</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    c_acao, c_status = st.columns([1.5, 2.5])
                    with c_acao:
                        if status_aula == "ABERTA":
                            militar_logado = u["nome_completo"]
                            if militar_logado not in nomes_confirmados:
                                if st.button("🥋 Vou Treinar!", key=f"in_{aula_id}", type="primary", use_container_width=True):
                                    supabase.table("presencas_aula").insert({
                                        "aula_id": aula_id,
                                        "militar_nome": militar_logado,
                                        "posto_graduacao": u["posto_graduacao"],
                                        "numero_policia": u["numero_policia"],
                                        "checkin_confirmado": True,
                                        "presenca_homologada": False
                                    }).execute()
                                    st.success("Check-in efetuado!")
                                    st.rerun()
                            else:
                                st.success("✅ Presença sinalizada!")
                                if st.button("Cancelar Presença", key=f"out_{aula_id}", use_container_width=True):
                                    supabase.table("presencas_aula").delete().match({
                                        "aula_id": aula_id,
                                        "militar_nome": militar_logado
                                    }).execute()
                                    st.info("Check-in cancelado.")
                                    st.rerun()
                        else:
                            st.warning("🔒 Treino Finalizado (Inscrições encerradas)")

                    if eh_gestor and checkins:
                        with st.expander(f"📝 Homologar Chamada - Aula #{aula_id} ({len(checkins)} presentes)"):
                            st.caption("Marque os militares que efetivamente compareceram ao treino:")
                            
                            marcados = {}
                            for chk in checkins:
                                estado = chk.get("presenca_homologada", False)
                                marcados[chk["id"]] = st.checkbox(
                                    f"{chk['militar_nome']}",
                                    value=estado,
                                    key=f"chk_homolog_{aula_id}_{chk['id']}"
                                )

                            btn_c1, btn_c2 = st.columns(2)
                            if btn_c1.button("💾 Salvar Frequência", key=f"btn_salvar_{aula_id}"):
                                for pres_id, presente_real in marcados.items():
                                    supabase.table("presencas_aula").update({
                                        "presenca_homologada": presente_real
                                    }).eq("id", pres_id).execute()
                                st.success("Presenças homologadas salvas!")
                                st.rerun()

                            if status_aula == "ABERTA":
                                if btn_c2.button("🏁 Finalizar Aula e Fechar Chamada", key=f"btn_fechar_{aula_id}"):
                                    supabase.table("aulas").update({"status": "FINALIZADA"}).eq("id", aula_id).execute()
                                    st.success("Instrução concluída e travada!")
                                    st.rerun()

                    st.divider()

    # 2. RANKING DE ALUNOS
    elif menu == "🏆 Ranking de Alunos":
        st.title("🏆 Ranking de Alunos & Praticantes")
        st.caption("Discentes ativos (Faixas Branca e Azul) — Presenças unificadas em tempo real.")

        if not df_alunos.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Alunos Ativos", f"{len(df_alunos)}")
            c2.metric("Total de Aulas Registradas", f"{total_aulas_geral}")
            
            lider_nome = df_alunos.iloc[0].get("Nome Completo", "Destaque")
            lider_pres = df_alunos.iloc[0]["Presenças"]
            c3.metric("Líder de Presenças (Alunos)", f"{lider_pres} aulas", str(lider_nome))

            st.write("---")
            cols_desejadas = [
                localizar_coluna(df_alunos, ["POSTO", "GRADUAÇÃO"]),
                "Nome Completo",
                localizar_coluna(df_alunos, ["SEÇÃO", "SECAO", "FRAÇÃO"]),
                localizar_coluna(df_alunos, ["FAIXA"]),
                localizar_coluna(df_alunos, ["GRAU"]),
                "Presenças",
                "% Assiduidade",
                "XP",
                "Insígnia"
            ]
            cols_existentes = [c for c in cols_desejadas if c and c in df_alunos.columns]
            st.dataframe(df_alunos[cols_existentes].copy(), use_container_width=True)
        else:
            st.warning("Sem alunos cadastrados no momento.")

    # 3. CORPO DE INSTRUTORES
    elif menu == "👨‍🏫 Corpo de Instrutores":
        st.title("👨‍🏫 Corpo de Instrutores & Graduados")
        st.caption("Controle de docência conforme Resolução nº 5.563/2026 (Faixa Roxa em diante).")

        if not df_instrutores.empty:
            for _, inst in df_instrutores.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.markdown(f"### {inst.get('Posto / Graduação', '')} {inst['Nome Completo']}")
                    c1.caption(f"Seção: {inst.get('Seção / Fração', 'DRH')} | Graduação: **{inst.get('Faixa Jiu-Jitsu', 'Faixa Preta')}**")
                    c2.metric("Aulas Ministradas", f"{inst['Aulas Ministradas']} aulas")
                    c3.metric("Função Técnica", "Instrutor Responsável")
                    st.divider()

            st.subheader("Diário Técnico Consolidado (Histórico)")
            cols_resumo = [c for c in ["Nº Aula", "Data da Aula", "Horário", "Local", "Instrutor", "Tema / Técnicas Ministradas", "Qtd Presentes", "Houve Intercorrência?", "Detalhamento Intercorrência"] if c in df_diario.columns]
            st.dataframe(df_diario[cols_resumo].reset_index(drop=True), use_container_width=True)
        else:
            st.info("Nenhum instrutor identificado.")

    # 4. ÁREA INDIVIDUAL
    elif menu == "👤 Área Individual":
        st.title("👤 Espelho Individual de Treinos")
        df_todos = pd.concat([df_alunos, df_instrutores]).sort_values(by="Nome Completo")
        if not df_todos.empty:
            nomes_praticantes = df_todos["Nome Completo"].tolist()
            # Posiciona por padrão no militar logado
            idx_padrao = nomes_praticantes.index(u["nome_completo"]) if u["nome_completo"] in nomes_praticantes else 0
            selecionado = st.selectbox("Selecione o Militar para visualizar o espelho:", nomes_praticantes, index=idx_padrao)

            dados_militar = df_todos[df_todos["Nome Completo"] == selecionado].iloc[0]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Graduação", f"{dados_militar.get('Faixa Jiu-Jitsu', 'N/A')}")
            
            if dados_militar.get("Eh_Instrutor", False):
                c2.metric("Aulas Ministradas", f"{dados_militar['Aulas Ministradas']} aulas")
                c3.metric("Função", "Instrutor Responsável")
                c4.metric("Status", "Docência Ativa")
            else:
                c2.metric("Total de Presenças", f"{dados_militar['Presenças']} aulas")
                c3.metric("Assiduidade Proporcional", f"{dados_militar['% Assiduidade']}")
                c4.metric("Pontuação Total", f"{dados_militar['XP']} XP")

            st.write("---")
            st.subheader("Presenças Homologadas no Sistema Atual")
            presencas_deste_militar = [
                p for p in presencas_supa 
                if p.get("militar_nome", "").strip().upper() in selecionado.upper()
                or selecionado.upper() in p.get("militar_nome", "").strip().upper()
            ]
            
            if presencas_deste_militar:
                df_pres_militar = pd.DataFrame(presencas_deste_militar)
                cols_supa_view = [c for c in ["aula_id", "data_registro", "presenca_homologada"] if c in df_pres_militar.columns]
                st.dataframe(df_pres_militar[cols_supa_view].reset_index(drop=True), use_container_width=True)
            else:
                st.caption("Nenhuma presença recente registrada no novo sistema.")

            cols_presentes = [c for c in df_diario.columns if "PRESENTE" in c.upper() and c.upper() != "QTD PRESENTES"]
            if not df_diario.empty and cols_presentes:
                mascara_presenca = df_diario[cols_presentes].apply(
                    lambda linha: linha.astype(str).str.contains(selecionado, case=False, na=False).any(),
                    axis=1
                )
                historico_legado = df_diario[mascara_presenca].copy()

                st.subheader(f"Histórico em Diário Anterior ({len(historico_legado)} aulas)")
                cols_hist_exibir = [c for c in ["Nº Aula", "Data da Aula", "Horário", "Tema / Técnicas Ministradas", "Instrutor", "Local"] if c in historico_legado.columns]
                st.dataframe(historico_legado[cols_hist_exibir].reset_index(drop=True), use_container_width=True)
        else:
            st.info("Sem dados disponíveis.")

    # 5. GESTÃO EXECUTIVA
    elif menu == "⚙️ Gestão Executiva (Admin)":
        st.title("⚙️ Painel Executivo DRH")
        st.caption("Visão integrada: efetivo ativo, diário de bordo e corpo docente.")

        tab1, tab2, tab3 = st.tabs(["📋 Alunos / Discentes", "🥋 Diário de Aulas", "👨‍🏫 Corpo de Instrutores"])
        with tab1:
            st.dataframe(df_alunos, use_container_width=True)
        with tab2:
            st.dataframe(df_diario, use_container_width=True)
        with tab3:
            st.dataframe(df_instrutores, use_container_width=True)

    # 6. GESTÃO DE CONTAS & PERFIS (Apenas Administrador)
    elif menu == "👥 Gestão de Contas & Perfis":
        st.title("👥 Gestão de Contas de Acesso & Perfis")
        st.caption("Controle administrativo de logins, perfis regimentais e redefinição de senhas para o padrão.")

        try:
            resp_todos_users = supabase.table("usuarios").select("id, numero_policia, login_usuario, nome_completo, posto_graduacao, perfil, primeiro_acesso, criado_em").order("nome_completo").execute()
            df_users = pd.DataFrame(resp_todos_users.data) if resp_todos_users else pd.DataFrame()
        except Exception as e:
            st.error(f"Erro ao carregar usuários: {e}")
            df_users = pd.DataFrame()

        if not df_users.empty:
            st.dataframe(df_users, use_container_width=True)

            st.write("---")
            st.subheader("Gerenciar Militar Selecionado")
            
            c_sel1, c_sel2 = st.columns(2)
            id_militar_sel = c_sel1.selectbox(
                "Selecione o militar:",
                df_users["id"].tolist(),
                format_func=lambda x: f"{df_users[df_users['id']==x].iloc[0]['posto_graduacao']} {df_users[df_users['id']==x].iloc[0]['nome_completo']} ({df_users[df_users['id']==x].iloc[0]['numero_policia']})"
            )
            
            user_alvo = df_users[df_users["id"] == id_militar_sel].iloc[0]
            
            perfis_possiveis = ["Praticante", "Instrutor", "Administrador"]
            idx_p = perfis_possiveis.index(user_alvo["perfil"]) if user_alvo["perfil"] in perfis_possiveis else 0
            novo_p = c_sel2.selectbox("Alterar Perfil Regimental", perfis_possiveis, index=idx_p)

            c_act1, c_act2 = st.columns(2)
            if c_act1.button("💾 Salvar Novo Perfil", use_container_width=True):
                supabase.table("usuarios").update({"perfil": novo_p}).eq("id", id_militar_sel).execute()
                st.success("Perfil atualizado com sucesso!")
                st.rerun()

            if c_act2.button(f"🔄 Resetar Senha para o Padrão ({SENHA_PADRAO_INICIAL})", use_container_width=True):
                supabase.table("usuarios").update({
                    "senha_hash": gerar_hash(SENHA_PADRAO_INICIAL),
                    "primeiro_acesso": True
                }).eq("id", id_militar_sel).execute()
                st.warning(f"Senha de {user_alvo['nome_completo']} resetada para '{SENHA_PADRAO_INICIAL}'!")
                st.rerun()