"""The whole app in a real browser (simulation mode). Needs the playwright
package and Chrome/Chromium; skipped otherwise. CHROME=/path/to/chrome picks
the browser."""

from __future__ import annotations

import os
import shutil
import threading

import pytest

from spherex.server import UI_DIR, make_server

sync_api = pytest.importorskip("playwright.sync_api")


def chrome_path():
    for p in (os.environ.get("CHROME"), shutil.which("google-chrome"), shutil.which("chromium"),
              shutil.which("chromium-browser")):
        if p and os.path.exists(p):
            return p
    return None


@pytest.fixture(scope="module")
def page():
    exe = chrome_path()
    if exe is None:
        pytest.skip("no Chrome or Chromium found")
    httpd = make_server(("127.0.0.1", 0), UI_DIR, None)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.base = base
        pg.errors = errors
        yield pg
        browser.close()
    httpd.shutdown()


def state(pg, expr):
    return pg.evaluate(f"() => {expr}")


def test_play_select_and_switch(page):
    pg = page
    pg.goto(pg.base + "/?target=barnard&level=analyze&catalog=1&mode=diff&play=0&debug=1&lang=en")
    pg.wait_for_function("() => skyState.field && skyState.done === skyState.total && skyState.frame?.loaded",
                         timeout=30000)
    assert state(pg, "skyState.real") is False
    assert "Simulated" in pg.locator("#banner").inner_text()
    assert state(pg, "skyState.field.name") == "Barnard's Star"
    # The canvas shows something other than the background.
    assert state(pg, """(() => { const c = document.getElementById('canvas');
        const d = c.getContext('2d').getImageData(c.width / 2 - 150, c.height / 2 - 150, 300, 300).data;
        let s = new Set(); for (let i = 0; i < d.length; i += 4) s.add(d[i]); return s.size; })()""") > 5

    box = pg.locator("#canvas").bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + 5)
    pg.wait_for_function("() => skyState.selection && skyState.selection.measurements.length > 50", timeout=10000)
    sel = state(pg, "skyState.selection")
    assert sel["moving"] and sel["catalog"]["name"] == "Barnard's Star"
    assert "matches the catalog" in pg.locator("#motion").inner_text()
    assert pg.locator("#spectrum circle").count() > 50

    pg.keyboard.press("e")
    pg.keyboard.press("ArrowRight")
    pg.wait_for_function("() => skyState.frame.mode === 'epoch' && skyState.frame.visit === skyState.view.visit")
    pg.keyboard.press("s")
    pg.wait_for_function("() => skyState.frame.mode === 'sum'")
    pg.keyboard.press("6")
    pg.wait_for_function("() => skyState.frame.band === 5")
    pg.keyboard.press(" ")
    pg.wait_for_timeout(1500)
    pg.keyboard.press(" ")
    assert state(pg, "skyState.view.visit") > 1

    pg.fill("#q", "R Dra")
    pg.keyboard.press("Enter")
    pg.wait_for_function("() => skyState.field?.name === 'R Draconis'", timeout=10000)
    assert pg.errors == []


def test_doors_tour_and_challenge(page):
    pg = page
    pg.goto(pg.base + "/?debug=1&lang=es")
    pg.wait_for_function("() => document.querySelectorAll('.tour-card').length === 3", timeout=15000)
    assert pg.locator(".door").count() == 3
    pg.click("#tab-discover")
    assert pg.locator(".levels button[aria-checked='true']").inner_text() == "Descubre"
    assert pg.locator("#door-discover .object").count() >= 28

    # Guided tour "Lo que se mueve": Barnard in Difference with the catalog layer.
    pg.click("#tab-learn")
    pg.locator(".tour-card").nth(1).click()
    pg.wait_for_function("() => skyState.field?.name === \"Barnard's Star\" && skyState.frame?.loaded", timeout=30000)
    assert state(pg, "skyState.frame.mode") == "diff" and state(pg, "skyState.view.catalog")
    assert "Paso 1 de 4" in pg.locator("#tour-count").inner_text()
    pg.click("#tour-next")
    pg.wait_for_function("() => skyState.field?.name === 'Epsilon Indi B'", timeout=30000)
    pg.click("#tour-exit")
    assert pg.locator("#tour").is_hidden()

    # Challenge: the name is hidden until the moving star is clicked.
    pg.goto(pg.base + "/?debug=1&lang=es")
    pg.wait_for_function("() => document.querySelectorAll('.door').length === 3")
    pg.click("#tab-discover")
    pg.click("#challenge-start")
    pg.wait_for_function("() => skyState.field && skyState.done === skyState.total && skyState.frame?.loaded", timeout=30000)
    assert pg.locator("#field-name").inner_text() == "Campo misterioso"
    box = pg.locator("#canvas").bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + 3)
    pg.wait_for_function("() => document.getElementById('challenge-result').classList.contains('good')", timeout=15000)
    assert pg.locator("#field-name").inner_text() != "Campo misterioso"
    # Bands are explained under the spectrum.
    assert pg.locator("#bands li").count() == 8
    assert pg.errors == []
