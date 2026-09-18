from datetime import datetime
from unittest.mock import Mock
import uuid

import pytest

from gps_emi import cli
from gps_emi.errors import TransientAcquisitionError, SessionExpiredError
from gps_emi.models import Vehicle
from gps_emi.sites import EMI_SITES


@pytest.fixture
def prompts(monkeypatch):
    captured = []
    def install(answers):
        iterator = iter(answers)
        def answer(prompt):
            captured.append(prompt)
            return next(iterator)
        monkeypatch.setattr('builtins.input', answer)
    return install, captured


@pytest.fixture
def client(monkeypatch):
    source = Mock()
    source.get_vehicles.return_value = [Vehicle('433909', 'PJU886', datetime(2026, 9, 17, 12, 34),
                                               location='Dirección de prueba', speed=0, gps_fix=1,
                                               mobile_number='AMB-20', zones=[EMI_SITES[0]])]
    monkeypatch.setattr(cli, 'WideTechClient', lambda: source)
    return source


def test_option_one_watches_emi_without_site_prompt(monkeypatch, prompts, client, capsys):
    install, captured = prompts
    install(['1', 'AMB-20', '0'])
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main([]) == 0
    assert watch.call_args.args[1:4] == ('AMB-20', None, 30.0)
    assert captured == ['> ', 'Placa o número de móvil: ', '> ']
    output = capsys.readouterr().out
    assert 'Sede:' not in output and 'Destino:' not in output
    client.get_vehicles.assert_not_called()


@pytest.mark.parametrize('identifier', ['AMB-20', 'PJU886'])
def test_option_two_location_has_no_site_prompt(prompts, client, identifier, capsys):
    install, captured = prompts
    install(['2', identifier, '0'])
    assert cli.main([]) == 0
    client.get_vehicles.assert_called_once_with()
    output = capsys.readouterr().out
    assert 'AMB-20' in output and 'PJU886' in output and 'Dirección de prueba' in output
    assert 'Sede:' not in output and 'Destino:' not in output
    assert captured == ['> ', 'Placa o número de móvil: ', '> ']


@pytest.mark.parametrize('choice,site', [('1', EMI_SITES[0]), ('2', EMI_SITES[1])])
def test_option_three_alone_requests_site(prompts, client, choice, site, capsys):
    install, captured = prompts
    install(['3', choice, '0'])
    assert cli.main([]) == 0
    client.get_vehicles.assert_called_once_with()
    output = capsys.readouterr().out
    assert 'Sede:' in output and site in output
    assert 'Placa o número de móvil:' not in captured
    assert 'última posición reportada pertenece a esta geocerca' in output


def test_zero_exits_without_loading_configuration_or_query(monkeypatch, prompts, client):
    load = Mock()
    monkeypatch.setattr(cli, 'load_dotenv', load)
    prompts[0](['0'])
    assert cli.main([]) == 0
    load.assert_not_called()
    client.get_vehicles.assert_not_called()


def test_invalid_menu_allows_another_attempt(prompts, client, capsys):
    prompts[0](['?', '9', '2', 'AMB-20', '0'])
    assert cli.main([]) == 0
    assert capsys.readouterr().out.count('ERROR: seleccione 0, 1, 2 o 3.') == 2
    client.get_vehicles.assert_called_once()


def test_invalid_site_allows_another_attempt(prompts, client, capsys):
    prompts[0](['3', 'invalid', '1', '0'])
    assert cli.main([]) == 0
    assert 'ERROR: seleccione 1 o 2.' in capsys.readouterr().out
    client.get_vehicles.assert_called_once()


def test_repeated_queries_reuse_use_case_without_per_vehicle_requests(prompts, client):
    prompts[0](['2', 'AMB-20', '2', 'PJU886', '3', '1', '0'])
    assert cli.main([]) == 0
    assert client.get_vehicles.call_count == 3


@pytest.mark.parametrize('rows,message', [([], 'No se encontró el móvil'),
    ([Vehicle('1', 'X'), Vehicle('2', 'X')], 'identificador es ambiguo')])
def test_resolution_error_is_clear_and_returns_to_menu(prompts, client, rows, message, capsys):
    client.get_vehicles.return_value = rows
    prompts[0](['2', 'X', '0'])
    assert cli.main([]) == 0
    assert message in capsys.readouterr().out


@pytest.mark.parametrize('action,args', [
    ('location', ['--identifier', 'AMB-20']), ('site', ['--site', EMI_SITES[0]]),
])
def test_direct_queries_do_not_prompt(action, args, client, monkeypatch):
    def forbidden(*args):
        pytest.fail('Modo directo no debe solicitar input')
    monkeypatch.setattr('builtins.input', forbidden)
    assert cli.main(['--action', action, *args]) == 0
    client.get_vehicles.assert_called_once()


def test_legacy_destination_is_explicit_and_warns(monkeypatch, caplog):
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main(['--plate', 'AMB-20', '--destination', EMI_SITES[1]]) == 0
    assert watch.call_args.args[2] == EMI_SITES[1]
    assert '--destination está obsoleto' in caplog.text


def test_identifier_without_destination_uses_union(monkeypatch):
    watch = Mock(return_value=0)
    monkeypatch.setattr(cli, 'watch', watch)
    assert cli.main(['--identifier', 'AMB-20']) == 0
    assert watch.call_args.args[2] is None


@pytest.mark.parametrize('error_type', [TransientAcquisitionError, SessionExpiredError, RuntimeError])
def test_query_errors_are_safe_and_not_retried(error_type, client, caplog):
    marker = uuid.uuid4().hex
    client.get_vehicles.side_effect = error_type(marker)
    assert cli.main(['--action', 'location', '--identifier', 'AMB-20']) == 1
    client.get_vehicles.assert_called_once()
    assert marker not in caplog.text
    assert 'Traceback' not in caplog.text


def test_menu_ctrl_c(monkeypatch, caplog):
    monkeypatch.setattr('builtins.input', Mock(side_effect=KeyboardInterrupt()))
    assert cli.main([]) == 130
    assert 'Operación cancelada.' in caplog.text


def test_cancelled_watch_exits_menu(monkeypatch, prompts):
    prompts[0](['1', 'AMB-20'])
    monkeypatch.setattr(cli, 'watch', Mock(return_value=130))
    assert cli.main([]) == 130
