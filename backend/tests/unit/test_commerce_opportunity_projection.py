from types import SimpleNamespace

from app.domain.opportunities.category_citations import _citation_domain


def test_citation_domain_falls_back_to_url_host_and_normalizes_www() -> None:
    citation = SimpleNamespace(domain=None, url="https://WWW.Example.com/products/1")

    assert _citation_domain(citation) == "example.com"


def test_citation_domain_prefers_persisted_domain() -> None:
    citation = SimpleNamespace(domain="WWW.Canonical.example", url="https://other.test")

    assert _citation_domain(citation) == "canonical.example"
