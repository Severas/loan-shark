"""
Runner do sistema de CTA.

  python cta_run.py roster.tsv --cta "07/07/2026 21:00:00" party1.png party2.png
        [--record "07/07/2026 21:20:00"] [--grace 15]
        [--presentes Fulano Ciclano]   # complemento manual (igual seu tracker)

Fluxo:
  1. Detecta + OCR + corrige os nomes de cada imagem (cta_attendance).
  2. Junta os presentes de guild de todas as imagens (+ os manuais).
  3. Aplica as regras de multa (cta_fines) cruzando com o roster e o horario.
"""
import sys
import os
import csv
import json
import argparse
from datetime import datetime

import cta_attendance as A
import cta_fines as F

TS_FMT = "%m/%d/%Y %H:%M:%S"


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            if row and row[0].strip():
                nome = row[0].strip()
                ls = row[1].strip() if len(row) > 1 else ""
                roles = row[2].strip() if len(row) > 2 else ""
                rows.append((nome, ls, roles))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster")
    ap.add_argument("imagens", nargs="*")
    ap.add_argument("--cta", required=True, help='inicio do CTA "MM/DD/YYYY HH:MM:SS"')
    ap.add_argument("--record", default=None, help="horario do registro/export do roster")
    ap.add_argument("--grace", type=int, default=15)
    ap.add_argument("--presentes", nargs="*", default=[], help="nomes presentes manuais")
    ap.add_argument("--csv", default=None, help="caminho para exportar o relatorio em CSV")
    ap.add_argument("--multa", type=int, default=0, help="valor da multa por jogador multado")
    ap.add_argument("--limiar", type=int, default=65,
                    help="limiar do fuzzy (0-100). No modo pool pode ser baixo com seguranca")
    ap.add_argument("--debug", action="store_true",
                    help="mostra o que o OCR leu em cada tira (para afinar)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = load_rows(args.roster)
    canon = {n.lower(): n for n, _, _ in rows}

    cta_dt = datetime.strptime(args.cta, TS_FMT)
    rec_dt = datetime.strptime(args.record, TS_FMT) if args.record else None

    # pool = quem poderia estar na party (Online ou offline na janela do CTA).
    # Restringir o matching a esse conjunto pequeno automatiza o reconhecimento
    # de leituras ruins e rejeita externos, sem entradas manuais.

    pool = F.pool_candidatos(rows, cta_dt, rec_dt, args.grace)

    presentes = set()
    for img in args.imagens:
        if not os.path.isfile(img):
            print("aviso: imagem nao encontrada, pulando: %s" % img, file=sys.stderr)
            continue
        try:
            r = A.processar(img, args.roster, limiar=args.limiar, pool=pool)
        except Exception as e:
            print("aviso: falha ao processar %s: %s" % (img, e), file=sys.stderr)
            continue
        presentes.update(r["presentes_guild"])
        if args.debug:
            print("### DEBUG %s" % img, file=sys.stderr)
            au = r.get("autor")
            if au:
                print("  autor : lido=%-18r -> %-16s [%s %d]"
                      % (au["lido"], au["corrigido"],
                         "G" if au["na_guild"] else "x", au["score"]),
                      file=sys.stderr)
            for m in r.get("membros", []):
                print("  membro: lido=%-18r -> %-16s [%s %d]"
                      % (m["lido"], m["corrigido"],
                         "G" if m["na_guild"] else "x", m["score"]),
                      file=sys.stderr)

    # complemento manual, casando na grafia canonica do roster quando possivel
    for nm in args.presentes:
        presentes.add(canon.get(nm.lower(), nm))

    rel = F.avaliar(rows, presentes, cta_dt, rec_dt, args.grace)

    if args.csv:
        n = F.exportar_csv(args.csv, rel, rows, args.multa)
        print("CSV salvo em %s (%d linhas)" % (args.csv, n), file=sys.stderr)

    if args.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
        return

    print("== CTA %s | janela desde %s | registro %s =="
          % (rel["cta_dt"], rel["janela_inicio"], rel["record_dt"]))
    print("\nPRESENTES (%d): %s" % (len(rel["presentes"]), ", ".join(sorted(rel["presentes"]))))
    print("\nMULTADOS (%d):" % len(rel["multados"]))
    for m in sorted(rel["multados"], key=lambda x: (x["motivo"], x["nome"])):
        print("  %-18s %-32s %s" % (m["nome"], m["motivo"], m["last_seen"]))
    print("\nISENTOS VIP ausentes (%d): %s"
          % (len(rel["isentos_vip"]), ", ".join(sorted(rel["isentos_vip"]))))
    print("\nSEM EXPECTATIVA (offline antes da janela): %d" % len(rel["sem_expectativa"]))


if __name__ == "__main__":
    main()
