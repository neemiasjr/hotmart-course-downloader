import unittest

from hotmart_downloader.caminhos import (
    _caminho_anexo_aula,
    _caminho_descricao_aula,
    _caminho_video_no_topico,
)
from hotmart_downloader.nomes import (
    _nome_arquivo_corresponde_aula,
    _nome_fiel,
    _nome_pasta_topico,
    _nome_pasta_topico_legado,
    _prefixo_aula,
    _prefixo_aula_legado,
)


class NomeFielTest(unittest.TestCase):
    def test_mantem_acentos_maiusculas_e_espacos(self):
        self.assertEqual(_nome_fiel('Comece por aqui'), 'Comece por aqui')
        self.assertEqual(_nome_fiel('Introdução à Música'), 'Introdução à Música')

    def test_troca_separadores_e_remove_proibidos(self):
        self.assertEqual(_nome_fiel('Aula 1: Harmonia | Parte 2'), 'Aula 1 - Harmonia - Parte 2')
        self.assertEqual(_nome_fiel('E agora? <Fim>*'), 'E agora Fim')

    def test_limita_tamanho_e_evita_nomes_reservados_do_windows(self):
        self.assertEqual(len(_nome_fiel('a' * 300)), 120)
        self.assertEqual(_nome_fiel('CON'), 'CON_')


class PadraoDeNomesTest(unittest.TestCase):
    def test_pasta_do_topico(self):
        self.assertEqual(_nome_pasta_topico(1, 'Comece por aqui'), '1 - Comece por aqui')
        self.assertEqual(_nome_pasta_topico_legado(1, 'Comece por aqui'), '1_comece-por-aqui')

    def test_prefixos_da_aula(self):
        self.assertEqual(_prefixo_aula(8, 'Yakissoba'), '8 - Yakissoba')
        self.assertEqual(_prefixo_aula_legado(8, 'Yakissoba'), '8.yakissoba')

    def test_caminhos_dentro_do_topico(self):
        self.assertEqual(_caminho_video_no_topico('T', 2, 'Aula', 1), 'T/2 - Aula.mp4')
        self.assertEqual(
            _caminho_video_no_topico('T', 2, 'Aula', 3, total_videos=3), 'T/2 - Aula (vídeo 3).mp4',
        )
        self.assertEqual(_caminho_descricao_aula('T', 2, 'Aula'), 'T/descricoes/2 - Aula.html')
        self.assertEqual(_caminho_anexo_aula('T', 2, 'Aula', 'a.pdf'), 'T/Materiais/2 - Aula - a.pdf')

    def test_reconhece_video_da_aula_em_qualquer_padrao(self):
        self.assertTrue(_nome_arquivo_corresponde_aula('8 - Yakissoba.mp4', 8, 'Yakissoba'))
        self.assertTrue(_nome_arquivo_corresponde_aula('8.yakissoba.mp4', 8, 'Yakissoba'))
        self.assertFalse(_nome_arquivo_corresponde_aula('8 - Yakissoba.part.mp4', 8, 'Yakissoba'))
        self.assertFalse(_nome_arquivo_corresponde_aula('9 - Sushi.mp4', 8, 'Yakissoba'))


if __name__ == '__main__':
    unittest.main()
