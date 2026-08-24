from app.core.config.audits import audit_execution_policy
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    measurement_route,
    measurement_routes_for_engine,
)


def test_every_engine_has_one_retrieval_enabled_route() -> None:
    expected = {
        ENGINE_CHATGPT: ("openai", "gpt-5.6-sol"),
        ENGINE_CLAUDE: ("anthropic", "claude-sonnet-5"),
        ENGINE_GEMINI: ("google", "gemini-3.6-flash"),
    }
    for engine, identity in expected.items():
        routes = measurement_routes_for_engine(engine)
        assert len(routes) == 1
        route = measurement_route(engine)
        assert (route.transport_provider, route.transport_model) == identity
        assert route.retrieval_enabled is True


def test_audit_policy_is_citation_capable() -> None:
    policy = audit_execution_policy()
    assert policy.retrieval_enabled is True
    assert "citation" in policy.answer_instruction.casefold()
