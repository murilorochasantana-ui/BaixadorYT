"""Transforma erros do yt-dlp em mensagens em português dizendo o que fazer (copiado do app antigo)."""
import re

DICA_LOGIN = "\"Login (+18 / Instagram)\""


def limpar_mensagem(e):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    return msg.split("; please report")[0].strip()


def explicar_erro(msg, login):
    m = msg.lower()
    if "sign in to confirm your age" in m or "age-restricted" in m:
        if login == "Nenhum":
            return ("Esse vídeo tem restrição de idade e o YouTube só libera para quem está logado.\n\n"
                    f"Em {DICA_LOGIN}, escolha o navegador onde você está logado no YouTube "
                    "(o Firefox é o que funciona melhor) e tente de novo.")
        return ("Mesmo com o login, o YouTube não liberou. Confira se a conta logada nesse navegador "
                "é maior de 18 anos e está entrando no YouTube normalmente.")
    if "is_live" in m or "live event" in m or "está ao vivo" in m or "live acontecendo" in m:
        return msg
    if any(x in m for x in ("login required", "requested content is not available",
                            "rate-limit", "rate limit", "empty media response", "only available for registered",
                            "you need to log in", "cookies")) and "cookies database" not in m:
        if login == "Nenhum":
            return ("Esse site pediu login para liberar o vídeo (o Instagram e o Facebook fazem isso muito).\n\n"
                    f"Em {DICA_LOGIN}, escolha o navegador onde você está logado nesse site "
                    "e tente de novo.")
        return ("Mesmo com o login o site não liberou. Confira se você está logado nesse site pelo navegador "
                "escolhido e se o post é público ou você segue o perfil.")
    if "private" in m or "privado" in m:
        return "Esse vídeo é privado. Só dá para baixar se a sua conta (no navegador escolhido) tiver acesso."
    if "no video" in m and "pinterest" in m:
        return "Esse Pin não tem vídeo (é só imagem)."
    if "not a bot" in m:
        return ("O YouTube pediu para confirmar que você não é um robô.\n\n"
                f"Escolha um navegador em {DICA_LOGIN} e tente de novo. Se continuar, espere alguns minutos.")
    if "could not copy" in m and "cookie" in m:
        return ("Não consegui ler o login do navegador porque ele está aberto.\n\n"
                "Feche o navegador por completo e tente de novo, ou use o Firefox.")
    if "dpapi" in m or "app-bound" in m or "failed to decrypt" in m:
        return ("O Chrome/Edge bloqueia a leitura do login por outros programas.\n\n"
                "Use o Firefox (entre no site por ele uma vez) ou a opção \"Arquivo cookies.txt\".")
    if "could not find" in m and "cookies database" in m:
        return f"Não achei esse navegador instalado ou ele nunca foi aberto. Escolha outro em {DICA_LOGIN}."
    if "requested format is not available" in m:
        return ("Esse formato não existe para esse vídeo.\n\n"
                "Escolha outra qualidade, ou use \"Avançado\" para ver os formatos que o vídeo realmente tem.")
    if "abaixo do limite" in m or "falhou ao dividir" in m or "ler o áudio" in m:
        return msg  # erros do próprio Estúdio já explicam o que fazer
    if "no space left" in m or "errno 28" in m:
        return "O disco ficou cheio. Libere espaço na pasta de destino (ou escolha outra pasta) e tente de novo."
    return msg + "\n\nDica: rode o atualizar.bat e tente de novo."
