"""Atualiza a planilha da Agroliga com cotações de commodities.

Uso:
    python atualizar.py              # grava no Google Sheets (precisa de credenciais)
    python atualizar.py --dry-run    # só busca os preços e salva CSVs locais em ./saida

Variáveis de ambiente:
    SPREADSHEET_ID           ID da planilha (trecho entre /d/ e /edit na URL)
    GOOGLE_CREDENTIALS_JSON  conteúdo do JSON da conta de serviço do Google
"""
import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

TZ = ZoneInfo("America/Sao_Paulo")

# Tickers do Yahoo Finance. Os abaixo são contínuos (o Yahoo faz a rolagem) e não vencem.
# (nome, ticker, unidade original, kg por bushel p/ conversão ou None)
ATIVOS_FIXOS = [
    ("Açúcar #11 (ICE)", "SB=F", "¢/libra-peso", None),
    ("Café Arábica (ICE)", "KC=F", "¢/libra-peso", None),
    ("Algodão #2 (ICE)", "CT=F", "¢/libra-peso", None),
    ("Suco de Laranja (ICE)", "OJ=F", "¢/libra-peso", None),
    ("Boi Gordo EUA (CME)", "LE=F", "¢/libra-peso", None),
]
CAMBIO = ("USD/BRL", "BRL=X", "R$/US$", None)

# Grãos têm contratos mensais que vencem. O script descobre sozinho os vencimentos
# vigentes, então os nomes são estáveis ("1º venc." é sempre o mais próximo) e o painel
# não quebra a cada vencimento. O contrato real aparece na coluna `ticker`.
# (nome, raiz no Yahoo, meses de vencimento, quantos vencimentos, kg por bushel)
GRAOS = [
    ("Soja CBOT", "ZS", "FHKNQUX", 2, 27.2155),
    ("Milho CBOT", "ZC", "HKNUZ", 2, 25.4012),
    ("Trigo CBOT", "ZW", "HKNUZ", 1, 27.2155),
]
CODIGOS_MES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
               "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}

COLUNAS_HIST = ["data", "ativo", "ticker", "preco", "unidade"]
COLUNAS_ATUAL = ["ativo", "ticker", "preco", "unidade", "variacao_pct",
                 "equiv_rs_saca_60kg", "data_pregao", "atualizado_em"]
COLUNAS_FISICO = ["data", "commodity_praca", "unidade", "preco", "fonte"]


def buscar_serie(ticker: str, periodo: str) -> pd.Series:
    """Série de fechamentos (índice = data do pregão). Levanta erro se vier vazia."""
    hist = yf.Ticker(ticker).history(period=periodo)["Close"].dropna()
    if hist.empty:
        raise ValueError("sem dados")
    hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
    return hist


def candidatos(raiz: str, meses: str, hoje):
    """Tickers dos contratos do mês atual em diante, em ordem de vencimento."""
    for ano in range(hoje.year, hoje.year + 3):
        for cod in sorted(meses, key=CODIGOS_MES.get):
            if (ano, CODIGOS_MES[cod]) >= (hoje.year, hoje.month):
                yield f"{raiz}{cod}{ano % 100:02d}.CBT"


def descobrir_contratos(raiz: str, meses: str, n: int, hoje) -> list:
    """Os n próximos contratos que ainda negociam (último pregão há <= 5 dias)."""
    achados = []
    for ticker in candidatos(raiz, meses, hoje):
        try:
            s = buscar_serie(ticker, "10d")
        except Exception:  # noqa: BLE001
            continue  # contrato vencido, ainda não listado ou sem dados
        if (pd.Timestamp(hoje) - s.index[-1]).days > 5:
            continue
        achados.append(ticker)
        if len(achados) == n:
            break
    return achados


def montar_ativos(hoje):
    """Lista final de ativos (com rolagem automática dos grãos) e eventuais falhas."""
    ativos, falhas = [], []
    for nome, raiz, meses, n, kg in GRAOS:
        tickers = descobrir_contratos(raiz, meses, n, hoje)
        if len(tickers) < n:
            falhas.append(f"{nome}: achei {len(tickers)} de {n} contratos vigentes")
        for i, ticker in enumerate(tickers, 1):
            ativos.append((f"{nome} ({i}º venc.)", ticker, "¢/bushel", kg))
    return ativos + ATIVOS_FIXOS, falhas


def equiv_reais_saca(preco_centavos_bu, kg_bu, usd_brl):
    """Paridade CBOT: ¢/bu -> R$/saca 60 kg (sem prêmio, frete ou impostos)."""
    if not kg_bu or not usd_brl:
        return ""
    return round(preco_centavos_bu / 100 * (60 / kg_bu) * usd_brl, 2)


def coletar(periodo_hist: str):
    """Retorna (historico, atual, falhas)."""
    historico, atual = [], []
    ativos, falhas = montar_ativos(datetime.now(TZ).date())
    series = {}
    for nome, ticker, unidade, kg in [CAMBIO] + ativos:
        try:
            series[ticker] = buscar_serie(ticker, periodo_hist)
        except Exception as e:  # noqa: BLE001
            falhas.append(f"{nome} ({ticker}): {e}")

    cambio = series.get(CAMBIO[1])
    cambio_atual = float(cambio.iloc[-1]) if cambio is not None else None
    agora = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

    for nome, ticker, unidade, kg in [CAMBIO] + ativos:
        s = series.get(ticker)
        if s is None:
            continue
        for data, preco in s.items():
            historico.append([data.strftime("%Y-%m-%d"), nome, ticker,
                              round(float(preco), 4), unidade])
        ultimo = float(s.iloc[-1])
        anterior = float(s.iloc[-2]) if len(s) > 1 else ultimo
        atual.append([
            nome, ticker, round(ultimo, 2), unidade,
            round((ultimo - anterior) / anterior * 100, 2),
            equiv_reais_saca(ultimo, kg, cambio_atual),
            s.index[-1].strftime("%Y-%m-%d"), agora,
        ])
    return historico, atual, falhas


def abrir_planilha():
    import gspread
    cred = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    sheet_id = os.environ.get("SPREADSHEET_ID")
    if not cred or not sheet_id:
        sys.exit("Defina GOOGLE_CREDENTIALS_JSON e SPREADSHEET_ID (ou use --dry-run).")
    gc = gspread.service_account_from_dict(json.loads(cred))
    return gc.open_by_key(sheet_id)


def aba(sh, titulo, cabecalho):
    import gspread
    try:
        ws = sh.worksheet(titulo)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=titulo, rows=1000, cols=len(cabecalho) + 2)
        ws.update(range_name="A1", values=[cabecalho])
    return ws


def gravar_sheets(historico, atual):
    sh = abrir_planilha()

    # Aba "Atual": foto do último pregão (sobrescreve).
    ws = aba(sh, "Atual", COLUNAS_ATUAL)
    ws.clear()
    ws.update(range_name="A1", values=[COLUNAS_ATUAL] + atual,
              value_input_option="USER_ENTERED")

    # Aba "Historico": só acrescenta pregões novos (chave = data + ticker).
    ws = aba(sh, "Historico", COLUNAS_HIST)
    if os.environ.get("REBUILD"):  # recomeça o histórico (ex.: após mudar nomes de ativos)
        ws.clear()
        ws.update(range_name="A1", values=[COLUNAS_HIST])
    existentes = {(r[0], r[2]) for r in ws.get_all_values()[1:] if len(r) > 2}
    novas = [r for r in historico if (r[0], r[2]) not in existentes]
    if novas:
        ws.append_rows(novas, value_input_option="USER_ENTERED")
    print(f"Historico: {len(novas)} linhas novas.")

    # Aba "Fisico_Manual": preenchida à mão (ver README). Nunca sobrescrita.
    aba(sh, "Fisico_Manual", COLUNAS_FISICO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Primeira execução traz 1 ano de histórico; depois bastam alguns dias.
    carga_completa = args.dry_run or os.environ.get("BACKFILL") or os.environ.get("REBUILD")
    historico, atual, falhas = coletar("1y" if carga_completa else "10d")

    if os.environ.get("REBUILD") and falhas:  # não apaga o histórico com dados incompletos
        sys.exit("REBUILD cancelado, houve falhas na coleta:\n- " + "\n- ".join(falhas))

    if args.dry_run:
        os.makedirs("saida", exist_ok=True)
        pd.DataFrame(historico, columns=COLUNAS_HIST).to_csv("saida/historico.csv", index=False)
        pd.DataFrame(atual, columns=COLUNAS_ATUAL).to_csv("saida/atual.csv", index=False)
        print(pd.DataFrame(atual, columns=COLUNAS_ATUAL).to_string(index=False))
    else:
        gravar_sheets(historico, atual)

    if falhas:
        print("\nFALHAS:\n- " + "\n- ".join(falhas), file=sys.stderr)
        sys.exit(1)  # faz o GitHub avisar por e-mail
    print("OK")


if __name__ == "__main__":
    main()
