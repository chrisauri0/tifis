"""The whole app in a real browser (simulation mode). Needs the playwright
package and Chrome/Chromium; skipped otherwise. CHROME=/path/to/chrome picks
the browser."""

from __future__ import annotations

import os
import shutil
import threading

import pytest

from spherex.features import FEATURES
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


def test_doors_and_guided_tour(page):
    pg = page
    pg.set_viewport_size({"width": 1400, "height": 900})
    pg.goto(pg.base + "/?debug=1&lang=es")
    pg.wait_for_function("() => document.querySelectorAll('.tour-card').length === 3", timeout=15000)
    assert pg.locator(".door").count() == 3
    assert pg.locator(".how li").count() == 4
    pg.click("#tab-discover")
    assert pg.locator(".levels button[aria-checked='true']").inner_text() == "Descubre"
    assert pg.locator("#door-discover .object").count() >= 28
    assert pg.locator(".mission-card").count() == 3

    # Tour "Lo que se mueve": the tasks check themselves off as they are done.
    pg.click("#tab-learn")
    pg.locator(".tour-card").nth(1).click()
    pg.wait_for_function("() => skyState.field?.name === \"Barnard's Star\" && skyState.frame?.loaded", timeout=30000)
    assert state(pg, "skyState.frame.mode") == "diff"
    assert not state(pg, "skyState.playing") and not state(pg, "skyState.view.catalog")
    assert "Paso 1 de 4" in pg.locator("#tour-count").inner_text()
    assert pg.locator("#tour-tasks li").count() == 2
    assert pg.locator("#tour-takeaway").is_hidden()
    assert pg.locator("#tour-next").inner_text() == "Saltar paso →"
    # The control of the first pending task pulses.
    assert "coach" in pg.locator("#play").get_attribute("class")
    pg.locator("#tour-tasks li.current .helper").click()  # ▶ Play
    pg.wait_for_function("() => document.querySelector('#tour-tasks li').classList.contains('done')", timeout=20000)
    pg.locator("#tour-tasks li.current .helper").click()  # catalog layer
    pg.wait_for_function("() => !document.getElementById('tour-takeaway').hidden", timeout=10000)
    assert state(pg, "skyState.view.catalog")
    assert "Gaia" in pg.locator("#tour-takeaway").inner_text()
    assert pg.locator("#tour-next").inner_text() == "Siguiente →"
    assert "coach" in pg.locator("#tour-next").get_attribute("class")
    # The "what you are seeing" panel names the object and the mode.
    now = pg.locator("#now").inner_text()
    assert "Barnard's Star" in now and "Diferencia" in now and "Canal 2" in now

    pg.click("#tour-next")
    pg.wait_for_function("() => skyState.field?.name === 'Epsilon Indi B' && skyState.frame?.loaded", timeout=30000)
    pg.keyboard.press("Escape")
    # A click far from the object does not count, and says so.
    box = pg.locator("#canvas").bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2 - 200, box["y"] + box["height"] / 2 - 200)
    pg.wait_for_function("() => !!skyState.selection", timeout=10000)
    pg.wait_for_function("() => !!document.querySelector('#tour-tasks .note')", timeout=5000)

    # Skip to the end: the quick question.
    for _ in range(3):
        pg.click("#tour-next")
    pg.wait_for_function("() => !document.getElementById('tour-quiz').hidden", timeout=30000)
    assert pg.locator("#tour-quiz .quiz-options button").count() == 3
    pg.locator("#tour-quiz .quiz-options button").nth(1).click()
    assert "¡Correcto!" in pg.locator("#tour-quiz .result").inner_text()
    pg.click("#tour-exit")
    assert pg.locator("#tour").is_hidden()
    assert pg.errors == []


def click_center(pg, dy=0):
    box = pg.locator("#canvas").bounding_box()
    pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + dy)


def open_mission(pg, mission, obj):
    pg.goto(pg.base + "/?debug=1&lang=es")
    pg.wait_for_function("() => document.querySelectorAll('.mission-card').length === 3")
    pg.click("#tab-discover")
    # Pin the random pick so the test knows the answer.
    pg.evaluate("(o) => { Math.random = () => 0; }", obj)
    pg.locator(f".mission-card[data-mission='{mission}']").click()
    pg.wait_for_function("() => skyState.field && skyState.done === skyState.total && skyState.frame?.loaded", timeout=30000)
    assert state(pg, "skyState.challenge.obj") == obj
    assert pg.locator("#field-name").inner_text() == "Campo misterioso"
    assert "misterioso" in pg.locator("#now-what").inner_text()


def test_missions(page):
    pg = page
    pg.set_viewport_size({"width": 1400, "height": 900})
    pg.evaluate("() => localStorage.removeItem('sky.score')") if pg.url.startswith("http") else None

    # Find what moves: answered on the click, checked against the catalog.
    open_mission(pg, "moving", "barnard")
    click_center(pg, 3)
    pg.wait_for_function("() => document.getElementById('challenge-result').classList.contains('good')", timeout=15000)
    assert pg.locator("#field-name").inner_text() != "Campo misterioso"
    # One entry per feature in the server's table (spherex/features.py).
    assert pg.locator("#bands li").count() == len(FEATURES)

    # Pulse or flicker: play, click the star, then the question appears.
    open_mission(pg, "rhythm", "r-dra")
    assert pg.locator("#challenge-question").is_hidden()
    pg.click("#play")
    pg.wait_for_function("() => skyState.challenge.done[0]", timeout=20000)
    pg.click("#play")
    click_center(pg)
    pg.wait_for_function("() => document.querySelectorAll('#challenge-question .quiz-options button').length === 2", timeout=15000)
    pg.locator("#challenge-question .quiz-options button").nth(0).click()  # periodic
    assert "¡Correcto!" in pg.locator("#challenge-result").inner_text()
    assert "R Dra" in pg.locator("#challenge-result").inner_text()

    # Hot or cold: the answer comes from the measurements themselves.
    open_mission(pg, "temperature", "barnard")
    assert state(pg, "skyState.view.band") == 0
    pg.locator("#channels .channel").nth(5).click()
    click_center(pg)
    pg.wait_for_function("() => document.querySelectorAll('#challenge-question .quiz-options button').length === 3", timeout=20000)
    # Choosing channel 6 scrolled the side panel down; the question is back in view.
    pg.wait_for_function("""() => { const q = document.getElementById('challenge-question').getBoundingClientRect();
        const side = document.querySelector('.side').getBoundingClientRect();
        return q.top >= side.top && q.bottom <= side.bottom; }""", timeout=5000)
    pg.locator("#challenge-question .quiz-options button").nth(2).click()  # long: wrong for Barnard
    res = pg.locator("#challenge-result")
    assert "No." in res.inner_text() and "K" in res.inner_text() and "Barnard" in res.inner_text()
    assert "bad" in res.get_attribute("class")
    assert pg.locator("#challenge-question .right").count() == 1

    pg.click("#challenge-next")
    pg.wait_for_function("() => skyState.challenge.obj !== 'barnard' && skyState.field", timeout=30000)
    pg.click("#challenge-exit")
    pg.goto(pg.base + "/?debug=1&lang=es")
    pg.wait_for_function("() => document.querySelectorAll('.mission-card').length === 3")
    assert pg.locator("#score").inner_text() == "Aciertos: 2 de 3"
    assert pg.errors == []


def test_home_hides_player_and_side_panel(page):
    pg = page

    def shown(sel):
        return pg.locator(sel).is_visible()

    for width, height in ((1400, 900), (420, 860)):
        pg.set_viewport_size({"width": width, "height": height})
        pg.goto(pg.base + "/?debug=1&lang=es")
        pg.wait_for_function("() => document.querySelectorAll('.tour-card').length === 3", timeout=15000)
        assert state(pg, "document.body.classList.contains('home')")
        assert not shown(".transport") and not shown(".side")
        # The welcome fills the width the side panel used to take.
        assert pg.locator("#welcome").bounding_box()["width"] >= width - 20
        assert pg.locator(".door").nth(0).is_visible()

        # Opening an object brings the player, the timeline and the panel.
        pg.locator("#cards .card").first.click()
        pg.wait_for_function("() => skyState.field && skyState.frame?.loaded", timeout=30000)
        assert not state(pg, "document.body.classList.contains('home')")
        assert shown(".transport") and shown(".side") and shown("#timeline")
        assert pg.locator("#welcome").is_hidden()

    # A deep link opens straight into the viewer, never on the home screen.
    pg.set_viewport_size({"width": 1400, "height": 900})
    pg.goto(pg.base + "/?target=barnard&debug=1")
    assert not state(pg, "document.body.classList.contains('home')")
    pg.wait_for_function("() => skyState.field && skyState.frame?.loaded", timeout=30000)
    assert shown(".transport") and shown(".side")
    assert pg.errors == []
