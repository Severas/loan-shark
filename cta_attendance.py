"""
CTA attendance: pipeline completo.

  imagem + roster.tsv  ->  { autor, lider, membros[], presentes_guild[] }

Etapas:
  1. detect_regions: independente da posicao na tela.
  2. OCR por regiao.
  3. name_match: corrige cada nome contra o roster da guild.

Uso: python cta_attendance.py imagem.png roster.tsv
"""
import sys
import re
import json
from collections import Counter
import numpy as np
from PIL import Image, ImageOps, ImageEnhance
from scipy import ndimage

import detect_regions as D
import name_match as NM

# Altura-alvo (em px) do texto entregue ao OCR, independente da resolucao de
# origem. Um fator de resize FIXO (ex.: sempre x4) faria um crop de 4K ficar
# enorme e lento, e um crop de tela pequena nao ampliar o suficiente. Mirar
# numa altura absoluta deixa o "tamanho aparente" da fonte estavel para o
# modelo de OCR, o que tende a melhorar a leitura em qualquer resolucao.
_OCR_TARGET_H = 88

# Score (0-100) a partir do qual uma leitura ja e "boa o suficiente": mesmo
# sem bater com ninguem do pool/roster (guild=False), tentar mais variantes
# de pre-processamento dificilmente vai mudar o resultado, so custa CPU.
# So vale reprocessar quando a leitura da variante anterior ficou fraca.
_VARIANT_GOOD_ENOUGH = 75


_RAPID_ENGINE = None


def _rapid_engine():
    global _RAPID_ENGINE
    if _RAPID_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID_ENGINE = RapidOCR()
    return _RAPID_ENGINE


def _preprocess(pil_img, variant):
    fator = max(1.0, _OCR_TARGET_H / max(1, pil_img.height))
    novo_w = max(1, round(pil_img.width * fator))
    novo_h = max(1, round(pil_img.height * fator))
    g = pil_img.resize((novo_w, novo_h), Image.LANCZOS)
    if variant == 1:
        # 2a tentativa: contraste mais agressivo + leve blur (ajuda quando
        # brilho/anti-aliasing da fonte confunde a 1a leitura).
        g = ImageEnhance.Contrast(g).enhance(1.8)
        g = ImageEnhance.Sharpness(g).enhance(2.2)
    elif variant == 2:
        # 3a tentativa: binariza mantendo so o texto claro (alto brilho).
        gg = ImageOps.grayscale(g)
        arr = np.asarray(gg).astype(np.int16)
        thr = int(arr.mean() + arr.std() * 0.5)
        bw = np.where(arr > thr, 255, 0).astype("uint8")
        g = Image.fromarray(bw).convert("RGB")
    return g


def ocr(pil_img, dark_on_light, variant=0):
    g = _preprocess(pil_img, variant)
    try:
        engine = _rapid_engine()
    except ModuleNotFoundError:
        raise RuntimeError(
            "rapidocr-onnxruntime nao esta instalado. Rode: "
            "pip install rapidocr-onnxruntime (ou rode so com --presentes)."
        )
    out = engine(np.array(g))
    res = out[0] if isinstance(out, tuple) else out
    if res:
        txt = "".join(item[1] for item in res)
        return re.sub(r"[^A-Za-z0-9_]", "", txt)
    return ""


# recorte das tiras de membro
def _member_strips(a, box):
    """Reusa a MESMA deteccao/filtro de tiras de detect_regions.raw_strips
    (antes esta funcao duplicava os limiares com valores levemente diferentes
    dos usados para achar o cluster, o que podia fazer uma tira aparecer no
    cluster mas sumir de novo aqui dentro). Passar 'box' como regiao restringe
    a busca a ela, mas a escala usada continua a da imagem inteira (a)."""
    strips = D.raw_strips(a, region=(box[0], box[1], box[2], box[3]))
    # ordena por coluna (borda esquerda) e depois por Y
    col_w = D.px(a, 40)
    strips.sort(key=lambda s: (round(s[0] / col_w), s[1]))
    return strips


def processar(imagem, roster_path, limiar=65, pool=None):
    """Se 'pool' (lista de nomes candidatos: quem estava Online/na janela) for
    fornecido, o matching e feito so contra ele, com atribuicao unica e scorer
    tolerante a embaralho, o que casa leituras ruins com seguranca e rejeita
    externos. Sem pool, cai no matching classico contra o roster inteiro."""
    a = D.load_rgb(imagem)
    img = Image.open(imagem).convert("RGB")
    roster = NM.load_roster(roster_path)

    # autor
    autor = None
    sb = D.find_self_plate(a)
    if sb:
        b = sb[0]
        mx, my = D.px(a, 3), D.px(a, 1)
        crop = img.crop((b[0] + mx, b[1] + my, b[2] - D.px(a, 2), b[3] - my))
        autor = {"lido": "", "corrigido": "", "score": -1, "na_guild": False}
        for variant in (0, 1, 2):
            lido = ocr(crop, dark_on_light=True, variant=variant)
            if not lido:
                continue
            if pool is not None:
                canon, score, guild = NM.match_pool(lido, pool, limiar)
            else:
                canon, score, guild = NM.match_roster(lido, roster, limiar)
            if guild:
                autor = {"lido": lido, "corrigido": canon, "score": score, "na_guild": True}
                break
            if score > autor["score"]:
                autor = {"lido": lido, "corrigido": canon, "score": score, "na_guild": False}
            # leitura ja ficou boa o suficiente: mais variantes dificilmente
            # mudam o resultado, entao para de gastar OCR a toa.
            if autor["score"] >= _VARIANT_GOOD_ENOUGH:
                break

    # membros: OCR por tira, com ate 2 novas tentativas (pre-processamento
    # alternativo) so enquanto a leitura anterior nao casou com ninguem do
    # pool E ainda estiver fraca. Isso resolve falhas pontuais de OCR
    # (brilho, anti-aliasing) sem hardcode de nomes, e sem reprocessar tiras
    # que ja leram bem na 1a tentativa.
    membros = []
    disponiveis = list(pool) if pool is not None else None
    pb = D.find_party_cluster(a)
    if pb:
        strips = _member_strips(a, pb[0])

        # O icone de funcao (tanque=azul, suporte=verde, dps/recrutador=
        # vermelho/dourado) tem cor variavel. Quando e vermelho/dourado, ele cai
        # dentro da mascara e empurra a borda esquerda da tira pra tras do que
        # deveria, incluindo o icone no recorte do nome (atrapalha o OCR).
        # Normaliza por coluna: usa a borda direita observada com mais
        # frequencia naquela coluna como referencia do "inicio do texto",
        # ja que a maioria das tiras (icone nao-vermelho) fica correta.
        col_w = D.px(a, 30)
        col_de = lambda s: round(s[0] / col_w) * col_w
        colunas = {}
        for s in strips:
            colunas.setdefault(col_de(s), []).append(s[0])
        x0_coluna = {c: Counter(xs).most_common(1)[0][0] if len(set(xs)) < len(xs)
                    else max(xs) for c, xs in colunas.items()}

        margem_topo = D.px(a, 2)
        margem_lado = D.px(a, 3)
        for s in strips:
            x0_ref = x0_coluna.get(col_de(s), s[0])
            # usa o x0 mais para a direita entre o observado e o de referencia
            # da coluna: nunca corta letra (fica <= observado), e ignora o
            # icone quando ele vazou pra dentro da tira detectada.
            x0_texto = max(s[0], x0_ref)
            h_tira = s[3] - s[1] + 1
            top = s[1] - margem_topo
            if h_tira > D.px(a, 20):
                # tira de 2 linhas (nome + subtitulo tipo "Fora Da Regiao"):
                # usa so a metade de cima, que e o nome.
                bot = s[1] + int(h_tira * 0.55)
            else:
                bot = min(s[3] + margem_topo + 1, s[1] + D.px(a, 16))
            x0 = max(0, x0_texto - margem_lado)
            crop = img.crop((x0, top, s[2] + margem_lado, bot))

            melhor = {"lido": "", "corrigido": "", "score": -1, "na_guild": False}
            for variant in (0, 1, 2):
                lido = ocr(crop, dark_on_light=False, variant=variant)
                if len(lido) < 3:
                    continue
                if pool is not None:
                    canon, score, guild = NM.match_pool(lido, disponiveis, limiar)
                else:
                    canon, score, guild = NM.match_roster(lido, roster, limiar)
                if guild:
                    melhor = {"lido": lido, "corrigido": canon,
                             "score": score, "na_guild": True}
                    break  # achou match confiavel, para de tentar variantes
                if score > melhor["score"]:
                    melhor = {"lido": lido, "corrigido": canon,
                             "score": score, "na_guild": False}
                # leitura ja boa o suficiente: novas variantes raramente
                # ajudam, entao evita gastar OCR a toa nessa tira.
                if melhor["score"] >= _VARIANT_GOOD_ENOUGH:
                    break

            if melhor["lido"]:
                membros.append(melhor)
                if melhor["na_guild"] and disponiveis is not None:
                    disponiveis.remove(melhor["corrigido"])

    presentes = sorted({m["corrigido"] for m in membros if m["na_guild"]})
    if autor and autor["na_guild"]:
        presentes = sorted(set(presentes) | {autor["corrigido"]})

    return {"autor": autor, "membros": membros, "presentes_guild": presentes}


if __name__ == "__main__":
    out = processar(sys.argv[1], sys.argv[2])
    print(json.dumps(out, ensure_ascii=False, indent=2))
