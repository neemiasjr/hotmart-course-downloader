import sys
import types
import unittest
from unittest import mock

from hotmart_downloader.config import (
    _carregar_desempenho,
    _cursos_subdominios,
    _product_id_por_subdominio,
    valor,
)


def _config(**valores):
    return mock.patch.dict(sys.modules, {'config_cursos': types.SimpleNamespace(**valores)})


class ConfigTest(unittest.TestCase):
    def test_sem_arquivo_usa_padroes(self):
        with mock.patch.dict(sys.modules, {'config_cursos': None}):
            self.assertEqual(valor('QUALIDADE_VIDEO', 720), 720)
            desempenho = _carregar_desempenho()
        self.assertEqual(desempenho['download_paralelo'], 1)
        self.assertEqual(desempenho['api_paralelo'], 6)
        self.assertTrue(desempenho['verificar_video_completo'])

    def test_variaveis_ausentes_nao_quebram(self):
        with _config(CURSOS_SUBDOMINIOS=['curso-a']):
            self.assertEqual(_carregar_desempenho()['fluidao_preset'], 'faster')

    def test_limites_e_valores_invalidos(self):
        with _config(DOWNLOAD_PARALELO=10, API_PARALELO='x', FRACAO_DURACAO_MINIMA=0.1):
            desempenho = _carregar_desempenho()
        self.assertEqual(desempenho['download_paralelo'], 4)
        self.assertEqual(desempenho['api_paralelo'], 6)
        self.assertEqual(desempenho['fracao_duracao_minima'], 0.5)

    def test_subdominios_e_product_id(self):
        with _config(
            CURSOS_SUBDOMINIOS=[' curso-a ', '', None, 'curso-b'],
            CURSOS_PRODUCT_IDS={'curso-a': 123},
            HOTMART_PRODUCT_ID='999',
        ):
            self.assertEqual(_cursos_subdominios(), ['curso-a', 'curso-b'])
            self.assertEqual(_product_id_por_subdominio('curso-a'), '123')
            self.assertEqual(_product_id_por_subdominio('curso-b'), '999')


if __name__ == '__main__':
    unittest.main()
