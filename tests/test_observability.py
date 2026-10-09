import io
import logging
from unittest.mock import Mock
import pytest
from gps_emi import observability
from gps_emi.errors import SessionExpiredError, TransientAcquisitionError, InvalidResponseError, EmptyResponseError
from gps_emi.providers import widetech


@pytest.fixture
def metrics(monkeypatch):
    stats = observability.Metrics(now=lambda: 10)
    monkeypatch.setattr(widetech, 'metrics', stats)
    return stats


def test_healthy_cycles_debug_and_state_change_only_info(metrics, caplog, monkeypatch):
    source = widetech.LegacyWideTechTransport()
    monkeypatch.setattr(source, 'load_data_log', lambda: '{"Rows":[]}')
    for _ in range(20):
        assert source.get_vehicles() == []
    records = [r for r in caplog.records if r.name == 'gps_emi.provider']
    assert len(records) == 1 and 'PROVIDER_OK' in records[0].message
    assert metrics.values['acquisitions'] == 20
    caplog.set_level(logging.DEBUG, logger='gps_emi.provider')
    source.get_vehicles()
    assert 'records=0 vehicles=0 duration_ms=' in caplog.text


@pytest.mark.parametrize('error,status', [(SessionExpiredError,'SESSION_EXPIRED'),
    (TransientAcquisitionError,'NETWORK_ERROR'), (InvalidResponseError,'MALFORMED_RESPONSE'),
    (EmptyResponseError,'EMPTY_RESPONSE')])
def test_failure_categories_and_recovery_never_log_payload(metrics, caplog, error, status):
    source = widetech.LegacyWideTechTransport()
    source.load_data_log = Mock(side_effect=error('Authorization: DO_NOT_LOG_SECRET cookie=DO_NOT_LOG_SECRET'))
    for _ in range(2):
        with pytest.raises(error):
            source.get_vehicles()
    assert caplog.text.count('provider_status=' + status) == 1
    source.load_data_log = Mock(return_value='{"Rows":[]}')
    source.get_vehicles()
    assert 'provider recovered downtime_seconds=' in caplog.text
    assert 'DO_NOT_LOG_SECRET' not in caplog.text


def test_safe_summary(metrics, caplog):
    metrics.update(active_watches=2, collection_session='COLLECTING')
    metrics.increment(observations_written=10)
    metrics.summary()
    assert 'active_watches=2' in caplog.text and 'observations_written=10' in caplog.text
    assert 'uptime_seconds=' in caplog.text


def test_logging_configuration_idempotent_and_env(monkeypatch):
    logger = logging.getLogger('gps_emi')
    original = logger.handlers[:], logger.level, logger.propagate
    stream = io.StringIO()
    monkeypatch.setattr('sys.stdout', stream)
    monkeypatch.setenv('LOG_LEVEL','DEBUG')
    try:
        observability.configure_logging()
        observability.configure_logging()
        logging.getLogger('gps_emi.synthetic').debug('safe event')
        assert stream.getvalue().count('safe event') == 1
        assert 'gps_emi.synthetic' in stream.getvalue()
        assert '-05:00' in stream.getvalue()
    finally:
        for handler in logger.handlers:
            if handler not in original[0]:
                handler.close()
        logger.handlers, logger.level, logger.propagate = original
