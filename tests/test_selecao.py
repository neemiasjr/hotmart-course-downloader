import contextlib
import io
import unittest

from hotmart_downloader.selecao import (
    _aula_apenas_videos,
    _indices_config_para_raw,
    _parse_escopo_aulas,
    _parse_selecao_numeros,
    _parse_selecao_topicos,
    _serializar_videos_por_aula,
    _video_incluido_no_escopo,
)


def _silencioso(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class SelecaoNumerosTest(unittest.TestCase):
    def test_todos(self):
        for raw in ('', '0', 'todos', '*'):
            self.assertEqual(_parse_selecao_numeros(raw, 3), {1, 2, 3})

    def test_lista_intervalo_e_fora_da_faixa(self):
        self.assertEqual(_parse_selecao_numeros('1,3', 5), {1, 3})
        self.assertEqual(_parse_selecao_numeros('4-2', 5), {2, 3, 4})
        self.assertEqual(_parse_selecao_numeros('2-9', 3), {2, 3})

    def test_invalido_cai_em_todos_ou_vazio(self):
        self.assertEqual(_silencioso(_parse_selecao_numeros, 'x', 2), {1, 2})
        self.assertEqual(_silencioso(_parse_selecao_numeros, 'x', 2, fallback_todos=False), set())


class SelecaoTopicosTest(unittest.TestCase):
    def test_topicos_e_aulas_dentro_do_topico(self):
        self.assertEqual(_parse_selecao_topicos('1,3', 4), ({1, 3}, {}))
        self.assertEqual(_parse_selecao_topicos('5:2-4', 5), ({5}, {5: {2, 3, 4}}))

    def test_topico_fora_da_lista_e_ignorado(self):
        self.assertEqual(_silencioso(_parse_selecao_topicos, '2,9', 3), ({2}, {}))


class EscopoAulasTest(unittest.TestCase):
    def test_aulas_e_videos(self):
        aulas, videos = _parse_escopo_aulas('1,3:v2', 4)
        self.assertEqual(aulas, {1, 3})
        self.assertEqual(videos, {3: {2}})
        self.assertTrue(_video_incluido_no_escopo(3, 2, videos))
        self.assertFalse(_video_incluido_no_escopo(3, 1, videos))
        self.assertTrue(_video_incluido_no_escopo(1, 5, videos))
        self.assertTrue(_aula_apenas_videos(3, videos))
        self.assertFalse(_aula_apenas_videos(1, videos))
        self.assertEqual(_serializar_videos_por_aula(videos), {'3': [2]})

    def test_indices_do_config(self):
        self.assertIsNone(_indices_config_para_raw(None))
        self.assertEqual(_indices_config_para_raw(' 1-2 '), '1-2')
        self.assertEqual(_indices_config_para_raw([1, 2]), '1,2')
        self.assertEqual(_silencioso(_indices_config_para_raw, -1), '-1')


if __name__ == '__main__':
    unittest.main()
