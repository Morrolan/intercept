"""Flipper source uses bounded receive controls, not SDR gain/availability."""

import json

import pytest
from playwright.sync_api import expect

from .test_pages_load import INIT_SCRIPT


@pytest.mark.parametrize("theme,width", [("dark", 1600), ("light", 390)])
def test_flipper_sensor_controls(browser, base_url, theme, width):
    context = browser.new_context(viewport={"width": width, "height": 1000})
    context.add_init_script(INIT_SCRIPT % theme)
    sent = []
    pending_starts = []

    def route_request(route):
        url = route.request.url
        if "/sensor/flipper/observations" in url:
            data = {
                "source": "flipper",
                "running": False,
                "state": "completed",
                "cursor": 1,
                "session_id": "synthetic",
                "frequency_hz": 433920000,
                "observations": [{"seq": 1, "text": "Synthetic <b>OOK</b> line"}],
            }
        elif url.endswith("/sensor/flipper"):
            data = {"configured": True, "can_receive": True, "preset": "OOK650", "max_duration_s": 30}
        elif url.endswith("/sensor/status"):
            data = {"running": False, "source": "rtl"}
        elif url.endswith("/start_sensor"):
            sent.append(route.request.post_data_json)
            pending_starts.append(route)
            return
        elif url.startswith(base_url):
            route.continue_()
            return
        else:
            route.abort()
            return
        route.fulfill(content_type="application/json", body=json.dumps(data))

    context.route("**/*", route_request)
    page = context.new_page()
    try:
        page.goto(base_url + "/?mode=sensor", wait_until="load")
        page.evaluate("switchMode('sensor')")
        if width < 768:
            page.locator("#mainSidebar").evaluate("el => el.classList.add('open')")
        page.locator("#sensorSource").select_option("flipper")
        expect(page.locator("#sensorGain")).to_be_disabled()
        expect(page.locator("#flipperSensorDuration")).to_be_visible()
        page.locator("#flipperSensorDuration").fill("5")
        page.locator("#startSensorBtn").click()
        expect(page.locator("#sensorSource")).to_be_disabled()
        expect(page.locator("#sensorFrequency")).to_be_disabled()
        page.wait_for_function("document.getElementById('stopSensorBtn').style.display !== 'none'")
        assert len(pending_starts) == 1
        pending_starts[0].fulfill(content_type='application/json', body=json.dumps({'status':'started','source':'flipper'}))
        expect(page.locator("#flipperSensorCount")).to_have_text("Observations: 1")
        assert sent == [{"source": "flipper", "frequency": "433.92", "duration_s": 5}]
        expect(page.locator("#flipperSensorOutput")).to_contain_text("Synthetic <b>OOK</b> line")
        assert page.locator("#flipperSensorOutput b").count() == 0
        expect(page.locator("#sensorSource")).to_be_enabled()
        page.locator("#sensorSource").select_option("rtl")
        expect(page.locator("#sensorGain")).to_be_enabled()
    finally:
        context.close()
