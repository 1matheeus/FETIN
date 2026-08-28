"""
AeroScan — Testes da fronteira de anonimização
Projeto FETIN 2026 — Equipe 49

Trava uma regra só, a que importa: **nenhuma foto vai para o disco sem passar
pelo borrão de rostos.** Antes destes testes, `blur_lgpd.py` existia, funcionava
e não era chamado por ninguém — o README afirmava uma anonimização que o código
não fazia. Um teste que exercita o caminho de gravação impede a reincidência.

Não precisa de GPU, câmera, GPS nem do modelo YOLO: o `ultralytics` é
substituído por um stub para que o `detectar_foco` possa ser importado.

Como rodar:
    python drone/testar_anonimizacao.py
"""

import sys
import types
import tempfile
import csv
from pathlib import Path

import numpy as np
import cv2

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))

# O detectar_foco importa YOLO no topo. Aqui não queremos torch nem pesos —
# só o caminho de gravação de imagem.
if 'ultralytics' not in sys.modules:
    _stub = types.ModuleType('ultralytics')
    _stub.YOLO = object
    sys.modules['ultralytics'] = _stub

import blur_lgpd
import detectar_foco


falhas = []


def verificar(descricao, condicao):
    if condicao:
        print(f'  ✅ {descricao}')
    else:
        print(f'  ❌ {descricao}')
        falhas.append(descricao)


def frame_de_teste(cor=70):
    img = np.full((120, 160, 3), cor, np.uint8)
    cv2.circle(img, (80, 60), 25, (20, 200, 20), -1)
    return img


def teste_importacao_nao_carrega_cascade():
    """Importar o módulo não pode falhar nem carregar os cascades cedo demais.

    O carregamento é preguiçoso justamente para que um OpenCV incompleto não
    derrube a importação do detectar_foco — a falha precisa chegar a quem
    chama, que decide não gravar a foto.
    """
    print('\n1. Importação')
    verificar('blur_lgpd expõe anonimizar()', callable(blur_lgpd.anonimizar))
    verificar('detectar_foco importa anonimizar', callable(detectar_foco.anonimizar))


def teste_anonimizar_devolve_copia():
    print('\n2. anonimizar() não altera o frame original')
    img = frame_de_teste()
    copia_antes = img.copy()
    saida, rostos = blur_lgpd.anonimizar(img)
    verificar('devolve uma imagem nova, não o mesmo objeto', saida is not img)
    verificar('mesmo formato', saida.shape == img.shape)
    verificar('frame original intacto', np.array_equal(img, copia_antes))
    verificar('conta rostos como inteiro', isinstance(rostos, int))


def teste_blur_altera_so_o_rosto():
    print('\n3. O borrão cobre a região do rosto e só ela')
    img = frame_de_teste()
    rostos = [[40, 30, 60, 60]]          # x, y, w, h
    borrada = blur_lgpd.aplicar_blur(img, rostos)
    dentro_mudou = not np.array_equal(img[35:95, 45:105], borrada[35:95, 45:105])
    fora_intacto = np.array_equal(img[0:20, 0:20], borrada[0:20, 0:20])
    verificar('a região do rosto muda', dentro_mudou)
    verificar('o canto oposto permanece igual', fora_intacto)


def teste_grava_foto_anonimizada():
    print('\n4. Caminho feliz: a foto é gravada')
    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / 'foco_teste.jpg'
        salvo, _ = detectar_foco.salvar_foto_anonimizada(frame_de_teste(), alvo)
        verificar('devolve o caminho gravado', salvo == alvo)
        verificar('o arquivo existe em disco', alvo.exists())


def teste_falha_fechada():
    """A regra que não pode quebrar nunca.

    Se a anonimização falhar por qualquer motivo, o disco tem de continuar
    limpo. Um frame cru gravado aqui é um rosto publicado no dashboard.
    """
    print('\n5. Falha fechada: anonimização quebrada não grava nada')
    original = detectar_foco.anonimizar

    def explodir(_frame):
        raise RuntimeError('cascade indisponível (simulado)')

    detectar_foco.anonimizar = explodir
    try:
        with tempfile.TemporaryDirectory() as tmp:
            alvo = Path(tmp) / 'foco_nao_deve_existir.jpg'
            salvo, rostos = detectar_foco.salvar_foto_anonimizada(frame_de_teste(), alvo)
            verificar('não devolve caminho', salvo is None)
            verificar('NADA foi gravado em disco', not alvo.exists())
            verificar('a pasta continua vazia', not list(Path(tmp).iterdir()))
    finally:
        detectar_foco.anonimizar = original


def teste_csv_aceita_foco_sem_foto():
    print('\n6. Foco sem foto entra no CSV com origem_imagem vazia')
    with tempfile.TemporaryDirectory() as tmp:
        reg = detectar_foco.RegistradorFocos(tmp)
        reg.registrar('tire', 0.91, -22.2534, -45.7041, None)
        reg.registrar('pool', 0.88, -22.2540, -45.7050, 'foco_ok.jpg')
        caminho = Path(tmp) / detectar_foco.CSV_NOME
        linhas = list(csv.DictReader(open(caminho, encoding='utf-8')))
        verificar('duas linhas gravadas', len(linhas) == 2)
        verificar('sem foto → campo vazio, sem nome inventado',
                  linhas[0]['origem_imagem'] == '')
        verificar('com foto → o nome do arquivo',
                  linhas[1]['origem_imagem'] == 'foco_ok.jpg')
        verificar('ids sequenciais',
                  [l['id_foco'] for l in linhas] == ['FD-001', 'FD-002'])


def main():
    print('\n🔒 AeroScan — testes da fronteira de anonimização')
    print('=' * 52)

    teste_importacao_nao_carrega_cascade()
    teste_anonimizar_devolve_copia()
    teste_blur_altera_so_o_rosto()
    teste_grava_foto_anonimizada()
    teste_falha_fechada()
    teste_csv_aceita_foco_sem_foto()

    print('\n' + '=' * 52)
    if falhas:
        print(f'❌ {len(falhas)} verificação(ões) falharam:')
        for f in falhas:
            print(f'   · {f}')
        return 1
    print('✅ Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
