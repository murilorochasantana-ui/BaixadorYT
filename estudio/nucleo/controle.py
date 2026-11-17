"""Exceção usada para pausar/cancelar de dentro de qualquer ponto do download."""


class Interrompido(Exception):
    """Lançada pelos ganchos quando o usuário pausa ou cancela (motivo: "pausar" ou "cancelar")."""
    def __init__(self, motivo):
        super().__init__(f"interrompido: {motivo}")
        self.motivo = motivo
