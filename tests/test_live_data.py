from mila.config import Settings
from mila.services.live_data import LiveDataService


class Response:
    def __init__(self, records):
        self.records = records

    def raise_for_status(self):
        return None

    def json(self):
        return self.records


class FakeHTTPClient:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def get(self, endpoint, params):
        self.calls.append((endpoint, params))
        return Response(self.records)


def test_supported_professional_filters_normalize_user_text():
    settings = Settings(_env_file=None, groq_api_key="test")
    client = FakeHTTPClient([])
    live = LiveDataService(settings, client)
    filters = live.filters_for("profissionais online com DEPRESSÃO", "profissionais")
    assert filters == {"modalidade": "VIRTUAL", "especialidade": "depressao"}


def test_live_cache_and_public_fields_only():
    settings = Settings(_env_file=None, groq_api_key="test")
    client = FakeHTTPClient([{
        "id": "private-id",
        "nome": "Profissional público",
        "tipo": "PSICOLOGO",
        "bio": "Bio pública",
        "tags": ["ansiedade"],
        "email": "private@example.test",
        "status": "APROVADO",
    }])
    live = LiveDataService(settings, client)
    first = live.records("profissionais", {})
    second = live.records("profissionais", {})
    assert first == second
    assert len(client.calls) == 1
    assert set(first[0]) == {"nome", "tipo", "bio", "tags"}


def test_plans_use_a_five_minute_cache_and_only_public_fields():
    settings = Settings(_env_file=None, groq_api_key="test")
    client = FakeHTTPClient([{
        "id": "private-id",
        "nome": "Start",
        "vagasTotais": 30,
        "porteIndicado": "Pequeno",
        "precoMensalPorColaborador": 129.00,
        "consultasSemLimite": True,
        "billingToken": "private",
    }])
    live = LiveDataService(settings, client)
    records = live.records("planos", {})
    assert set(records[0]) == {
        "nome", "vagasTotais", "porteIndicado",
        "precoMensalPorColaborador", "consultasSemLimite",
    }
    assert client.calls == [("/v1/planos", {})]
