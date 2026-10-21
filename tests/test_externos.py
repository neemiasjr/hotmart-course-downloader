import unittest

from hotmart_downloader.externos import (
    _formato_ytdlp,
    _listar_links_video_externo,
    _normalizar_url_youtube,
)


class LinksExternosTest(unittest.TestCase):
    def test_normaliza_youtube_para_watch(self):
        for url in (
            '//www.youtube.com/embed/dQw4w9WgXcQ?rel=0',
            'https://youtu.be/dQw4w9WgXcQ',
            'https://www.youtube.com/live/dQw4w9WgXcQ',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30',
        ):
            self.assertEqual(
                _normalizar_url_youtube(url), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            )

    def test_varios_videos_do_youtube_na_mesma_aula(self):
        html = (
            '<iframe src="https://www.youtube.com/embed/aaaaaaaaaaa"></iframe>'
            '<a href="https://youtu.be/bbbbbbbbbbb">2</a>'
            '<a href="https://youtu.be/aaaaaaaaaaa">repetido</a>'
        )
        self.assertEqual(_listar_links_video_externo(html, [], None), [
            'https://www.youtube.com/watch?v=aaaaaaaaaaa',
            'https://www.youtube.com/watch?v=bbbbbbbbbbb',
        ])

    def test_api_vimeo_e_wistia(self):
        html = (
            '<iframe data-src="https://player.vimeo.com/video/123?h=abc"></iframe>'
            '<a href="https://vimeo.com/123/">mesmo vídeo</a>'
            '<iframe src="https://fast.wistia.com/embed/x"></iframe>'
        )
        registros = [
            ['a', 'id', 'https://www.youtube.com/watch?v=ccccccccccc'],
            ['b', 'id2', 'https://cf-embed.play.hotmart.com/embed/x'],
        ]
        self.assertEqual(_listar_links_video_externo(html, registros, None), [
            'https://www.youtube.com/watch?v=ccccccccccc',
            'https://player.vimeo.com/video/123?h=abc',
        ])

    def test_formato_por_qualidade(self):
        self.assertEqual(_formato_ytdlp(0), 'bestvideo+bestaudio/best')
        self.assertEqual(
            _formato_ytdlp(720), 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        )


if __name__ == '__main__':
    unittest.main()
