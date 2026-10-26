"""Offline recordings must reach SatDump as the signal actually stored on disk."""

import os
import wave
from unittest.mock import MagicMock, patch

import pytest

from utils.weather_sat import WeatherSatDecoder


@pytest.fixture
def offline(tmp_path):
    with (
        patch("utils.weather_sat.shutil.which", return_value="/usr/bin/satdump"),
        patch("utils.weather_sat.ALLOWED_OFFLINE_INPUT_DIRS", (tmp_path,)),
        patch("utils.weather_sat.register_process"),
        patch("utils.weather_sat.time.sleep"),
        patch("utils.weather_sat.threading.Thread.start"),
        patch("utils.weather_sat.subprocess.Popen") as popen,
    ):
        popen.return_value.poll.return_value = None
        decoder = WeatherSatDecoder(output_dir=tmp_path / "output")
        yield decoder, popen
        decoder._running = False
        if decoder._pty_master_fd is not None:
            os.close(decoder._pty_master_fd)


def recording(path, rate, channels=2, width=2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\0" * 100 * channels * width)
    return path


@pytest.mark.parametrize("satellite,pipeline,rate", [
    ("METEOR-M2", "meteor_m2_lrpt", 187500),
    ("METEOR-HRPT", "meteor_hrpt", 3000000),
    ("METEOR-M2-3", "meteor_m2-x_lrpt", 187500),
])
def test_iq_wav_uses_baseband_and_header_rate(offline, tmp_path, satellite, pipeline, rate):
    decoder, popen = offline
    path = recording(tmp_path / "sample.wav", rate)
    success, error = decoder.start_from_file(satellite, str(path), sample_rate=2400000)
    assert success, error
    argv = popen.call_args.args[0]
    assert argv[:4] == ["satdump", pipeline, "baseband", str(path)]
    assert argv[argv.index("--samplerate") + 1] == str(rate)
    assert argv[argv.index("--baseband_format") + 1] == "cs16"


@pytest.mark.parametrize("channels,width", [(1, 2), (2, 3)])
def test_meteor_rejects_audio_or_unsupported_wav_before_launch(offline, tmp_path, channels, width):
    decoder, popen = offline
    path = recording(tmp_path / "sample.wav", 187500, channels, width)
    success, error = decoder.start_from_file("METEOR-M2-3", str(path))
    assert not success
    assert "WAV" in error
    popen.assert_not_called()


def test_malformed_wav_has_actionable_error(offline, tmp_path):
    decoder, popen = offline
    path = tmp_path / "sample.wav"
    path.write_bytes(b"not a wave recording")
    success, error = decoder.start_from_file("METEOR-M2-3", str(path))
    assert not success
    assert "WAV" in error
    popen.assert_not_called()


def test_apt_audio_wav_still_uses_audio_decoder(offline, tmp_path):
    decoder, popen = offline
    path = recording(tmp_path / "audio.wav", 11025, channels=1)
    success, error = decoder.start_from_file("NOAA-18", str(path))
    assert success, error
    argv = popen.call_args.args[0]
    assert argv[1:3] == ["noaa_apt", "audio_wav"]


@pytest.mark.parametrize("satellite,mode,frequency", [
    ("METEOR-M2", "LRPT", 137.9),
    ("METEOR-HRPT", "HRPT", 1700.0),
    ("METEOR-M2-3", "LRPT", 137.9),
])
def test_saved_image_metadata_survives_restart(tmp_path, satellite, mode, frequency):
    output = tmp_path / "images"
    output.mkdir()
    (output / f"{satellite}_20261026_130000_channel_1.png").write_bytes(b"\0" * 2048)
    with patch("utils.weather_sat.shutil.which", return_value="/usr/bin/satdump"):
        restored = WeatherSatDecoder(output_dir=output)
    images = restored.get_images()
    assert len(images) == 1
    assert (images[0].satellite, images[0].mode, images[0].frequency) == (satellite, mode, frequency)


@pytest.mark.parametrize("satellite", ["METEOR-M2", "METEOR-HRPT"])
def test_offline_profiles_accepted_by_route(client, tmp_path, satellite):
    decoder = MagicMock()
    decoder.is_running = False
    decoder.start_from_file.return_value = (True, None)
    path = recording(tmp_path / "sample.wav", 187500)
    with (
        patch("routes.weather_sat.is_weather_sat_available", return_value=True),
        patch("routes.weather_sat.ALLOWED_TEST_DECODE_DIRS", (tmp_path,)),
        patch("routes.weather_sat.get_weather_sat_decoder", return_value=decoder),
    ):
        response = client.post("/weather-sat/test-decode", json={
            "satellite": satellite, "input_file": str(path), "sample_rate": 187500,
        })
        assert response.status_code == 200
        assert response.json["status"] == "started"
        # Offline-only profiles must not start a live receiver.
        response = client.post("/weather-sat/start", json={"satellite": satellite})
        assert response.status_code == 400
