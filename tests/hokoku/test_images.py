from hokoku.images import fit, natural_width_cm, split_tall, size_px


def test_fit_and_natural(png):
    assert size_px(png) == (200, 100)
    assert abs(natural_width_cm(png) - 200 / 96 * 2.54) < 0.01
    w, h = fit(png, 16.0, 24.0)                 # естественная ширина < страницы
    assert abs(w - 5.29) < 0.05 and abs(h - w / 2) < 0.01
    w, h = fit(png, 16.0, 24.0, want_w_cm=30)   # запрошенная шире страницы → страница
    assert w == 16.0
    w, h = fit(png, 16.0, 2.0)                  # ограничение по высоте
    assert h == 2.0 and w == 4.0


def test_split_tall_cuts_on_blank_rows(tall_png):
    pieces = split_tall(tall_png, max_ratio=1.5, connectors=False)
    assert len(pieces) >= 3
    heights = [size_px(p)[1] for p in pieces]
    assert sum(heights) == 2000
    assert all(h <= 600 for h in heights)
    assert split_tall(tall_png, max_ratio=10) == [tall_png]


def test_split_connectors_add_margins(tall_png):
    plain = split_tall(tall_png, max_ratio=1.5, connectors=False)
    with_c = split_tall(tall_png, max_ratio=1.5, connectors=True)
    assert len(plain) == len(with_c)
    hp = [size_px(p)[1] for p in plain]
    hc = [size_px(p)[1] for p in with_c]
    assert hc[0] > hp[0] and hc[-1] > hp[-1]                     # снизу первого и сверху последнего — кружок
    assert all(c - p >= 48 for p, c in zip(hp, hc))
