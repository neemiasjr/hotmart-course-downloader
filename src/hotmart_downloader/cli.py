"""Linha de comando: autentica e inicia o download."""

from .auth import autenticacao
from .curso import listacursos

# Para não digitar sempre, troque LOGIN por {"email": "EMAIL@EMAIL", "senha": "SENHA"}.
LOGIN = {
    "Info": "Pode colocar o email/senha em LOGIN (cli.py) para deixar os dados salvos no script",
    "autor": "Telegram: @katomaro",
}


def main():
    try:
        listacursos(*autenticacao(**LOGIN))
    except KeyboardInterrupt:
        print(
            "\n\nDownload interrompido. Rode o script de novo, escolha o mesmo curso "
            "e confirme 'Continuar de onde parou'.\n"
            "Arquivos já baixados serão pulados; o vídeo incompleto reinicia.\n"
        )
