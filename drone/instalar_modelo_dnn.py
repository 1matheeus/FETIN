"""
AeroScan — Instalador do modelo DNN de detecção facial
Projeto FETIN 2026 — Equipe 49

Baixa os dois arquivos que blur_lgpd.py precisa para borrar rostos
(deploy.prototxt + res10_300x300_ssd_iter_140000.caffemodel) e coloca em
drone/modelos_dnn/. Sem eles, a anonimização falha fechada — nenhuma foto
é salva (ver blur_lgpd.py) — então este passo é obrigatório antes de rodar
detectar_foco.py, demo.py --camera ou blur_lgpd.py em qualquer computador
novo (os pesos não vão para o repositório, são ~10 MB e ficam fora do git
de propósito).

Como usar (não precisa de nada além do Python já instalado):
  python drone/instalar_modelo_dnn.py
"""

import sys
import urllib.request
from pathlib import Path

ARQUIVOS = {
    "deploy.prototxt": (
        "https://raw.githubusercontent.com/opencv/opencv/master/"
        "samples/dnn/face_detector/deploy.prototxt"
    ),
    "res10_300x300_ssd_iter_140000.caffemodel": (
        "https://raw.githubusercontent.com/opencv/opencv_3rdparty/"
        "dnn_samples_face_detector_20170830/"
        "res10_300x300_ssd_iter_140000.caffemodel"
    ),
}

PASTA_MODELOS = Path(__file__).resolve().parent / "modelos_dnn"


def baixar(nome, url, destino):
    print(f"  Baixando {nome}...")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            destino.write_bytes(resp.read())
    except Exception as e:
        print(f"  ❌ Falhou: {e}")
        return False
    tamanho_kb = destino.stat().st_size / 1024
    print(f"  ✅ {nome} salvo ({tamanho_kb:.0f} KB)")
    return True


def main():
    print("\n🔒 AeroScan — Instalando modelo DNN de detecção facial")
    print("=" * 50)
    PASTA_MODELOS.mkdir(parents=True, exist_ok=True)

    ok = True
    for nome, url in ARQUIVOS.items():
        destino = PASTA_MODELOS / nome
        if destino.exists() and destino.stat().st_size > 0:
            print(f"  ✔  {nome} já existe, pulando")
            continue
        ok = baixar(nome, url, destino) and ok

    print("=" * 50)
    if ok:
        print(f"✅ Pronto. Modelo instalado em: {PASTA_MODELOS}")
        print("   Agora dá para rodar detectar_foco.py, demo.py ou blur_lgpd.py normalmente.")
    else:
        print("❌ Algum arquivo não baixou. Confira sua conexão e rode de novo.")
        print(f"   Se persistir, baixe manualmente e coloque em: {PASTA_MODELOS}")
        for nome, url in ARQUIVOS.items():
            print(f"     {nome} → {url}")
        sys.exit(1)


if __name__ == "__main__":
    main()
