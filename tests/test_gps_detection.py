"""Automatic GPS discovery must not seize unrelated USB serial devices."""
from unittest.mock import patch

import pytest

from utils.gps import detect_gps_devices


def test_gps_only_excludes_generic_serial_bridges():
    paths = {'/dev/ttyUSB*': ['/dev/ttyUSB0', '/dev/ttyUSB1'], '/dev/ttyACM*': []}
    descriptions = {'/dev/ttyUSB0': 'Silicon Labs CP2102 USB to UART Bridge', '/dev/ttyUSB1': 'u-blox GNSS receiver'}
    with patch('platform.system', return_value='Linux'), patch('glob.glob', side_effect=lambda p: paths[p]), patch('os.path.isdir', return_value=False), patch('utils.gps._describe_device_linux', side_effect=lambda p: descriptions[p]):
        assert detect_gps_devices(gps_only=True) == [{'path': '/dev/ttyUSB1', 'description': descriptions['/dev/ttyUSB1']}]
        assert len(detect_gps_devices()) == 2  # Manual selection still sees both.


@pytest.mark.parametrize("gpsd_running", [False, True])
def test_auto_connect_never_claims_generic_serial(client, gpsd_running):
    with (
        patch('routes.gps.get_gps_reader', return_value=None),
        patch('routes.gps.is_gpsd_running', return_value=gpsd_running),
        patch('routes.gps.gpsd_devices', return_value=[]),
        patch('platform.system', return_value='Linux'),
        patch('glob.glob', side_effect=lambda p: ['/dev/ttyUSB0'] if p == '/dev/ttyUSB*' else []),
        patch('os.path.isdir', return_value=False),
        patch('utils.gps._describe_device_linux', return_value='Silicon Labs CP2102 USB to UART Bridge'),
        patch('routes.gps.start_gpsd_daemon') as start,
        patch('routes.gps.add_device_to_gpsd') as add,
    ):
        assert client.post('/gps/auto-connect').get_json()['status'] == 'unavailable'
        start.assert_not_called()
        add.assert_not_called()
