import contextlib
import io
import os
import tempfile
import unittest

from hotmart_downloader.migracao import _migrar_nomes_legados_topico, _migrar_pasta_legada


def _criar(caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write('x')


class MigracaoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.curso = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_renomeia_arquivos_do_padrao_antigo(self):
        topico = os.path.join(self.curso, '1 - Comece por aqui')
        for nome in (
            '8.yakissoba.mp4',
            '8.yakissoba-v2.mp4',
            '8.yakissoba-extra.mp4',
            '8.yakissoba.part.mp4',
            'descricoes/8.yakissoba.html',
            'Materiais/8.yakissoba_receita.pdf',
        ):
            _criar(os.path.join(topico, nome))

        aulas = [(8, 'Yakissoba'), (8, 'Yakissoba Extra')]
        self.assertEqual(_migrar_nomes_legados_topico(topico, aulas, self.curso), 5)
        self.assertEqual(sorted(os.listdir(topico)), [
            '8 - Yakissoba (vídeo 2).mp4',
            '8 - Yakissoba Extra.mp4',
            '8 - Yakissoba.mp4',
            '8.yakissoba.part.mp4',
            'Materiais',
            'descricoes',
        ])
        self.assertEqual(os.listdir(os.path.join(topico, 'descricoes')), ['8 - Yakissoba.html'])
        self.assertEqual(
            os.listdir(os.path.join(topico, 'Materiais')), ['8 - Yakissoba - receita.pdf'],
        )

    def test_renomeia_pasta_antiga_so_se_a_nova_nao_existir(self):
        os.makedirs(os.path.join(self.curso, '1_comece-por-aqui'))
        destino = os.path.join(self.curso, '1 - Comece por aqui')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(_migrar_pasta_legada(destino, ['1_comece-por-aqui'], self.curso))
        self.assertTrue(os.path.isdir(destino))
        self.assertFalse(_migrar_pasta_legada(destino, ['1_comece-por-aqui'], self.curso))


if __name__ == '__main__':
    unittest.main()
