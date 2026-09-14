from hokoku.images import count_pages, fit, natural_width_cm, size_px


def test_fit_and_natural(png):
    assert size_px(png) == (200, 100)
    assert abs(natural_width_cm(png) - 200 / 96 * 2.54) < 0.01
    w, h = fit(png, 16.0, 24.0)                 # естественная ширина < страницы
    assert abs(w - 5.29) < 0.05 and abs(h - w / 2) < 0.01
    w, h = fit(png, 16.0, 24.0, want_w_cm=30)   # запрошенная шире страницы → страница
    assert w == 16.0
    w, h = fit(png, 16.0, 2.0)                  # ограничение по высоте
    assert h == 2.0 and w == 4.0


def test_drawio_png_is_cached_by_content(monkeypatch, png):
    """Запуск drawio стоит секунды и зависит только от XML — второй раз берём из кэша."""
    import shutil
    import subprocess

    from hokoku import images
    images.clear_png_cache()
    calls = []
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/true" if name == "drawio" else None)

    class Подделка:
        """Столько от `Popen`, сколько читает вызов: PNG на месте и пустой вывод.

        Процесс заводится своей группой и снимается по таймауту целиком, поэтому
        запускается он `Popen`, а не `run`: подделка повторяет ту же пару
        `Popen` — `communicate`, иначе проверка ушла бы мимо настоящего вызова.
        """

        returncode = 0

        def __init__(self, cmd, **kw):
            calls.append(cmd)
            with open(cmd[cmd.index("-o") + 1], "wb") as f:
                f.write(png)

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(subprocess, "Popen", Подделка)
    try:
        assert images.drawio_to_png("<mxfile>a</mxfile>") == png
        # Оба флага Electron на месте: без песочницы он падает в контейнере, без
        # `--disable-dev-shm-usage` виснет на схеме крупнее мегапикселя.
        assert {"--no-sandbox", "--disable-dev-shm-usage"} <= set(calls[0])
        assert images.drawio_to_png("<mxfile>a</mxfile>") == png
        assert len(calls) == 1                                  # второй раз drawio не запускался
        images.drawio_to_png("<mxfile>b</mxfile>")
        images.drawio_to_png("<mxfile>a</mxfile>", cache=False)
        assert len(calls) == 3                                  # другой XML и cache=False считаются
    finally:
        images.clear_png_cache()
