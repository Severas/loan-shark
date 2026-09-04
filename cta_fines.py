"""
Regras de multa do CTA, cruzando roster + presenca na party + horarios.

Entradas:
  roster_rows : lista de (nome, last_seen, roles) do TSV.
  presentes   : conjunto de nomes canonicos detectados nas partys (so guild).
  cta_dt      : datetime de inicio do CTA (informado na entrada).
  record_dt   : datetime em que o roster foi gerado/exportado. Se None, usa o
                maior Last Seen do roster como aproximacao.
  grace_min   : minutos antes do inicio que ja contam como fuga (default 15).

Saida: dict com listas categorizadas e o motivo de cada multa.
"""
from datetime import datetime, timedelta

TS_FMT = "%m/%d/%Y %H:%M:%S"  # ex.: 07/07/2026 01:19:03


def parse_ts(s):
    s = s.strip()
    if not s or s.lower() == "online":
        return None
    try:
        return datetime.strptime(s, TS_FMT)
    except ValueError:
        return None


def roles_de(roles_str):
    return [r.strip() for r in roles_str.split(";") if r.strip()]


def eh_isento(roles):
    return any(r in ("VIP", "VIP AVALON") for r in roles)


def max_last_seen(roster_rows):
    ts = [parse_ts(ls) for _, ls, _ in roster_rows]
    ts = [t for t in ts if t]
    return max(ts) if ts else None


def resolver_record(roster_rows, cta_dt, record_dt=None):
    if record_dt is not None:
        return record_dt
    mls = max_last_seen(roster_rows)
    return max(mls, cta_dt) if mls else cta_dt


def pool_candidatos(roster_rows, cta_dt, record_dt=None, grace_min=15):
    """Nomes do roster que poderiam estar na party: Online, ou offline com
    Last Seen dentro da janela [inicio-graca .. registro]. Usado para restringir
    o OCR-matching a um conjunto pequeno e assim casar leituras ruins com seguranca."""
    from datetime import timedelta
    record_dt = resolver_record(roster_rows, cta_dt, record_dt)
    janela_ini = cta_dt - timedelta(minutes=grace_min)
    nomes = []
    for nome, last_seen, _roles in roster_rows:
        ls = parse_ts(last_seen)
        if ls is None:  # Online
            nomes.append(nome)
        elif janela_ini <= ls <= record_dt:
            nomes.append(nome)
    return nomes


def avaliar(roster_rows, presentes, cta_dt, record_dt=None, grace_min=15):
    record_dt = resolver_record(roster_rows, cta_dt, record_dt)
    janela_ini = cta_dt - timedelta(minutes=grace_min)

    presentes_norm = {p.lower() for p in presentes}
    rel = {
        "presentes": [],       # membros que compareceram (na party)
        "multados": [],        # {nome, motivo, last_seen}
        "isentos_vip": [],     # VIP/VIP AVALON que faltaram (sem multa)
        "sem_expectativa": [], # offline bem antes da janela (sem multa)
    }

    for nome, last_seen, roles_str in roster_rows:
        roles = roles_de(roles_str)
        na_party = nome.lower() in presentes_norm

        if na_party:
            rel["presentes"].append(nome)
            continue

        if eh_isento(roles):
            rel["isentos_vip"].append(nome)
            continue

        ls = parse_ts(last_seen)
        if ls is None:  # "Online" e nao esta na party
            rel["multados"].append({
                "nome": nome, "last_seen": "Online",
                "motivo": "online_fora_da_party",
            })
            continue

        if janela_ini <= ls <= record_dt:
            if ls < cta_dt:
                motivo = "saiu_ate_15min_antes_do_inicio"
            else:
                motivo = "entrou_e_saiu_durante_o_cta"
            rel["multados"].append({
                "nome": nome, "last_seen": ls.strftime(TS_FMT), "motivo": motivo,
            })
        else:
            rel["sem_expectativa"].append(nome)

    rel["record_dt"] = record_dt.strftime(TS_FMT)
    rel["cta_dt"] = cta_dt.strftime(TS_FMT)
    rel["janela_inicio"] = janela_ini.strftime(TS_FMT)
    return rel


def exportar_csv(caminho, rel, roster_rows, multa_valor=0):
    """Gera um CSV (um jogador por linha) para o controle de multas da guild.
    Colunas: personagem, status, motivo, valor_multa, last_seen, cargos.
    Usa utf-8-sig para acentos abrirem certo no Excel/LibreOffice."""
    import csv

    roles_map = {n: r for n, _, r in roster_rows}
    ls_map = {n: ls for n, ls, _ in roster_rows}

    linhas = []
    
    # multados primeiro (o que interessa para cobranca), depois o resto
    for m in rel["multados"]:
        nome = m["nome"]
        linhas.append([nome, "multado", m["motivo"], multa_valor,
                       ls_map.get(nome, ""), roles_map.get(nome, "")])
    for nome in sorted(rel["presentes"]):
        linhas.append([nome, "presente", "", 0,
                       ls_map.get(nome, ""), roles_map.get(nome, "")])
    for nome in sorted(rel["isentos_vip"]):
        linhas.append([nome, "isento_vip", "ausente_isento", 0,
                       ls_map.get(nome, ""), roles_map.get(nome, "")])
    for nome in sorted(rel["sem_expectativa"]):
        linhas.append([nome, "sem_expectativa", "", 0,
                       ls_map.get(nome, ""), roles_map.get(nome, "")])

    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["personagem", "status", "motivo", "valor_multa",
                    "last_seen", "cargos"])
        w.writerows(linhas)
    return len(linhas)
