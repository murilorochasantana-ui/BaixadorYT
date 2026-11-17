"""Modo Claude: divide vídeos grandes em partes que cabem no limite de upload do Claude (copiado do app antigo)."""
import glob
import math
import os

from .ffmpeg import exe_ffmpeg, rodar_cancelavel


def dividir(arquivo, duracao, limite_mb, avisar=lambda t: None, checar=lambda: None):
    """Divide o arquivo em partes de no máximo limite_mb, sem perder qualidade (sem recodificar).
    Retorna a lista de partes, ou [arquivo] se ele já couber.
    `checar` pode lançar exceção (pausar/cancelar): o ffmpeg é encerrado na hora e as partes apagadas."""
    limite = limite_mb * 1024 * 1024
    tamanho = os.path.getsize(arquivo)
    if tamanho <= limite:
        return [arquivo]
    pasta = os.path.dirname(arquivo)
    nome, ext = os.path.splitext(os.path.basename(arquivo))
    if not duracao:
        duracao = 0
    partes_n = math.ceil(tamanho / (limite * 0.92))  # margem: cortes caem em keyframes
    for _tentativa in range(8):
        for velho in glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")):
            os.remove(velho)
        avisar(f"Dividindo em {partes_n} partes...")
        seg = max(duracao / partes_n, 5) if duracao else 600
        modelo = os.path.join(pasta, f"{nome} - Parte %02d{ext}")
        try:
            r = rodar_cancelavel([exe_ffmpeg(), "-hide_banner", "-y", "-nostdin", "-i", arquivo, "-map", "0",
                                  "-c", "copy", "-f", "segment", "-segment_time", f"{seg:.2f}",
                                  "-segment_start_number", "1", "-reset_timestamps", "1", modelo], checar)
        except BaseException:
            for velho in glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")):
                os.remove(velho)
            raise
        if r.returncode != 0:
            raise RuntimeError("O ffmpeg falhou ao dividir: " + r.stderr.decode(errors="ignore")[-300:])
        partes = sorted(glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")))
        if partes and all(os.path.getsize(x) <= limite for x in partes):
            os.remove(arquivo)  # fica só com as partes
            return partes
        partes_n = math.ceil(partes_n * 1.25) + 1
    for velho in glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")):
        os.remove(velho)  # não deixa partes pela metade: o original continua inteiro
    raise RuntimeError("Não consegui deixar todas as partes abaixo do limite. Aumente o limite do Modo Claude.")
