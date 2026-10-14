from snapshot_fakes import snapshot_reader, ScriptedSnapshots
from unittest.mock import Mock
from datetime import datetime, timedelta
import logging

import pytest

from gps_emi import cli
from gps_emi.cli import configure_logging as real_configure_logging
from gps_emi.config import WatchConfig
from gps_emi.errors import TransientAcquisitionError
from gps_emi.models import Vehicle
from gps_emi.monitoring.arrival import DESTINATIONS


@pytest.mark.parametrize('field', ['polling_interval', 'initial_backoff', 'max_backoff'])
@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_positive_finite_intervals(field, value):
    with pytest.raises(ValueError):
        WatchConfig(**{field: value})


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_stale_threshold_is_nonnegative_finite(value):
    with pytest.raises(ValueError):
        WatchConfig(stale_warning_seconds=value)


def test_backoff_cannot_start_above_cap():
    with pytest.raises(ValueError, match='max_backoff'):
        WatchConfig(initial_backoff=20, max_backoff=10)


def test_cli_passes_config_without_reading_env(monkeypatch):
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main(['--identifier', 'AMB-20', '--destination', DESTINATIONS[0],
                     '--interval', '17', '--initial-backoff', '2', '--max-backoff', '8',
                     '--stale-warning-seconds', '120', '--log-level', 'DEBUG']) == 0
    assert watch.call_args.args[3] == 17
    assert watch.call_args.kwargs == {
        'initial_backoff': 2, 'max_backoff': 8, 'stale_warning_seconds': 120, 'inactivity_seconds': 43200,
        'confirm_inside': cli._confirm_inside,
    }


@pytest.mark.parametrize('arguments', [
    ['--initial-backoff', '10', '--max-backoff', '5'],
    ['--stale-warning-seconds', 'nan'], ['--stale-warning-seconds', '-1'],
    ['--max-backoff', '0'],
])
def test_invalid_cli_configuration(arguments):
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments)
    assert caught.value.code == 2


def test_cli_logging_and_recovery_end_to_end_without_network(monkeypatch, capsys):
    # Ejecuta CLI, runner, monitor y notificador con el handler de consola real.
    logger = logging.getLogger('gps_emi')
    original_handlers, original_level, original_propagate = list(logger.handlers), logger.level, logger.propagate
    timestamp = datetime(2026, 9, 17, 12, 30)
    outside = Vehicle('433909', 'PJU886', timestamp, mobile_number='AMB-20')
    inside = Vehicle('433909', 'PJU886', timestamp + timedelta(minutes=1),
                     mobile_number='AMB-20', zones=[DESTINATIONS[0]])
    client = Mock()
    client.get_vehicles.side_effect = [[outside], TransientAcquisitionError(), [inside]]
    sleep = Mock()
    original_watch = cli.watch
    def injected_watch(*args, **kwargs):
        return original_watch(*args, **kwargs, sleep=sleep)
    monkeypatch.setattr(cli, 'watch', injected_watch)
    monkeypatch.setattr(cli, 'AcquisitionRuntime', lambda **kwargs: Mock(source=ScriptedSnapshots(client)))
    monkeypatch.setattr(cli, 'configure_logging', real_configure_logging)
    try:
        assert cli.main(['--identifier', 'AMB-20', '--destination', DESTINATIONS[0]]) == 0
        output = capsys.readouterr().out
        assert 'INFO: OUTSIDE' in output
        assert 'WARNING:' in output
        assert 'Adquisición recuperada' in output
        assert output.count('ARRIVAL_DETECTED') == 1
        assert 'PJU886 llegó a' in output
        assert 'Vigilancia completada.' in output
        sleep.assert_not_called()  # La planificación pertenece al coordinador.
    finally:
        for handler in list(logger.handlers):
            if handler not in original_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(original_level)
        logger.propagate = original_propagate
