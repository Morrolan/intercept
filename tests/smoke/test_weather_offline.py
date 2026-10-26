"""The offline form submits both legacy Meteor formats and arbitrary rates."""

import json

import pytest

from .test_pages_load import INIT_SCRIPT


@pytest.mark.parametrize("theme,width", [("dark", 1600), ("light", 1600), ("dark", 390), ("light", 390)])
def test_offline_recording_controls(browser, base_url, theme, width):
    context = browser.new_context(viewport={"width": width, "height": 1000})
    context.add_init_script(INIT_SCRIPT % theme)
    sent = []

    def requests(route):
        if route.request.url.endswith("/weather-sat/test-decode"):
            sent.append(route.request.post_data_json)
            route.fulfill(content_type="application/json", body=json.dumps({
                "status": "error", "message": "Decode request captured by browser test",
            }))
        elif route.request.url.startswith(base_url):
            route.continue_()
        else:
            route.abort()

    context.route("**/*", requests)
    page = context.new_page()
    try:
        page.goto(base_url + "/?mode=weathersat", wait_until="load")
        page.wait_for_function("typeof window.switchMode === 'function'")
        page.evaluate("switchMode('weathersat')")
        page.wait_for_function("typeof WeatherSat !== 'undefined'")
        page.wait_for_timeout(200)  # Sidebar remembers its open sections after mode initialisation.
        if width < 768:
            # Scope this test to the form, independent of the navigation drawer's handlers.
            page.locator("#mainSidebar").evaluate("el => el.classList.add('open')")
        page.locator("#weatherSatMode h3").filter(has_text="Offline Decode").click()
        assert page.locator(".wxsat-test-decode-body").filter(has=page.locator("#wxsatTestSatSelect")).evaluate(
            "el => el.scrollHeight <= el.clientHeight + 1"
        ), "Expanded offline form clips its controls"
        for satellite, filename, rate in [
            ("METEOR-M2", "LRPT_16-29-02_137900kHz.wav", "187500"),
            ("METEOR-HRPT", "METEOR_HRPT.wav", "3000000"),
        ]:
            page.locator("#wxsatTestSatSelect").select_option(satellite)
            page.locator("#wxsatTestFilePath").fill("data/weather_sat/" + filename)
            page.locator("#wxsatTestSampleRate").fill(rate)
            with page.expect_response(lambda response: response.url.endswith("/weather-sat/test-decode")):
                page.get_by_role("button", name="Decode File", exact=True).click(timeout=5000)
            assert sent[-1] == {
                "satellite": satellite, "input_file": "data/weather_sat/" + filename, "sample_rate": int(rate),
            }
        page.locator("#wxsatTestSampleRate").fill("999")
        page.evaluate("WeatherSat.testDecode()")
        assert len(sent) == 2
    finally:
        context.close()
