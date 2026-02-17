"""
AGENTE DE INSPEÇÃO — GER. DE MATERIAL RODANTE GD
Lê o Microsoft Lists real e analisa com IA (Claude)

Colunas mapeadas da lista:
  TAG, MODELO, OM, DATA, ÁREA DE INSPEÇÃO, HORÍMETRO, Analista Técnico, LADO,
  RODA GUIA, ELO, MOTRIZ(3 GARRAS),
  ROLETE SUPERIOR 1..5, SAPATA, PASSO DA ESTEIRA, BUCHA,
  ROLETE INFERIOR, ROLETES DANIFICADOS
"""

import os
import json
import requests
from datetime import datetime
from anthropic import Anthropic

# ─────────────────────────────────────────────
# CONFIGURAÇÃO — preencha com suas credenciais
# ─────────────────────────────────────────────

CLIENT_ID     = os.getenv("MS_CLIENT_ID",     "SEU_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "SEU_CLIENT_SECRET")
TENANT_ID     = os.getenv("MS_TENANT_ID",     "SEU_TENANT_ID")
SITE_ID       = os.getenv("MS_SITE_ID",       "SEU_SITE_ID")
LIST_NAME     = os.getenv("MS_LIST_NAME",     "Ger. de Material Rodante GD")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "SUA_CHAVE_ANTHROPIC")

# ─────────────────────────────────────────────
# PARÂMETROS DO FABRICANTE (da lista "Parâmetros" do Microsoft Lists)
# Coluna "Novo"             = valor de referência (peça nova)
# Coluna "Limite de desgaste" = valor mínimo/máximo aceitável antes da substituição
#
# LÓGICA POR COMPONENTE:
#   Roda Guia, Elo, Motriz, Rolete Sup/Inf, Sapata, Bucha
#     → medição ABAIXO do "Limite de desgaste" = substituir
#   Passo da Esteira
#     → medição ACIMA do "Limite de desgaste" = corrente elongada = substituir
# ─────────────────────────────────────────────

PARAMETROS_POR_MODELO = {
    "Pit Viper/DR416i": {
        "roda_guia_novo":      22.5,
        "roda_guia_limite":    34.5,    # abaixo → substituir
        "elo_novo":            155.5,
        "elo_limite":          142.5,   # abaixo → substituir
        "motriz_novo":         284.0,
        "motriz_limite":       270.0,   # abaixo → substituir
        "rolete_sup_novo":     190.0,
        "rolete_sup_limite":   167.5,   # abaixo → substituir
        "sapata_novo":         85.0,
        "sapata_limite":       70.6,    # abaixo → substituir
        "passo_novo":          1042.5,
        "passo_limite":        1055.5,  # ACIMA → elongado → substituir
        "bucha_novo":          14.0,
        "bucha_limite":        10.7,    # abaixo → substituir
        "rolete_inf_novo":     73.9,
        "rolete_inf_limite":   61.2,    # abaixo → substituir
        "roletes_danif_atencao": 1,
        "roletes_danif_critico": 3,
        "vida_util_horas":     50_000,
    },
    "FlexiROC D65": {
        "roda_guia_novo":      17.5,
        "roda_guia_limite":    25.5,    # abaixo → substituir
        "elo_novo":            89.0,
        "elo_limite":          84.2,    # abaixo → substituir
        "motriz_novo":         185.0,
        "motriz_limite":       165.0,   # abaixo → substituir
        "rolete_sup_novo":     100.0,
        "rolete_sup_limite":   92.0,    # abaixo → substituir
        "sapata_novo":         25.0,
        "sapata_limite":       6.0,     # abaixo → substituir
        "passo_novo":          686.0,
        "passo_limite":        698.7,   # ACIMA → elongado → substituir
        "bucha_novo":          8.2,
        "bucha_limite":        3.2,     # abaixo → substituir
        "rolete_inf_novo":     43.0,
        "rolete_inf_limite":   36.5,    # abaixo → substituir
        "roletes_danif_atencao": 1,
        "roletes_danif_critico": 3,
        "vida_util_horas":     30_000,
    },
}

def get_params(modelo: str) -> dict:
    """Retorna parâmetros do modelo. Fallback para Pit Viper se não encontrado."""
    for key in PARAMETROS_POR_MODELO:
        if key.lower() in modelo.lower():
            return PARAMETROS_POR_MODELO[key]
    return PARAMETROS_POR_MODELO["Pit Viper/DR416i"]


# ─────────────────────────────────────────────
# MICROSOFT GRAPH API
# ─────────────────────────────────────────────

def get_token() -> str:
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    r = requests.post(url, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_lista(token: str) -> list[dict]:
    """Retorna todos os items expandidos da lista."""
    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}"
        f"/lists/{LIST_NAME}/items?expand=fields&$top=999"
    )
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return [i["fields"] for i in r.json().get("value", [])]


# ─────────────────────────────────────────────
# MAPEAMENTO DE CAMPOS
# O Graph API retorna os nomes internos do SharePoint.
# Ajuste as chaves abaixo se necessário após testar.
# ─────────────────────────────────────────────

FIELD_MAP = {
    "TAG":                  "TAG",
    "MODELO":               "MODELO",
    "OM":                   "OM",
    "DATA":                 "DATA",
    "AREA":                 "_x00c1_REA_x0020_DE_x0020_INSPE_x00c7__x00c3_O",  # nome interno do SharePoint para "ÁREA DE INSPEÇÃO"
    "HORIMETRO":            "HOR_x00cd_METRO",
    "ANALISTA":             "Analista_x0020_T_x00e9_cnico",
    "LADO":                 "LADO",
    "RODA_GUIA":            "RODA_x0020_GUIA",
    "ELO":                  "ELO",
    "MOTRIZ":               "MOTRIZ_x00283_x0020_GARRAS_x0029_",
    "ROLETE_SUP_1":         "ROLETE_x0020_SUPERIO_x2026__0",
    "ROLETE_SUP_2":         "ROLETE_x0020_SUPERIO_x2026__1",
    "ROLETE_SUP_3":         "ROLETE_x0020_SUPERIO_x2026__2",
    "ROLETE_SUP_4":         "ROLETE_x0020_SUPERIO_x2026__3",
    "ROLETE_SUP_5":         "ROLETE_x0020_SUPERIO_x2026__4",
    "SAPATA":               "SAPATA",
    "PASSO":                "PASSO_x0020_DA_x0020_ESTEIRA",
    "BUCHA":                "BUCHA",
    "ROLETE_INF":           "ROLETE_x0020_INFERIOR",
    "ROLETES_DANIF":        "ROLETES_x0020_DANIFI_x2026_",
}

def extrair(item: dict, chave: str):
    """Tenta o nome mapeado, mas também tenta variações comuns."""
    campo = FIELD_MAP.get(chave, chave)
    val = item.get(campo)
    if val is None:
        # fallback: tenta o nome legível direto
        val = item.get(chave)
    return val


# ─────────────────────────────────────────────
# ANÁLISE
# ─────────────────────────────────────────────

def num(v):
    """Converte para float com segurança."""
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def analisar_item(item: dict) -> dict:
    modelo    = extrair(item, "MODELO") or ""
    P         = get_params(modelo)

    roda_guia  = num(extrair(item, "RODA_GUIA"))
    elo        = num(extrair(item, "ELO"))
    motriz     = num(extrair(item, "MOTRIZ"))
    sups       = [num(extrair(item, f"ROLETE_SUP_{i}")) for i in range(1, 6)]
    sapata     = num(extrair(item, "SAPATA"))
    passo      = num(extrair(item, "PASSO"))
    bucha      = num(extrair(item, "BUCHA"))
    rolete_inf = num(extrair(item, "ROLETE_INF"))
    danif      = num(extrair(item, "ROLETES_DANIF")) or 0
    horimetro  = num(extrair(item, "HORIMETRO")) or 0

    desvios  = []
    medicoes = {}

    def pct_desgaste(medido, novo, limite):
        """% de desgaste consumido em relação à faixa total (novo → limite)."""
        faixa = abs(novo - limite)
        if faixa == 0:
            return 0.0
        consumido = abs(medido - novo)
        return round(min(consumido / faixa * 100, 100), 1)

    def check_min(nome, val, lim, novo, label):
        """Falha quando val < lim (desgaste por redução de diâmetro/espessura)."""
        if val is None:
            return
        medicoes[nome] = val
        deg = pct_desgaste(val, novo, lim)
        if val < lim:
            desvio_pct = round((lim - val) / lim * 100, 1)
            desvios.append({"campo": label, "medido": val, "limite": lim,
                            "novo": novo, "tipo": "min",
                            "desvio_pct": desvio_pct, "pct_desgaste": deg})

    def check_max(nome, val, lim, novo, label):
        """Falha quando val > lim (passo: elongação da corrente)."""
        if val is None:
            return
        medicoes[nome] = val
        deg = pct_desgaste(val, novo, lim)
        if val > lim:
            desvio_pct = round((val - lim) / lim * 100, 1)
            desvios.append({"campo": label, "medido": val, "limite": lim,
                            "novo": novo, "tipo": "max",
                            "desvio_pct": desvio_pct, "pct_desgaste": deg})

    check_min("Roda Guia (mm)",      roda_guia,  P["roda_guia_limite"],  P["roda_guia_novo"],    "Roda Guia — desgaste excessivo")
    check_min("Elo (mm)",            elo,        P["elo_limite"],        P["elo_novo"],          "Elo — desgaste da corrente")
    check_min("Motriz (mm)",         motriz,     P["motriz_limite"],     P["motriz_novo"],       "Motriz — desgaste das garras")
    check_min("Sapata (mm)",         sapata,     P["sapata_limite"],     P["sapata_novo"],       "Sapata — espessura crítica")
    check_max("Passo Esteira (mm)",  passo,      P["passo_limite"],      P["passo_novo"],        "Passo — corrente elongada")
    check_min("Bucha (mm)",          bucha,      P["bucha_limite"],      P["bucha_novo"],        "Bucha — desgaste excessivo")
    check_min("Rolete Inferior (mm)",rolete_inf, P["rolete_inf_limite"], P["rolete_inf_novo"],   "Rolete Inferior — desgaste")

    for i, v in enumerate(sups, 1):
        check_min(f"Rolete Sup. {i} (mm)", v, P["rolete_sup_limite"], P["rolete_sup_novo"],
                  f"Rolete Superior {i} — desgaste")

    if danif > 0:
        medicoes["Roletes Danificados"] = danif
        if danif >= P["roletes_danif_critico"]:
            desvios.append({"campo": "Roletes Danificados — qtd. crítica", "medido": danif,
                            "limite": P["roletes_danif_critico"], "novo": 0, "tipo": "max",
                            "desvio_pct": 100, "pct_desgaste": 100})
        elif danif >= P["roletes_danif_atencao"]:
            desvios.append({"campo": "Roletes Danificados — atenção", "medido": danif,
                            "limite": P["roletes_danif_atencao"], "novo": 0, "tipo": "max",
                            "desvio_pct": 50, "pct_desgaste": 50})

    pct_vida = round(horimetro / P["vida_util_horas"] * 100, 1) if P["vida_util_horas"] else 0

    if desvios:
        max_desvio = max(d["desvio_pct"] for d in desvios)
        status = "CRÍTICO" if (max_desvio > 5 or pct_vida > 90) else "ATENÇÃO"
    elif pct_vida > 80:
        status = "ATENÇÃO"
    else:
        status = "OK"

    urgencia_dias = 7 if status == "CRÍTICO" else (30 if status == "ATENÇÃO" else None)

    return {
        "tag":           extrair(item, "TAG") or "N/D",
        "modelo":        modelo,
        "om":            extrair(item, "OM") or "N/D",
        "data":          extrair(item, "DATA") or "N/D",
        "area":          extrair(item, "AREA") or "N/D",
        "horimetro":     horimetro,
        "analista":      extrair(item, "ANALISTA") or "N/D",
        "lado":          extrair(item, "LADO") or "N/D",
        "pct_vida":      pct_vida,
        "medicoes":      medicoes,
        "desvios":       desvios,
        "status":        status,
        "urgencia_dias": urgencia_dias,
        "params":        P,   # inclui parâmetros usados no relatório
    }


def gerar_relatorio(itens_raw: list[dict]) -> dict:
    analises = [analisar_item(i) for i in itens_raw]
    criticos = [a for a in analises if a["status"] == "CRÍTICO"]
    atencao  = [a for a in analises if a["status"] == "ATENÇÃO"]
    ok       = [a for a in analises if a["status"] == "OK"]
    return {
        "gerado_em": datetime.now().isoformat(),
        "resumo": {"total": len(analises), "criticos": len(criticos),
                   "atencao": len(atencao), "ok": len(ok)},
        "criticos": criticos,
        "atencao":  atencao,
        "ok":       ok,
    }


# ─────────────────────────────────────────────
# AGENTE IA
# ─────────────────────────────────────────────

SYSTEM = """
Você é especialista em PCM (Planejamento e Controle de Manutenção) e inspeção de
material rodante de perfuratrizes (Pit Viper DR416i) — rodas guias, roletes, elos,
sapatas, motrizes e correntes de esteira.

Sua função:
1. Interpretar os desvios em linguagem técnica para o time de manutenção
2. Priorizar substituições por risco operacional e segurança
3. Sugerir cronograma realista (urgência, próxima parada programada, OM)
4. Recomendar se é possível aguardar ou se é emergencial
5. Identificar padrões de desgaste por TAG ou lado (LC/LNC)

Seja direto, técnico e prático. Use termos de manutenção de mineração.
"""

class Agente:
    def __init__(self):
        self.client    = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.historico = []
        self.relatorio = None

    def carregar(self, mock=False):
        if mock:
            self.relatorio = gerar_relatorio(MOCK_ITEMS)
        else:
            token = get_token()
            raw   = fetch_lista(token)
            self.relatorio = gerar_relatorio(raw)
        r = self.relatorio["resumo"]
        print(f"✅ {r['total']} inspeções | {r['criticos']} críticos | {r['atencao']} atenção | {r['ok']} OK")

    def chat(self, pergunta: str) -> str:
        if not self.relatorio:
            return "⚠️ Execute carregar() primeiro."
        ctx = f"""
RELATÓRIO MATERIAL RODANTE GD — {self.relatorio['gerado_em']}
RESUMO: {json.dumps(self.relatorio['resumo'], ensure_ascii=False)}

CRÍTICOS:
{json.dumps(self.relatorio['criticos'], ensure_ascii=False, indent=2)}

ATENÇÃO:
{json.dumps(self.relatorio['atencao'], ensure_ascii=False, indent=2)}

PERGUNTA DO PCM: {pergunta}
"""
        self.historico.append({"role": "user", "content": ctx})
        resp = self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=SYSTEM,
            messages=self.historico,
        )
        txt = resp.content[0].text
        self.historico.append({"role": "assistant", "content": txt})
        return txt

    def cronograma(self):
        return self.chat(
            "Gere um cronograma priorizado de substituições para as próximas 4 semanas. "
            "Para cada item inclua: TAG, lado, componente, desvio crítico, urgência em dias e OM de referência. "
            "Formate como tabela markdown ordenada por urgência."
        )

    def exportar(self, path="relatorio_material_rodante.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.relatorio, f, ensure_ascii=False, indent=2)
        print(f"📄 Exportado: {path}")


# ─────────────────────────────────────────────
# MOCK — baseado nos dados reais das screenshots
# ─────────────────────────────────────────────

MOCK_ITEMS = [
    # TAG 1101PF1601 — LC
    {"TAG":"1101PF1601","MODELO":"Pit Viper/DR416i","OM":"202503926856","DATA":"2025-08-18",
     "AREA":"FASE 6","HORIMETRO":9240,"ANALISTA":"BRUNO SILVA","LADO":"LC (lado cabine)",
     "RODA_GUIA":25,"ELO":154,"MOTRIZ":277,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":189,"ROLETE_SUP_3":189,"ROLETE_SUP_4":189,"ROLETE_SUP_5":189,
     "SAPATA":81,"PASSO":1045,"BUCHA":13.8,"ROLETE_INF":70.3,"ROLETES_DANIF":0},

    # TAG 1101PF1601 — LNC
    {"TAG":"1101PF1601","MODELO":"Pit Viper/DR416i","OM":"202503926856","DATA":"2025-08-18",
     "AREA":"FASE 6","HORIMETRO":9240,"ANALISTA":"BRUNO SILVA","LADO":"LNC (lado não cabine)",
     "RODA_GUIA":25,"ELO":154,"MOTRIZ":278,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":189,"ROLETE_SUP_3":190,"ROLETE_SUP_4":190,"ROLETE_SUP_5":189,
     "SAPATA":82.5,"PASSO":1045,"BUCHA":13.9,"ROLETE_INF":70.5,"ROLETES_DANIF":1},

    # TAG 1101PF1601 — LC (set out)
    {"TAG":"1101PF1601","MODELO":"Pit Viper/DR416i","OM":"202504627719","DATA":"2025-09-19",
     "AREA":"PÁTIO 320","HORIMETRO":9553,"ANALISTA":"BRUNO SILVA","LADO":"LC (lado cabine)",
     "RODA_GUIA":22.5,"ELO":154,"MOTRIZ":275,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":189,"ROLETE_SUP_3":189,"ROLETE_SUP_4":189,"ROLETE_SUP_5":189,
     "SAPATA":81,"PASSO":1045.5,"BUCHA":13.7,"ROLETE_INF":70.2,"ROLETES_DANIF":0},

    # TAG PZ1001SA02 — LC (horímetro alto!)
    {"TAG":"PZ1001SA02","MODELO":"Pit Viper/DR416i","OM":"202503858807","DATA":"2025-08-18",
     "AREA":"PÁTIO 320","HORIMETRO":45917,"ANALISTA":"BRUNO SILVA","LADO":"LC (lado cabine)",
     "RODA_GUIA":23,"ELO":152,"MOTRIZ":282,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":189,"ROLETE_SUP_3":189,"ROLETE_SUP_4":189,"ROLETE_SUP_5":188,
     "SAPATA":81,"PASSO":1045,"BUCHA":13.9,"ROLETE_INF":69.3,"ROLETES_DANIF":0},

    # TAG PZ1001SA02 — LNC
    {"TAG":"PZ1001SA02","MODELO":"Pit Viper/DR416i","OM":"202503858807","DATA":"2025-08-18",
     "AREA":"PÁTIO 320","HORIMETRO":45917,"ANALISTA":"BRUNO SILVA","LADO":"LNC (lado não cabine)",
     "RODA_GUIA":23,"ELO":153,"MOTRIZ":280,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":189,"ROLETE_SUP_3":189,"ROLETE_SUP_4":189,"ROLETE_SUP_5":188,
     "SAPATA":82,"PASSO":1046,"BUCHA":13.9,"ROLETE_INF":69,"ROLETES_DANIF":0},

    # TAG PZ1001SA03 — LC (roletes danificados!)
    {"TAG":"PZ1001SA03","MODELO":"Pit Viper/DR416i","OM":"202503099260","DATA":"2025-08-01",
     "AREA":"FASE 5","HORIMETRO":39050,"ANALISTA":"BRUNO SILVA","LADO":"LC (lado cabine)",
     "RODA_GUIA":23,"ELO":155,"MOTRIZ":283,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":190,"ROLETE_SUP_3":189,"ROLETE_SUP_4":189,"ROLETE_SUP_5":189,
     "SAPATA":84,"PASSO":1045,"BUCHA":13.7,"ROLETE_INF":64,"ROLETES_DANIF":5},

    # TAG PZ1001SA03 — LNC
    {"TAG":"PZ1001SA03","MODELO":"Pit Viper/DR416i","OM":"202503099260","DATA":"2025-08-01",
     "AREA":"FASE 5","HORIMETRO":39050,"ANALISTA":"BRUNO SILVA","LADO":"LNC (lado não cabine)",
     "RODA_GUIA":24,"ELO":155,"MOTRIZ":283,
     "ROLETE_SUP_1":189,"ROLETE_SUP_2":190,"ROLETE_SUP_3":189,"ROLETE_SUP_4":190,"ROLETE_SUP_5":189,
     "SAPATA":84,"PASSO":1045,"BUCHA":13.9,"ROLETE_INF":64.5,"ROLETES_DANIF":0},
]


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("="*60)
    print("  🤖 AGENTE — MATERIAL RODANTE GD")
    print("="*60)

    agente = Agente()
    agente.carregar(mock=True)   # troque para mock=False para ler o Lists real

    print("\n📊 Cronograma automático:\n")
    print(agente.cronograma())

    agente.exportar()

    print("\n" + "="*60)
    print("  💬 CHAT PCM — (sair para encerrar)")
    print("="*60)

    while True:
        q = input("\n🔧 PCM > ").strip()
        if q.lower() in ("sair","exit","quit"):
            break
        if q:
            print("\n🤖", agente.chat(q))
